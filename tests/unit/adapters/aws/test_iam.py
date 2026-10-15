"""The IAM subset, one case per rule in docs/spec/04-engine.md section 5."""

from __future__ import annotations

import json

import pytest

from theseus.adapters.aws.iam import (
    ACTION_GRANTS,
    ASSUME,
    PolicyStatement,
    evaluate,
    glob_match,
    statements,
    trust_kind,
)
from theseus.errors import IngestError

ACCOUNT = "111122223333"
INVOICES = "arn:aws:s3:::demo-company-files/invoices/x"
SECRET = f"arn:aws:secretsmanager:eu-west-1:{ACCOUNT}:secret:prod-db-credentials-AbCdEf"
TABLE = f"arn:aws:dynamodb:eu-west-1:{ACCOUNT}:table/demo-orders"
ROLE = f"arn:aws:iam::{ACCOUNT}:role/prod-support"
SAM = f"arn:aws:iam::{ACCOUNT}:user/sam-support"


def stmt(
    effect: str = "Allow", action: object = "s3:GetObject", resource: object = "*", **extra: object
) -> dict:
    s: dict[str, object] = {"Effect": effect}
    if action is not None:
        s["Action"] = action
    if resource is not None:
        s["Resource"] = resource
    s.update(extra)
    return s


def policy(*stmts: dict) -> list[PolicyStatement]:
    return statements(json.dumps({"Version": "2012-10-17", "Statement": list(stmts)}))


# Matching ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "value", "matches"),
    [
        ("*", "arn:aws:s3:::any/key/with:colons", True),
        ("arn:aws:s3:::demo-company-files/*", INVOICES, True),
        ("arn:aws:s3:::demo-company-files/invoices/*", "arn:aws:s3:::demo-company-files/public/x", False),
        ("arn:aws:secretsmanager:*:*:secret:prod-db-credentials-*", SECRET, True),
        ("arn:aws:s3:::demo-company-files/invoice?/x", INVOICES, True),
        ("arn:aws:s3:::demo-company-files/invoice?/x", "arn:aws:s3:::demo-company-files/invoices1/x", False),
        ("arn:aws:s3:::demo-app-logs", "arn:aws:s3:::demo-app-logs/x", False),
    ],
)
def test_glob_match(pattern: str, value: str, matches: bool) -> None:
    assert glob_match(pattern, value) is matches


def test_actions_match_without_case_but_resources_with_it() -> None:
    allow = policy(stmt(action="S3:getobject", resource="arn:aws:s3:::demo-company-files/invoices/*"))
    assert evaluate(allow, "s3:GetObject", INVOICES).result == "allow"
    upper = policy(stmt(resource="arn:aws:s3:::demo-company-files/Invoices/*"))
    assert evaluate(upper, "s3:GetObject", INVOICES).result == "none"


# Evaluation -------------------------------------------------------------------------------------------------


def test_nothing_matches_is_none() -> None:
    assert evaluate(policy(stmt(resource="arn:aws:s3:::other/*")), "s3:GetObject", INVOICES).result == "none"


def test_an_unconditional_allow_allows_and_names_its_statement() -> None:
    allow = stmt(Sid="ReadInvoices", resource="arn:aws:s3:::demo-company-files/invoices/*")
    decision = evaluate(policy(allow), "s3:GetObject", INVOICES)
    assert decision.result == "allow"
    assert [s.sid for s in decision.statements] == ["ReadInvoices"]


def test_an_unconditional_deny_wins_over_any_allow() -> None:
    stmts = policy(
        stmt(Sid="All"), stmt(effect="Deny", Sid="NoInvoices", resource="arn:aws:s3:::demo-company-files/*")
    )
    decision = evaluate(stmts, "s3:GetObject", INVOICES)
    assert decision.result == "deny"
    assert [s.sid for s in decision.statements] == ["NoInvoices"]


