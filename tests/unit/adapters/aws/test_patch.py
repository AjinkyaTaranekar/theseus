"""Patch operations on real demo resources, including rejection and copy isolation (E5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.golden.conftest import adapters_for, world
from theseus.adapters.aws.patch import apply_ops
from theseus.contracts.adapters import IacResource
from theseus.contracts.result import PatchOp
from theseus.errors import PatchError

ACCOUNT = "111122223333"
SUB = "token.actions.githubusercontent.com:sub"


@pytest.mark.parametrize("length", [1, 63, 64, 65, 80, 128, 129])
def test_new_role_enforces_aws_name_length(resources: list[IacResource], length: int) -> None:
    operation = op(
        "add_role", name="r" * length, trust_principals=["user:priya-intern"], statements=[statement()]
    )
    before = [r.model_dump() for r in resources]
    if length <= 64:
        assert apply_ops(resources, [operation], account=ACCOUNT)
    else:
        with pytest.raises(PatchError):
            apply_ops(resources, [operation], account=ACCOUNT)
    assert [r.model_dump() for r in resources] == before


@pytest.mark.parametrize("new_in_sequence", [False, True])
def test_new_role_rejects_case_insensitive_collision(
    resources: list[IacResource], new_in_sequence: bool
) -> None:
    operations = []
    name = "prod-support"
    if new_in_sequence:
        name = "review-role"
        operations.append(
            op("add_role", name=name, trust_principals=["user:priya-intern"], statements=[statement()])
        )
    operations.append(
        op("add_role", name=name.upper(), trust_principals=["user:priya-intern"], statements=[statement()])
    )
    before = [r.model_dump() for r in resources]
    with pytest.raises(PatchError):
        apply_ops(resources, operations, account=ACCOUNT)
    assert [r.model_dump() for r in resources] == before


def op(operation: str, **args: object) -> PatchOp:
    return PatchOp(provider="aws", op=operation, args=args)


def statement(sid: str = "ReadLogs") -> dict:
    return {
        "sid": sid,
        "effect": "Allow",
        "actions": ["s3:GetObject"],
        "resources": ["arn:aws:s3:::demo-app-logs/*"],
    }


def resource(address: str, **values: object) -> IacResource:
    kind, name = address.split(".")
    return IacResource(address=address, type=kind, name=name, provider="aws", values=values)


def find(resources: list[IacResource], address: str) -> IacResource:
    return next(r for r in resources if r.address == address)


@pytest.fixture
def resources() -> list[IacResource]:
    return world("intern", "head").resources


def test_remove_membership_drops_only_empty_matching_resources(resources: list[IacResource]) -> None:
    mixed = resource(
        "aws_iam_user_group_membership.mixed",
        user="priya-intern",
        groups=["support-engineers", "data-analysts"],
    )
    before = [r.model_dump() for r in resources]
    got = apply_ops(
        [*resources, mixed], [op("remove_membership", user="priya-intern", group="support-engineers")]
    )
    assert "aws_iam_user_group_membership.priya_support" not in {r.address for r in got}
    assert find(got, mixed.address).values["groups"] == ["data-analysts"]
    assert find(got, "aws_iam_user_group_membership.sam_support").values["groups"] == ["support-engineers"]
    assert [r.model_dump() for r in resources] == before
    assert mixed.values["groups"] == ["support-engineers", "data-analysts"]


def test_add_membership_is_deterministic_sorted_and_independent(resources: list[IacResource]) -> None:
    operations = [op("add_membership", user="priya-intern", group="data-analysts")]
    a = apply_ops(resources, operations)
    b = apply_ops(list(reversed(resources)), operations)
    assert a == b and [r.address for r in a] == sorted(r.address for r in a)
    added = [r for r in a if r.address not in {r.address for r in resources}]
    assert len(added) == 1
    assert added[0].type == "aws_iam_user_group_membership"
    assert added[0].values == {"user": "priya-intern", "groups": ["data-analysts"]}
    find(a, "aws_iam_user.priya").values["name"] = "different"
    assert find(resources, "aws_iam_user.priya").values["name"] == "priya-intern"


@pytest.mark.parametrize(
    "kind",
    [
        "aws_iam_user_policy",
        "aws_iam_group_policy",
        "aws_iam_role_policy",
        "aws_iam_policy",
        "aws_s3_bucket_policy",
    ],
)
@pytest.mark.parametrize("encoded", [False, True])
def test_policy_edits_support_inline_and_shared_json_or_objects(kind: str, encoded: bool) -> None:
    document = {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "Keep", "Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"},
            {
                "Sid": "Edit",
                "Effect": "Allow",
                "Action": "s3:PutObject",
                "Resource": "*",
                "Condition": {"StringEquals": {"x": "y"}},
            },
        ],
    }
    source = resource(f"{kind}.p", policy=json.dumps(document) if encoded else document)
    edited = apply_ops(
        [source],
        [
            op(
                "set_statement_resources",
                policy_address=source.address,
                sid="Edit",
                resources=["arn:aws:s3:::logs/*"],
            )
        ],
    )
    raw = edited[0].values["policy"]
    got = json.loads(raw) if isinstance(raw, str) else raw
    assert got["Statement"][1] == {**document["Statement"][1], "Resource": ["arn:aws:s3:::logs/*"]}
    removed = apply_ops(edited, [op("remove_statement", policy_address=source.address, sid="Edit")])
    raw = removed[0].values["policy"]
    got = json.loads(raw) if isinstance(raw, str) else raw
    assert got == {**document, "Statement": [document["Statement"][0]]}
    assert source.values["policy"] == (json.dumps(document) if encoded else document)


def test_single_statement_object_can_be_removed() -> None:
    source = resource(
        "aws_iam_policy.p",
        policy={"Statement": {"Sid": "Only", "Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}},
    )
    got = apply_ops([source], [op("remove_statement", policy_address=source.address, sid="Only")])
    assert got[0].values["policy"]["Statement"] == []


@pytest.mark.parametrize("principal", ["user:priya-intern", "group:support-engineers", "role:prod-support"])
def test_add_policy_uses_the_principal_kind_and_serializes_conditions(
    resources: list[IacResource], principal: str
) -> None:
    condition = {"op": "StringEquals", "key": "aws:PrincipalTag/team", "value": ["support"]}
    got = apply_ops(
        resources,
        [op("add_policy", principal=principal, statements=[{**statement(), "condition": condition}])],
    )
    new = next(r for r in got if r.address not in {r.address for r in resources})
    kind, name = principal.split(":")
    assert new.type == f"aws_iam_{kind}_policy" and new.values[kind] == name
    doc = json.loads(new.values["policy"])
    assert doc["Statement"] == [
        {
            "Sid": "ReadLogs",
            "Effect": "Allow",
            "Action": ["s3:GetObject"],
            "Resource": ["arn:aws:s3:::demo-app-logs/*"],
            "Condition": {"StringEquals": {"aws:PrincipalTag/team": ["support"]}},
        }
    ]


def test_add_role_trusts_exact_declared_principals_and_works_through_adapter(
    resources: list[IacResource],
) -> None:
    w = world("intern", "head")
    adapter = adapters_for(Path(w.root)).cloud
    operations = [
        op(
            "add_role",
            name="intern-onboarding",
            trust_principals=["user:priya-intern", "role:prod-support"],
            statements=[statement()],
        )
    ]
    got = adapter.apply_ops(resources, operations)
    added = [r for r in got if r.address not in {r.address for r in resources}]
    assert len(added) == 2
    role = next(r for r in added if r.type == "aws_iam_role")
    policy = next(r for r in added if r.type == "aws_iam_role_policy")
    assert role.values["name"] == policy.values["role"] == "intern-onboarding"
    trust = json.loads(role.values["assume_role_policy"])["Statement"][0]
    assert trust["Principal"]["AWS"] == [
        f"arn:aws:iam::{ACCOUNT}:role/prod-support",
        f"arn:aws:iam::{ACCOUNT}:user/priya-intern",
    ]
    assert trust["Action"] == "sts:AssumeRole"
    assert policy.values["policy"]


def test_operations_can_use_a_principal_created_earlier(resources: list[IacResource]) -> None:
    got = apply_ops(
        resources,
        [
            op(
                "add_role",
                name="intern-onboarding",
                trust_principals=["user:priya-intern"],
                statements=[statement()],
            ),
            op("add_policy", principal="role:intern-onboarding", statements=[statement("More")]),
        ],
        account=ACCOUNT,
    )
    assert (
        sum(r.type == "aws_iam_role_policy" and r.values.get("role") == "intern-onboarding" for r in got) == 2
    )


def test_oidc_sub_changes_all_matching_trusts_and_preserves_audience(resources: list[IacResource]) -> None:
    role = find(resources, "aws_iam_role.github_deploy")
    doc = json.loads(role.values["assume_role_policy"])
    doc["Statement"].append(
        {"Effect": "Allow", "Action": "sts:AssumeRole", "Principal": {"Service": "lambda.amazonaws.com"}}
    )
    doc["Statement"][0]["Condition"]["StringEquals"][SUB] = "old-exact-sub"
    role.values["assume_role_policy"] = json.dumps(doc)
    patterns = ["repo:demo-org/infra:environment:production"]
    got = apply_ops(resources, [op("set_oidc_sub", role="github-deploy", patterns=patterns)])
    trust = json.loads(find(got, role.address).values["assume_role_policy"])
    assert trust["Statement"][0]["Condition"] == {
        "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
        "StringLike": {SUB: patterns},
    }
    assert trust["Statement"][1] == doc["Statement"][1]


@pytest.mark.parametrize(
    "operation",
    [
        PatchOp(
            provider="other", op="add_membership", args={"user": "priya-intern", "group": "data-analysts"}
        ),
        op("not_an_op"),
        op("remove_membership", user="priya-intern"),
        op("remove_membership", user="nobody", group="support-engineers"),
        op("remove_membership", user="priya-intern", group="missing"),
        op("remove_membership", user="priya-intern", group="data-analysts"),
        op("add_membership", user="priya-intern", group="support-engineers"),
        op("add_membership", user="missing", group="data-analysts"),
        op("add_membership", user="priya-intern", group="missing"),
        op("remove_statement", policy_address="aws_iam_policy.missing", sid="X"),
        op("remove_statement", policy_address="aws_iam_user.priya", sid="X"),
        op("remove_statement", policy_address="aws_iam_policy.orders_table_rw", sid="Missing"),
        op(
            "set_statement_resources",
            policy_address="aws_iam_policy.orders_table_rw",
            sid="OrdersTableReadWrite",
            resources=[],
        ),
        op("add_policy", principal="workload:orders-api", statements=[statement()]),
        op("add_policy", principal="user:missing", statements=[statement()]),
        op("add_policy", principal="user:priya-intern", statements=[]),
        op("add_policy", principal="user:priya-intern", statements=[statement(), statement()]),
        op("add_role", name="prod-support", trust_principals=["user:priya-intern"], statements=[statement()]),
        op("add_role", name="new", trust_principals=[], statements=[statement()]),
        op("add_role", name="new", trust_principals=["group:support-engineers"], statements=[statement()]),
        op("add_role", name="new", trust_principals=["user:missing"], statements=[statement()]),
        op("set_oidc_sub", role="missing", patterns=["repo:demo-org/*"]),
        op("set_oidc_sub", role="prod-support", patterns=["repo:demo-org/*"]),
        op("set_oidc_sub", role="github-deploy", patterns=[]),
    ],
)
def test_invalid_operations_raise_patch_error_without_mutation(
    resources: list[IacResource], operation: PatchOp
) -> None:
    before = [r.model_dump() for r in resources]
    with pytest.raises(PatchError):
        apply_ops(resources, [operation], account=ACCOUNT)
    assert [r.model_dump() for r in resources] == before


@pytest.mark.parametrize(
    "policy", [None, "{bad json", [], {"Statement": "bad"}, {"Statement": [{"Sid": "Same"}, {"Sid": "Same"}]}]
)
def test_unreadable_or_ambiguous_policy_is_rejected(policy: object) -> None:
    source = resource("aws_iam_policy.p", policy=policy)
    with pytest.raises(PatchError):
        apply_ops([source], [op("remove_statement", policy_address=source.address, sid="Same")])


def test_later_invalid_op_never_leaks_an_earlier_change(resources: list[IacResource]) -> None:
    before = [r.model_dump() for r in resources]
    with pytest.raises(PatchError):
        apply_ops(
            resources,
            [
                op("remove_membership", user="priya-intern", group="support-engineers"),
                op("remove_statement", policy_address="missing", sid="x"),
            ],
        )
    assert [r.model_dump() for r in resources] == before


def test_duplicate_addresses_and_generated_address_collisions_are_rejected(
    resources: list[IacResource],
) -> None:
    with pytest.raises(PatchError):
        apply_ops([*resources, resources[0]], [])
    operation = op("add_policy", principal="user:priya-intern", statements=[statement()])
    with pytest.raises(PatchError):
        apply_ops(resources, [operation, operation])


def test_malformed_oidc_condition_keys_are_patch_errors(resources: list[IacResource]) -> None:
    role = find(resources, "aws_iam_role.github_deploy")
    doc = json.loads(role.values["assume_role_policy"])
    doc["Statement"][0]["Condition"] = {"StringLike": {123: "invalid"}}
    role.values["assume_role_policy"] = doc
    with pytest.raises(PatchError):
        apply_ops(resources, [op("set_oidc_sub", role="github-deploy", patterns=["repo:demo-org/*"])])


@pytest.mark.parametrize("change", ["missing-account", "path", "arn"])
def test_role_creation_refuses_unknown_or_inconsistent_trust_identity(
    resources: list[IacResource], change: str
) -> None:
    account = ACCOUNT
    principal = find(resources, "aws_iam_user.priya")
    if change == "missing-account":
        account = None
    elif change == "path":
        principal.values["path"] = "/team/"
    else:
        principal.values["arn"] = "arn:aws:iam::999999999999:user/priya-intern"
    with pytest.raises(PatchError):
        apply_ops(
            resources,
            [op("add_role", name="new", trust_principals=["user:priya-intern"], statements=[statement()])],
            account=account,
        )
