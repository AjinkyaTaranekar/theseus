"""Graph changes become catalog operations backed by real fixture evidence (E6)."""

from __future__ import annotations

import json

import pytest

from tests.golden.conftest import deps_for, world
from theseus.adapters.aws.changes import ops_for
from theseus.adapters.aws.ops import parse
from theseus.contracts.adapters import Change
from theseus.contracts.engine import GraphState
from theseus.contracts.result import EdgeRow, Evidence, PatchOp
from theseus.engine.pipeline import prepare_state
from theseus.errors import PatchError


def state(scenario: str = "intern") -> GraphState:
    deps = deps_for(scenario)
    prepared, _ = prepare_state(world(scenario, "head"), "head", deps)
    return prepared


def edge(head: GraphState, kind: str, source: str, target: str) -> EdgeRow:
    return next(e for e in head.rows.edges if (e.type, e.src, e.dst) == (kind, source, target))


def translate(head: GraphState, change: Change) -> list[PatchOp]:
    result = ops_for(change, head.rows, head.world.resources)
    assert all(parse(operation) is not None for operation in result)
    return result


def test_remove_membership_names_the_graph_principal_and_group() -> None:
    head = state()
    membership = edge(head, "MEMBER_OF", "user:priya-intern", "group:support-engineers")
    got = translate(head, Change(kind="remove_edge", eid=membership.eid))
    assert [(operation.op, operation.args) for operation in got] == [
        ("remove_membership", {"user": "priya-intern", "group": "support-engineers"})
    ]


def test_assumption_removal_edits_the_callers_permission_and_keeps_role_trust() -> None:
    head = state()
    grant = edge(head, "CAN_ASSUME", "group:support-engineers", "role:prod-support")
    got = translate(head, Change(kind="remove_edge", eid=grant.eid))
    assert [(operation.op, operation.args) for operation in got] == [
        (
            "remove_statement",
            {"policy_address": "aws_iam_group_policy.support_assume", "sid": "AssumeProdSupport"},
        )
    ]


def test_remove_shared_policy_uses_its_statement_not_an_attachment() -> None:
    head = state()
    grant = edge(head, "CAN", "role:orders-api-task", "dynamodb:demo-orders")
    got = translate(head, Change(kind="remove_edge", eid=grant.eid))
    assert [operation.args for operation in got] == [
        {"policy_address": "aws_iam_policy.orders_table_rw", "sid": "OrdersTableReadWrite"}
    ]
    deps = deps_for("intern")
    patched = deps.adapters.cloud.apply_ops(head.world.resources, got)
    policy = next(r for r in patched if r.address == "aws_iam_policy.orders_table_rw")
    assert json.loads(policy.values["policy"])["Statement"] == []


def test_public_bucket_revert_and_scope_down_come_from_policy_evidence() -> None:
    head = state("public-bucket")
    grant = edge(head, "CAN", "entry:internet", "s3://demo-company-files/invoices/")
    removed = translate(head, Change(kind="remove_edge", eid=grant.eid))
    scoped = translate(
        head, Change(kind="narrow_grant", eid=grant.eid, values=["s3://demo-company-files/public/"])
    )
    assert [(operation.op, operation.args) for operation in removed] == [
        (
            "remove_statement",
            {"policy_address": "aws_s3_bucket_policy.company_files_public", "sid": "PublicRead"},
        )
    ]
    assert [(operation.op, operation.args) for operation in scoped] == [
        (
            "set_statement_resources",
            {
                "policy_address": "aws_s3_bucket_policy.company_files_public",
                "sid": "PublicRead",
                "resources": ["arn:aws:s3:::demo-company-files/public/*"],
            },
        )
    ]


def test_restrict_trust_uses_the_declared_role_and_subjects() -> None:
    head = state()
    trust = edge(head, "TRUSTS", "workflow:demo-org/docs-site/preview.yml", "role:github-deploy")
    subjects = ["repo:demo-org/infra:ref:refs/heads/main"]
    got = translate(head, Change(kind="restrict_trust", eid=trust.eid, values=subjects))
    assert [(operation.op, operation.args) for operation in got] == [
        ("set_oidc_sub", {"role": "github-deploy", "patterns": subjects})
    ]