def test_a_deny_on_something_else_leaves_the_allow() -> None:
    stmts = policy(stmt(), stmt(effect="Deny", resource="arn:aws:s3:::demo-app-logs/*"))
    assert evaluate(stmts, "s3:GetObject", INVOICES).result == "allow"


def test_a_conditional_allow_alone_is_unknown() -> None:
    cond = {"Bool": {"aws:MultiFactorAuthPresent": "true"}}
    assert evaluate(policy(stmt(Condition=cond)), "s3:GetObject", INVOICES).result == "unknown"


def test_a_conditional_deny_turns_an_allow_into_unknown() -> None:
    cond = {"StringEquals": {"aws:PrincipalTag/team": "billing"}}
    stmts = policy(stmt(Sid="Read"), stmt(effect="Deny", Sid="MaybeNot", Condition=cond))
    decision = evaluate(stmts, "s3:GetObject", INVOICES)
    assert decision.result == "unknown"
    assert {s.sid for s in decision.statements} == {"Read", "MaybeNot"}


def test_a_conditional_allow_never_weakens_a_definite_allow() -> None:
    cond = {"Bool": {"aws:SecureTransport": "true"}}
    stmts = policy(stmt(Sid="Read"), stmt(Sid="AlsoRead", Condition=cond))
    assert evaluate(stmts, "s3:GetObject", INVOICES).result == "allow"


def test_an_unconditional_deny_beats_a_conditional_allow() -> None:
    stmts = policy(stmt(Condition={"Bool": {"x": "y"}}), stmt(effect="Deny"))
    assert evaluate(stmts, "s3:GetObject", INVOICES).result == "deny"


@pytest.mark.parametrize("key", ["NotAction", "NotResource"])
def test_not_action_and_not_resource_are_unknown(key: str) -> None:
    other = "iam:*" if key == "NotAction" else "arn:aws:s3:::elsewhere/*"
    s = stmt(
        action=None if key == "NotAction" else "s3:GetObject", resource=None if key == "NotResource" else "*"
    )
    s[key] = other
    assert evaluate(policy(s), "s3:GetObject", INVOICES).result == "unknown"


def test_an_unsupported_deny_turns_an_allow_into_unknown() -> None:
    stmts = policy(stmt(Sid="Read"), {"Effect": "Deny", "NotAction": "s3:PutObject", "Resource": "*"})
    assert evaluate(stmts, "s3:GetObject", INVOICES).result == "unknown"


def test_a_statement_list_or_a_single_statement_both_parse() -> None:
    one = statements(json.dumps({"Statement": stmt(action=["s3:GetObject", "s3:PutObject"])}))
    assert one[0].actions == ["s3:GetObject", "s3:PutObject"]
    assert statements({"Statement": [stmt(), stmt(effect="Deny")]})[1].effect == "Deny"


def test_an_unreadable_policy_is_an_ingest_error() -> None:
    with pytest.raises(IngestError):
        statements("{not json")


# Modeled actions ------------------------------------------------------------------------------------------


def test_modeled_actions_and_the_access_they_grant() -> None:
    assert ACTION_GRANTS["s3"] == {
        "s3:GetObject": "read",
        "s3:PutObject": "write",
        "s3:DeleteObject": "write",
    }
    assert ACTION_GRANTS["secret"] == {"secretsmanager:GetSecretValue": "read"}
    reads = {a for a, g in ACTION_GRANTS["dynamodb"].items() if g == "read"}
    writes = {a for a, g in ACTION_GRANTS["dynamodb"].items() if g == "write"}
    assert reads == {"dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:Scan"}
    assert writes == {
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:BatchWriteItem",
    }
    assert ASSUME == "sts:AssumeRole"
    assert "db" not in ACTION_GRANTS


