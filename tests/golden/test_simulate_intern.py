"""Engine-verified candidate verdicts and graph-copy parity, without model or cloud calls (E5)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from tests.golden.conftest import deps_for, expected, world
from tests.unit.adapters.aws.test_patch import op
from theseus.config import get_settings
from theseus.contracts.engine import CandidateDraft, Deps, GraphState
from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow, PatchOp, Requirement
from theseus.engine.analyze import analyze
from theseus.engine.pipeline import config_requirements, prepare_state
from theseus.engine.simulate import simulate
from theseus.graph.client import get_client
from theseus.graph.load import apply_delta, delta, load_graph
from theseus.graph.store import FalkorStore, MemoryStore
from theseus.importer.build import build_rows


class ObservedStore(MemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.copies: list[tuple[str, str]] = []
        self.loads: list[str] = []

    def copy(self, src: str, dst: str) -> None:
        self.copies.append((src, dst))
        super().copy(src, dst)

    def load(self, graph: str, rows: GraphRows) -> None:
        self.loads.append(graph)
        super().load(graph, rows)


def draft(identifier: str, operations: list[PatchOp]) -> CandidateDraft:
    return CandidateDraft(
        id=identifier, source="rule", proposed_by="theseus", title="Test candidate", ops=operations
    )


def intern() -> tuple[Deps, GraphState, list[Requirement]]:
    deps = deps_for("intern")
    head, _ = prepare_state(world("intern", "head"), "head", deps)
    reqs = [
        *config_requirements(head.world),
        Requirement(
            id="I1",
            principal="user:priya-intern",
            access="read",
            resource="s3://demo-app-logs/",
            source="intent",
        ),
    ]
    return deps, head, reqs


def fix_b() -> CandidateDraft:
    return draft(
        "B",
        [
            op("remove_membership", user="priya-intern", group="support-engineers"),
            op(
                "add_role",
                name="intern-onboarding",
                trust_principals=["user:priya-intern"],
                statements=[
                    {
                        "sid": "ReadAppLogs",
                        "effect": "Allow",
                        "actions": ["s3:GetObject", "s3:ListBucket"],
                        "resources": ["arn:aws:s3:::demo-app-logs", "arn:aws:s3:::demo-app-logs/*"],
                    }
                ],
            ),
            op(
                "add_policy",
                principal="user:priya-intern",
                statements=[
                    {
                        "sid": "AssumeOnboarding",
                        "effect": "Allow",
                        "actions": ["sts:AssumeRole"],
                        "resources": ["arn:aws:iam::111122223333:role/intern-onboarding"],
                    }
                ],
            ),
        ],
    )


def test_intern_fix_b_passes_and_revert_a_breaks_i1() -> None:
    deps, head, reqs = intern()
    store = ObservedStore()
    load_graph(store, head)
    snapshot = head.model_dump_json()
    who = ["user:priya-intern"]
    before = analyze(store, head, reqs, who)
    b = simulate(store, head, fix_b(), who, reqs, deps.adapters)
    a = simulate(
        store,
        head,
        draft("A", [op("remove_membership", user="priya-intern", group="support-engineers")]),
        who,
        reqs,
        deps.adapters,
    )
    assert b.verdict == expected("intern")["candidates"]["B"] == "pass"
    assert b.paths_left == b.new_paths == b.requirements_broken == b.calls_broken == b.unknown == []
    assert a.verdict == expected("intern")["candidates"]["A"] == "fail"
    assert a.requirements_broken == ["I1"]
    assert "I1" in a.reason
    assert len(store.copies) == 2 and all(src == head.name for src, _ in store.copies)
    assert store.loads == [head.name]  # candidate graphs must come from COPY, never load/replacement
    assert len(set(dst for _, dst in store.copies)) == 2
    assert head.model_dump_json() == snapshot
    assert analyze(store, head, reqs, who) == before
    assert all(dst in store.list_graphs() for _, dst in store.copies)
    assert simulate(store, head, fix_b(), who, reqs, deps.adapters) == b


def test_invalid_op_still_has_an_independent_candidate_copy() -> None:
    deps, head, reqs = intern()
    store = ObservedStore()
    load_graph(store, head)
    got = simulate(
        store,
        head,
        draft("H1", [op("remove_statement", policy_address="missing", sid="X")]),
        ["user:priya-intern"],
        reqs,
        deps.adapters,
    )
    assert got.verdict == "invalid" and got.reason
    assert len(store.copies) == 1
    assert got.ops and got.proposed_by == "theseus"
    assert store.paths(head.name, "user:priya-intern")


def test_noop_fails_for_remaining_certain_dangerous_paths() -> None:
    deps, head, reqs = intern()
    load_graph(deps.store, head)
    before = analyze(deps.store, head, reqs, ["user:priya-intern"])
    got = simulate(deps.store, head, draft("H1", []), ["user:priya-intern"], reqs, deps.adapters)
    assert got.verdict == "fail"
    assert got.paths_left == sorted(p.id for p in before.dangerous)


def test_shared_policy_statement_removal_changes_both_attached_roles() -> None:
    deps, head, _ = intern()
    changed = head.world.model_copy(
        update={
            "resources": deps.adapters.cloud.apply_ops(
                head.world.resources,
                [
                    op(
                        "remove_statement",
                        policy_address="aws_iam_policy.orders_table_rw",
                        sid="OrdersTableReadWrite",
                    )
                ],
            )
        },
        deep=True,
    )
    labels = {n.id: n.sensitivity for n in head.rows.nodes if n.sensitivity is not None}
    patched = build_rows(changed, labels, deps.adapters)
    roles = {"role:orders-api-task", "role:orders-worker-task"}
    assert {
        e.src
        for e in head.rows.edges
        if e.type == "CAN" and e.src in roles and e.dst == "dynamodb:demo-orders"
    } == roles
    assert not [
        e for e in patched.edges if e.type == "CAN" and e.src in roles and e.dst == "dynamodb:demo-orders"
    ]


def test_sensitive_unapproved_intent_does_not_make_a_fix_fail() -> None:
    deps, head, reqs = intern()
    load_graph(deps.store, head)
    unapproved = Requirement(
        id="I2", principal="user:priya-intern", access="read", resource="db:customer-db", source="intent"
    )
    got = simulate(deps.store, head, fix_b(), ["user:priya-intern"], [*reqs, unapproved], deps.adapters)
    assert got.verdict == "pass" and got.requirements_broken == []


@pytest.mark.parametrize("break_required,verdict", [(False, "unknown"), (True, "fail")])
def test_remaining_unknown_path_has_unknown_verdict(break_required: bool, verdict: str) -> None:
    deps, head, reqs = intern()
    operations = [
        op(
            "add_policy",
            principal=principal,
            statements=[
                {
                    "sid": "Maybe",
                    "effect": "Deny",
                    "actions": ["secretsmanager:GetSecretValue", "s3:GetObject"],
                    "resources": ["*"],
                    "condition": {
                        "op": "StringNotEquals",
                        "key": "aws:PrincipalArn",
                        "value": "arn:aws:iam::111122223333:user/priya-intern",
                    },
                }
            ],
        )
        for principal in ["role:prod-support", "role:analytics-read"]
    ]
    if break_required:
        operations.append(op("remove_membership", user="sam-support", group="support-engineers"))
    load_graph(deps.store, head)
    got = simulate(deps.store, head, draft("C", operations), ["user:priya-intern"], reqs, deps.adapters)
    assert got.verdict == verdict and got.unknown


EV = [Evidence(address="synthetic", file="unknown", note="hand-built graph for delta regression")]


def small_rows() -> GraphRows:
    return GraphRows(
        nodes=[
            NodeRow(id="user:u", name="u", labels=["Node", "Principal", "User"]),
            NodeRow(
                id="data:d",
                name="d",
                labels=["Node", "Resource", "Database"],
                category="Database",
                sensitive=True,
                sensitivity="regulated",
            ),
        ],
        edges=[
            EdgeRow(
                eid="e1",
                type="CAN",
                src="user:u",
                dst="data:d",
                kind="configured",
                grants=["read"],
                evidence=EV,
            )
        ],
    )


@pytest.mark.parametrize("change", ["eid", "grants", "evidence", "kind", "props", "node", "labels", "remove"])
def test_delta_keeps_store_in_sync_with_rebuilt_rows(change: str) -> None:
    old = small_rows()
    new = old.model_copy(deep=True)
    edge = new.edges[0]
    if change == "eid":
        edge.eid = "e2"
    elif change == "grants":
        edge.grants = ["read", "write"]
    elif change == "evidence":
        edge.evidence = [Evidence(address="other", file="unknown", note="another test input")]
    elif change == "kind":
        edge.kind = "unknown"
    elif change == "props":
        edge.props = {"test": "updated"}
    elif change == "node":
        new.nodes[1].sensitive = False
    elif change == "labels":
        new.nodes[1].labels.append("Extra")
    else:
        new.nodes = new.nodes[:1]
        new.edges = []
    before = old.model_dump_json()
    changes = delta(old, new)
    assert changes == delta(old.model_copy(update={"nodes": list(reversed(old.nodes))}), new)
    store = MemoryStore()
    store.load("candidate", old)
    apply_delta(store, "candidate", changes)
    assert sorted(store._rows("candidate").nodes, key=lambda n: n.id) == sorted(new.nodes, key=lambda n: n.id)
    assert sorted(store._rows("candidate").edges, key=lambda e: e.eid) == sorted(
        new.edges, key=lambda e: e.eid
    )
    assert analyze(
        store, GraphState(name="candidate", world=world("intern", "head"), rows=new), [], ["user:u"]
    )
    assert old.model_dump_json() == before


def test_unchanged_rows_produce_an_empty_delta() -> None:
    rows = small_rows()
    got = delta(rows, rows.model_copy(deep=True))
    assert got.add_nodes == got.add_edges == got.remove_edges == got.remove_nodes == []


DATABASE_PREFIX = f"e5_test__{os.getpid()}__"


@pytest.fixture
def database() -> Iterator[FalkorStore]:
    store = FalkorStore(get_client(get_settings()))
    # Match the existing store-parity tests: concurrent test processes cannot overwrite one another.
    names = [DATABASE_PREFIX + suffix for suffix in ("head", "fix-b", "fix-a", "fix-s", "delta")]
    try:
        yield store
    finally:
        for name in names:
            store.delete(name)


@pytest.mark.falkordb
@pytest.mark.parametrize("scenario", ["intern", "public-bucket"])
def test_falkordb_simulation_matches_memory_and_keeps_the_candidate_graph(
    database: FalkorStore, scenario: str
) -> None:
    if scenario == "intern":
        deps, prepared, reqs = intern()
        who = ["user:priya-intern"]
        candidates = [
            fix_b(),
            draft("A", [op("remove_membership", user="priya-intern", group="support-engineers")]),
        ]
    else:
        deps = deps_for(scenario)
        prepared, _ = prepare_state(world(scenario, "head"), "head", deps)
        reqs = [
            *config_requirements(prepared.world),
            Requirement(
                id="I1",
                principal="entry:internet",
                access="read",
                resource="s3://demo-company-files/public/",
                source="intent",
            ),
        ]
        who = ["entry:internet"]
        candidates = [
            draft(
                "A",
                [
                    op(
                        "remove_statement",
                        policy_address="aws_s3_bucket_policy.company_files_public",
                        sid="PublicRead",
                    )
                ],
            ),
            draft(
                "S",
                [
                    op(
                        "set_statement_resources",
                        policy_address="aws_s3_bucket_policy.company_files_public",
                        sid="PublicRead",
                        resources=["arn:aws:s3:::demo-company-files/public/*"],
                    )
                ],
            ),
        ]
    head = prepared.model_copy(update={"name": DATABASE_PREFIX + "head"})
    load_graph(database, head)
    load_graph(deps.store, head)
    for candidate in candidates:
        actual = simulate(database, head, candidate, who, reqs, deps.adapters)
        assert actual == simulate(deps.store, head, candidate, who, reqs, deps.adapters)
        assert any(
            name.startswith(DATABASE_PREFIX) and name.endswith("fix-" + candidate.id.lower())
            for name in database.list_graphs()
        )
    assert analyze(database, head, reqs, who) == analyze(deps.store, head, reqs, who)


@pytest.mark.falkordb
def test_falkordb_node_replacement_restores_unchanged_incident_edges(database: FalkorStore) -> None:
    old = small_rows()
    new = old.model_copy(deep=True)
    new.nodes[1].sensitive = False
    new.nodes[1].labels.remove("Database")
    database.load(DATABASE_PREFIX + "delta", old)
    apply_delta(database, DATABASE_PREFIX + "delta", delta(old, new))
    assert database.paths(DATABASE_PREFIX + "delta", "user:u") == [["e1"]]
    result = (
        database.db.select_graph(DATABASE_PREFIX + "delta")
        .query("MATCH (n:Node {id: 'data:d'}) RETURN labels(n), n.sensitive")
        .result_set
    )
    assert set(result[0][0]) == {"Node", "Resource"} and result[0][1] is False


def test_a_fix_cannot_introduce_exposure_for_an_unrelated_actor() -> None:
    deps, head, reqs = intern()
    load_graph(deps.store, head)
    bad = fix_b().model_copy(
        update={
            "ops": [
                *fix_b().ops,
                op(
                    "add_policy",
                    principal="user:alex-analyst",
                    statements=[
                        {
                            "sid": "AccidentalSecret",
                            "effect": "Allow",
                            "actions": ["secretsmanager:GetSecretValue"],
                            "resources": ["*"],
                        }
                    ],
                ),
            ]
        }
    )
    got = simulate(deps.store, head, bad, ["user:priya-intern"], reqs, deps.adapters)
    assert got.verdict == "fail" and got.new_paths
    assert got.paths_left == []


def test_required_unknown_access_prevents_a_pass_even_without_dangerous_paths() -> None:
    deps, head, reqs = intern()
    load_graph(deps.store, head)
    uncertain = fix_b().model_copy(
        update={
            "ops": [
                *fix_b().ops,
                op(
                    "add_policy",
                    principal="role:intern-onboarding",
                    statements=[
                        {
                            "sid": "UncertainLogs",
                            "effect": "Deny",
                            "actions": ["s3:GetObject"],
                            "resources": ["*"],
                            "condition": {
                                "op": "StringNotEquals",
                                "key": "aws:PrincipalArn",
                                "value": "some-principal",
                            },
                        }
                    ],
                ),
            ]
        }
    )
    got = simulate(deps.store, head, uncertain, ["user:priya-intern"], reqs, deps.adapters)
    assert got.verdict == "unknown" and any("I1" in reason for reason in got.unknown)
    assert got.paths_left == got.requirements_broken == []


def maybe_deny_read(sid: str, arn: str) -> PatchOp:
    return op(
        "add_policy",
        principal="role:prod-support",
        statements=[
            {
                "sid": sid,
                "effect": "Deny",
                "actions": ["s3:GetObject"],
                "resources": [arn],
                "condition": {"op": "StringNotEquals", "key": "aws:SourceVpc", "value": "vpc-1"},
            }
        ],
    )


@pytest.mark.parametrize("touch_r2,verdict", [(False, "pass"), (True, "unknown")])
def test_only_a_requirement_that_becomes_unknown_makes_a_candidate_unknown(
    touch_r2: bool, verdict: str
) -> None:
    deps, initial, reqs = intern()
    changed_world = initial.world.model_copy(deep=True)
    changed_world.resources = deps.adapters.cloud.apply_ops(
        initial.world.resources, [maybe_deny_read("MaybeNoLogs", "arn:aws:s3:::demo-app-logs/*")]
    )
    head, _ = prepare_state(changed_world, "head", deps)
    load_graph(deps.store, head)
    who = ["user:priya-intern"]
    before = {req.id: req.status for req in analyze(deps.store, head, reqs, who).requirements}
    assert before["R1"] == "unknown" and before["R2"] == "satisfied"
    extra = [maybe_deny_read("MaybeNoInvoices", "arn:aws:s3:::demo-company-files/invoices/*")]
    candidate = fix_b().model_copy(update={"ops": [*fix_b().ops, *(extra if touch_r2 else [])]})
    got = simulate(deps.store, head, candidate, who, reqs, deps.adapters)
    assert got.verdict == verdict
    assert got.unknown == (["requirement R2: access is unknown"] if touch_r2 else [])
    assert got.paths_left == got.requirements_broken == []


def test_existing_classification_provenance_is_preserved_without_models() -> None:
    deps, head, reqs = intern()
    for node in head.rows.nodes:
        if node.id == "db:customer-db":
            node.sensitivity_source = "fallback"
    store = ObservedStore()
    load_graph(store, head)
    simulate(store, head, fix_b(), ["user:priya-intern"], reqs, deps.adapters)
    patched = store._rows(store.copies[-1][1])
    for original in head.rows.nodes:
        if "Resource" in original.labels:
            found = next(node for node in patched.nodes if node.id == original.id)
            assert (found.sensitivity, found.sensitive, found.sensitivity_source) == (
                original.sensitivity,
                original.sensitive,
                original.sensitivity_source,
            )


def test_delta_additions_and_duplicate_keys() -> None:
    from theseus.errors import GraphError

    old = small_rows()
    new = old.model_copy(deep=True)
    new.nodes.append(NodeRow(id="user:v", name="v", labels=["Node", "Principal", "User"]))
    new.edges.append(old.edges[0].model_copy(update={"src": "user:v", "eid": "e2"}))
    changes = delta(old, new)
    assert [n.id for n in changes.add_nodes] == ["user:v"]
    assert [e.eid for e in changes.add_edges] == ["e2"]
    assert changes.remove_nodes == changes.remove_edges == []
    with pytest.raises(GraphError):
        delta(old, old.model_copy(update={"nodes": [*old.nodes, old.nodes[0]]}))
    with pytest.raises(GraphError):
        delta(old.model_copy(update={"edges": [*old.edges, old.edges[0]]}), new)


def test_intern_cutting_the_support_assumption_fails_on_i1() -> None:
    deps, head, reqs = intern()
    load_graph(deps.store, head)
    got = simulate(
        deps.store,
        head,
        draft(
            "D",
            [
                op(
                    "remove_statement",
                    policy_address="aws_iam_group_policy.support_assume",
                    sid="AssumeProdSupport",
                )
            ],
        ),
        ["user:priya-intern"],
        reqs,
        deps.adapters,
    )
    assert got.verdict == expected("intern")["candidates"]["D"] == "fail"
    assert got.requirements_broken == ["I1", "R1", "R2", "R3"]


def test_containment_subject_restriction_keeps_required_workflows() -> None:
    deps = deps_for("compromised-action")
    head, _ = prepare_state(world("compromised-action", "base"), "head", deps)
    reqs = config_requirements(head.world)
    load_graph(deps.store, head)
    workflows = ["workflow:demo-org/docs-site/preview.yml"]
    before = analyze(deps.store, head, reqs, workflows)
    assert before.dangerous
    got = simulate(
        deps.store,
        head,
        draft(
            "K",
            [
                op(
                    "set_oidc_sub",
                    role="github-deploy",
                    patterns=[
                        "repo:demo-org/infra:ref:refs/heads/main",
                        "repo:demo-org/infra:environment:production",
                    ],
                )
            ],
        ),
        workflows,
        reqs,
        deps.adapters,
    )
    assert got.verdict == expected("compromised-action")["candidates"]["K"] == "pass"
    assert got.requirements_broken == got.paths_left == []


@pytest.mark.parametrize(
    "identifier,operation",
    [
        (
            "A",
            op(
                "remove_statement",
                policy_address="aws_s3_bucket_policy.company_files_public",
                sid="PublicRead",
            ),
        ),
        (
            "S",
            op(
                "set_statement_resources",
                policy_address="aws_s3_bucket_policy.company_files_public",
                sid="PublicRead",
                resources=["arn:aws:s3:::demo-company-files/public/*"],
            ),
        ),
    ],
)
def test_public_bucket_operations_preserve_only_the_required_public_access(
    identifier: str, operation: PatchOp
) -> None:
    deps = deps_for("public-bucket")
    head, _ = prepare_state(world("public-bucket", "head"), "head", deps)
    reqs = [
        *config_requirements(head.world),
        Requirement(
            id="I1",
            principal="entry:internet",
            access="read",
            resource="s3://demo-company-files/public/",
            source="intent",
        ),
    ]
    load_graph(deps.store, head)
    got = simulate(deps.store, head, draft(identifier, [operation]), ["entry:internet"], reqs, deps.adapters)
    assert got.verdict == expected("public-bucket")["candidates"][identifier]
    assert got.paths_left == got.new_paths == []
    assert got.requirements_broken == (["I1"] if identifier == "A" else [])


def test_a_fix_cannot_turn_an_unrelated_actors_unknown_exposure_into_certain_access() -> None:
    deps, initial, reqs = intern()
    maybe = op(
        "add_policy",
        principal="user:alex-analyst",
        statements=[
            {
                "sid": "MaybeReadSecret",
                "effect": "Allow",
                "actions": ["secretsmanager:GetSecretValue"],
                "resources": ["*"],
                "condition": {"op": "StringNotEquals", "key": "aws:PrincipalArn", "value": "other"},
            }
        ],
    )
    changed_world = initial.world.model_copy(deep=True)
    changed_world.resources = deps.adapters.cloud.apply_ops(initial.world.resources, [maybe])
    head, _ = prepare_state(changed_world, "head", deps)
    load_graph(deps.store, head)
    before = analyze(deps.store, head, reqs, ["user:alex-analyst"])
    assert any(path.target == "db:customer-db" and path.unknown for path in before.dangerous)
    added = next(
        r for r in changed_world.resources if r.address not in {r.address for r in initial.world.resources}
    )
    candidate = fix_b().model_copy(
        update={
            "ops": [
                *fix_b().ops,
                op("remove_statement", policy_address=added.address, sid="MaybeReadSecret"),
                op(
                    "add_policy",
                    principal="user:alex-analyst",
                    statements=[
                        {
                            "sid": "CertainReadSecret",
                            "effect": "Allow",
                            "actions": ["secretsmanager:GetSecretValue"],
                            "resources": ["*"],
                        }
                    ],
                ),
            ]
        }
    )
    result = simulate(deps.store, head, candidate, ["user:priya-intern"], reqs, deps.adapters)
    assert result.verdict == "fail"
    assert result.new_paths


def invalid_role_name_candidate(name: str) -> CandidateDraft:
    candidate = fix_b().model_copy(deep=True)
    candidate.ops[1].args["name"] = name
    candidate.ops[2].args["statements"][0]["resources"] = [f"arn:aws:iam::111122223333:role/{name}"]
    return candidate


@pytest.mark.parametrize("name", ["r" * 65, "PROD-SUPPORT"])
def test_invalid_role_name_is_an_invalid_candidate_without_head_mutation(name: str) -> None:
    deps, head, reqs = intern()
    load_graph(deps.store, head)
    snapshot = head.model_dump_json()
    who = ["user:priya-intern"]
    before = analyze(deps.store, head, reqs, who)
    result = simulate(deps.store, head, invalid_role_name_candidate(name), who, reqs, deps.adapters)
    assert result.verdict == "invalid" and result.reason
    assert head.model_dump_json() == snapshot
    assert analyze(deps.store, head, reqs, who) == before


@pytest.mark.falkordb
@pytest.mark.parametrize("name", ["r" * 65, "PROD-SUPPORT"])
def test_falkordb_rejects_invalid_role_names_without_head_mutation(database: FalkorStore, name: str) -> None:
    deps, prepared, reqs = intern()
    head = prepared.model_copy(update={"name": DATABASE_PREFIX + "head"})
    load_graph(database, head)
    who = ["user:priya-intern"]
    before = analyze(database, head, reqs, who)
    result = simulate(database, head, invalid_role_name_candidate(name), who, reqs, deps.adapters)
    assert result.verdict == "invalid" and result.reason
    assert DATABASE_PREFIX + "fix-b" in database.list_graphs()
    assert analyze(database, head, reqs, who) == before