def test_conditional_deny_names_exact_principals_actions_and_target() -> None:
    head = state()
    grant = edge(head, "CAN", "role:prod-support", "secret:prod-db-credentials")
    got = translate(head, Change(kind="deny_principal", eid=grant.eid, values=["user:priya-intern"]))
    assert len(got) == 1 and got[0].op == "add_policy"
    assert got[0].args["principal"] == "role:prod-support"
    (statement,) = got[0].args["statements"]
    assert statement["effect"] == "Deny"
    assert statement["actions"] == ["secretsmanager:GetSecretValue"]
    assert statement["resources"] == [
        "arn:aws:secretsmanager:eu-west-1:111122223333:secret:prod-db-credentials-*"
    ]
    assert statement["condition"] == {
        "op": "StringEquals",
        "key": "aws:PrincipalArn",
        "value": ["arn:aws:iam::111122223333:user/priya-intern"],
    }


def test_translation_is_order_independent_and_does_not_mutate_inputs() -> None:
    head = state("public-bucket")
    before = head.model_dump_json()
    grant = edge(head, "CAN", "entry:internet", "s3://demo-company-files/invoices/")
    change = Change(kind="narrow_grant", eid=grant.eid, values=["s3://demo-company-files/public/"])
    expected = translate(head, change)
    shuffled = head.model_copy(deep=True)
    shuffled.rows.nodes.reverse()
    shuffled.rows.edges.reverse()
    shuffled.world.resources.reverse()
    assert translate(shuffled, change) == expected
    assert head.model_dump_json() == before


def test_unexpressible_edges_return_no_operations() -> None:
    head = state()
    unlock = next(e for e in head.rows.edges if e.type == "UNLOCKS")
    assert translate(head, Change(kind="remove_edge", eid=unlock.eid)) == []


def test_unknown_edge_id_is_rejected() -> None:
    head = state()
    with pytest.raises(PatchError):
        translate(head, Change(kind="remove_edge", eid="not-in-this-build"))


def test_missing_or_ambiguous_statement_evidence_is_not_guessed() -> None:
    head = state()
    grant = edge(head, "CAN", "role:orders-api-task", "dynamodb:demo-orders")
    grant.evidence = [Evidence(address="unknown", file="unknown", note="source not available")]
    assert translate(head, Change(kind="remove_edge", eid=grant.eid)) == []


@pytest.mark.parametrize("kind", ["narrow_grant", "deny_principal", "restrict_trust"])
def test_empty_changes_do_not_turn_into_broad_or_destructive_operations(kind: str) -> None:
    head = state("public-bucket")
    grant = edge(head, "CAN", "entry:internet", "s3://demo-company-files/invoices/")
    with pytest.raises(PatchError):
        translate(head, Change(kind=kind, eid=grant.eid, values=[]))


def test_narrowing_to_an_unknown_resource_is_rejected() -> None:
    head = state("public-bucket")
    grant = edge(head, "CAN", "entry:internet", "s3://demo-company-files/invoices/")
    with pytest.raises(PatchError):
        translate(head, Change(kind="narrow_grant", eid=grant.eid, values=["data:invented"]))


def test_the_existing_adapter_protocol_uses_the_translator() -> None:
    head = state()
    grant = edge(head, "CAN", "role:orders-api-task", "dynamodb:demo-orders")
    change = Change(kind="remove_edge", eid=grant.eid)
    deps = deps_for("intern")
    assert deps.adapters.cloud.ops_for(change, head.rows, head.world.resources) == translate(head, change)


def test_ambiguous_sids_do_not_produce_statement_edits() -> None:
    head = state()
    grant = edge(head, "CAN", "role:orders-api-task", "dynamodb:demo-orders")
    policy = next(r for r in head.world.resources if r.address == "aws_iam_policy.orders_table_rw")
    document = json.loads(policy.values["policy"])
    document["Statement"].append(dict(document["Statement"][0]))
    policy.values["policy"] = json.dumps(document)
    assert translate(head, Change(kind="remove_edge", eid=grant.eid)) == []