@pytest.mark.parametrize(
    "action", ["dynamodb:Describe*", "dynamodb:CreateTable", "iam:*", "s3:ListBucket", "s3:PutBucket*"]
)
def test_control_plane_actions_grant_nothing_modeled(action: str) -> None:
    stmts = policy(stmt(action=action))
    for kind, arn in (("s3", INVOICES), ("secret", SECRET), ("dynamodb", TABLE)):
        for modeled in ACTION_GRANTS[kind]:
            assert evaluate(stmts, modeled, arn).result == "none", (action, modeled)


def test_a_table_index_does_not_reach_the_table() -> None:
    stmts = policy(stmt(action="dynamodb:Query", resource=f"{TABLE}/index/*"))
    assert evaluate(stmts, "dynamodb:Query", TABLE).result == "none"


# Trust -----------------------------------------------------------------------------------------------------


def trust(*stmts: dict) -> list[PolicyStatement]:
    return policy(*stmts)


def assume(principal: object, **extra: object) -> dict:
    return {"Effect": "Allow", "Action": "sts:AssumeRole", "Principal": principal, **extra}


@pytest.mark.parametrize(
    ("principal", "caller", "kind"),
    [
        ({"AWS": SAM}, SAM, "explicit"),
        ({"AWS": [f"arn:aws:iam::{ACCOUNT}:root"]}, SAM, "account"),
        ({"AWS": ACCOUNT}, SAM, "account"),
        ("*", SAM, "account"),
        ({"AWS": "*"}, SAM, "account"),
        ({"AWS": "arn:aws:iam::999988887777:root"}, SAM, None),
        ({"AWS": SAM}, f"arn:aws:iam::{ACCOUNT}:user/priya-intern", None),
        ({"Service": "lambda.amazonaws.com"}, SAM, None),
        ({"AWS": f"arn:aws:iam::{ACCOUNT}:root"}, None, "account"),
        ({"AWS": SAM}, None, None),
    ],
)
def test_trust_kind(principal: object, caller: str | None, kind: str | None) -> None:
    assert trust_kind(trust(assume(principal)), caller, ACCOUNT).kind == kind


def test_conditional_trust_is_unknown() -> None:
    cond = {"Bool": {"aws:MultiFactorAuthPresent": "true"}}
    assert trust_kind(trust(assume({"AWS": SAM}, Condition=cond)), SAM, ACCOUNT).kind == "unknown"


def test_not_principal_trust_is_unknown() -> None:
    s = {
        "Effect": "Allow",
        "Action": "sts:AssumeRole",
        "NotPrincipal": {"AWS": "arn:aws:iam::999988887777:root"},
    }
    assert trust_kind(trust(s), SAM, ACCOUNT).kind == "unknown"


def test_explicit_trust_beats_account_trust_and_names_its_statement() -> None:
    stmts = trust(
        assume({"AWS": f"arn:aws:iam::{ACCOUNT}:root"}, Sid="TrustAccount"),
        assume({"AWS": SAM}, Sid="TrustSam"),
    )
    decision = trust_kind(stmts, SAM, ACCOUNT)
    assert decision.kind == "explicit"
    assert [s.sid for s in decision.statements] == ["TrustSam"]


def test_a_trust_deny_for_the_caller_removes_the_trust() -> None:
    stmts = trust(
        assume({"AWS": ACCOUNT}), {"Effect": "Deny", "Action": "sts:AssumeRole", "Principal": {"AWS": SAM}}
    )
    assert trust_kind(stmts, SAM, ACCOUNT).kind is None


def test_web_identity_trust_is_left_to_oidc_matching() -> None:
    oidc = {
        "Effect": "Allow",
        "Action": "sts:AssumeRoleWithWebIdentity",
        "Principal": {
            "Federated": f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"
        },
    }
    assert trust_kind(trust(oidc), SAM, ACCOUNT).kind is None


def test_an_unknown_trust_policy_is_unknown_for_every_caller() -> None:
    assert trust_kind(statements(None), SAM, ACCOUNT).kind == "unknown"
    assert evaluate(statements(None), "s3:GetObject", INVOICES).result == "unknown"