def test_conditional_deny_is_unknown_when_the_simulator_checks_it() -> None:
    from theseus.contracts.engine import CandidateDraft
    from theseus.engine.pipeline import config_requirements
    from theseus.engine.simulate import simulate
    from theseus.graph.load import load_graph

    head = state()
    grants = [
        edge(head, "CAN", "role:prod-support", target)
        for target in ["s3://demo-company-files/invoices/", "secret:prod-db-credentials"]
    ]
    operations = [
        operation
        for grant in grants
        for operation in translate(
            head, Change(kind="deny_principal", eid=grant.eid, values=["user:priya-intern"])
        )
    ]
    deps = deps_for("intern")
    load_graph(deps.store, head)
    draft = CandidateDraft(
        id="C", source="rule", proposed_by="theseus", title="Conditional deny", ops=operations
    )
    result = simulate(
        deps.store, head, draft, ["user:priya-intern"], config_requirements(head.world), deps.adapters
    )
    assert result.verdict == "unknown" and result.unknown


def test_secret_deny_preserves_a_known_arn_instead_of_widening_it() -> None:
    head = state()
    target = next(n for n in head.rows.nodes if n.id == "secret:prod-db-credentials")
    source = next(r for r in head.world.resources if r.address == target.props["address"])
    known = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:prod-db-credentials-XyZ123"
    source.values["arn"] = known
    target.props["arn_pattern"] = known
    grant = edge(head, "CAN", "role:prod-support", target.id)
    (operation,) = translate(head, Change(kind="deny_principal", eid=grant.eid, values=["user:priya-intern"]))
    assert operation.args["statements"][0]["resources"] == [known]


@pytest.mark.parametrize(
    "action,resource,broad",
    [
        ("s3:GetObject", "arn:aws:s3:::files/public/*", False),
        ("s3:ListBucket", "arn:aws:s3:::files", False),
        ("s3:GetObject", "arn:aws:s3:::files/*", True),
        ("s3:*", "arn:aws:s3:::files/public/*", True),
        ("s3:GetObject", "*", True),
        ("s3:GetObject", "arn:aws:s3:::*/public/*", True),
        ("secretsmanager:GetSecretValue", "arn:aws:secretsmanager:eu-west-1:123:secret:named-*", False),
        ("secretsmanager:GetSecretValue", "arn:aws:secretsmanager:*:*:secret:*", True),
    ],
)
def test_added_statement_breadth_is_checked_by_the_adapter(action: str, resource: str, broad: bool) -> None:
    operation = PatchOp(
        provider="aws",
        op="add_policy",
        args={
            "principal": "role:prod-support",
            "statements": [{"sid": "Read", "effect": "Allow", "actions": [action], "resources": [resource]}],
        },
    )
    assert deps_for("intern").adapters.cloud.patch_traits([operation]).adds_broad_wildcard is broad


def test_remove_statement_honors_selected_evidence_only() -> None:
    head = state()
    grant = edge(head, "CAN", "role:prod-support", "secret:prod-db-credentials")
    changed = grant.model_copy(
        update={
            "evidence": [
                *grant.evidence,
                Evidence(
                    address="aws_iam_group_policy.support_assume",
                    part="AssumeProdSupport",
                    file="main.tf",
                    line=1,
                ),
            ]
        }
    )
    head.rows.edges = [changed if e.eid == grant.eid else e for e in head.rows.edges]
    got = translate(head, Change(kind="remove_edge", eid=grant.eid, evidence=grant.evidence))
    assert len(got) == 1
    assert got[0].args["policy_address"] != "aws_iam_group_policy.support_assume"


def test_revert_does_not_delete_an_old_statement_newly_visible_in_the_graph() -> None:
    head = state("public-bucket")
    grant = edge(head, "CAN", "entry:internet", "s3://demo-company-files/invoices/")
    change = Change(kind="remove_edge", eid=grant.eid, evidence=grant.evidence, added_only=True)
    # New modeled resources can expose edges from an unchanged pre-existing statement.
    assert ops_for(change, head.rows, head.world.resources, base_resources=head.world.resources) == []
    assert ops_for(change, head.rows, head.world.resources, base_resources=[]) != []
    assert ops_for(change, head.rows, head.world.resources) == []
