"""A principal's statements: inline, attached customer-managed, AWS-managed, and unknown policies."""

from __future__ import annotations

import json

from theseus.adapters.aws.iam import evaluate
from theseus.adapters.aws.managed import AWS_MANAGED, LAMBDA_BASIC
from theseus.adapters.aws.policies import statements_for
from theseus.contracts.adapters import IacResource
from theseus.contracts.result import Evidence

ACCOUNT = "111122223333"
TABLE = f"arn:aws:dynamodb:eu-west-1:{ACCOUNT}:table/demo-orders"
LOGS = "arn:aws:s3:::demo-app-logs/x"


def locate(address: str, part: str | None) -> Evidence:
    return Evidence(address=address, part=part, file="terraform/test.tf", line=len(address))


def res(address: str, **values: object) -> IacResource:
    rtype, name = address.split(".")
    return IacResource(address=address, type=rtype, name=name, provider="aws", values=values)


def doc(*stmts: dict) -> str:
    return json.dumps({"Version": "2012-10-17", "Statement": list(stmts)})


TABLE_RW = doc(
    {
        "Sid": "OrdersTableReadWrite",
        "Effect": "Allow",
        "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"],
        "Resource": [TABLE, f"{TABLE}/index/*"],
    }
)
WORLD = [
    res("aws_iam_policy.orders_table_rw", name="orders-table-rw", policy=TABLE_RW),
    res(
        "aws_iam_role_policy_attachment.orders_api_table",
        role="orders-api-task",
        policy_arn=f"arn:aws:iam::{ACCOUNT}:policy/orders-table-rw",
    ),
    res(
        "aws_iam_role_policy_attachment.orders_worker_table",
        role="orders-worker-task",
        policy_arn=f"arn:aws:iam::{ACCOUNT}:policy/orders-table-rw",
    ),
    res(
        "aws_iam_role_policy.orders_api_inline",
        name="orders-api-inline",
        role="orders-api-task",
        policy=doc({"Sid": "ReadLogs", "Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}),
    ),
    res(
        "aws_iam_group_policy.support_assume",
        name="assume-prod-support",
        group="support-engineers",
        policy=doc(
            {"Sid": "AssumeProdSupport", "Effect": "Allow", "Action": "sts:AssumeRole", "Resource": "*"}
        ),
    ),
    res(
        "aws_iam_role_policy_attachment.billing_job_logs",
        role="billing-job",
        policy_arn=LAMBDA_BASIC,
    ),
    res(
        "aws_iam_role_policy_attachment.mystery",
        role="mystery",
        policy_arn="arn:aws:iam::aws:policy/AdministratorAccess",
    ),
    res("aws_iam_role_policy.not_yet_known", name="not-yet-known", role="pending"),
]


def test_an_inline_policy_belongs_to_its_principal() -> None:
    pairs = statements_for("group", "support-engineers", WORLD, ACCOUNT, locate)
    assert [(s.sid, e.address, e.part, e.note) for s, e in pairs] == [
        ("AssumeProdSupport", "aws_iam_group_policy.support_assume", "AssumeProdSupport", None)
    ]


def test_an_attached_policy_grants_like_an_inline_one() -> None:
    pairs = statements_for("role", "orders-api-task", WORLD, ACCOUNT, locate)
    sids = sorted(s.sid or "" for s, _ in pairs)
    assert sids == ["OrdersTableReadWrite", "ReadLogs"]
    attached = next(e for s, e in pairs if s.sid == "OrdersTableReadWrite")
    assert attached.address == "aws_iam_policy.orders_table_rw"
    assert attached.note == "attached by aws_iam_role_policy_attachment.orders_api_table"
    assert evaluate([s for s, _ in pairs], "dynamodb:PutItem", TABLE).result == "allow"


def test_one_policy_attached_to_two_roles_reaches_from_both() -> None:
    for role in ("orders-api-task", "orders-worker-task"):
        stmts = [s for s, _ in statements_for("role", role, WORLD, ACCOUNT, locate)]
        assert evaluate(stmts, "dynamodb:GetItem", TABLE).result == "allow", role


def test_a_known_aws_managed_policy_expands_to_its_statements() -> None:
    pairs = statements_for("role", "billing-job", WORLD, ACCOUNT, locate)
    assert [s.actions for s, _ in pairs] == [s.actions for s in AWS_MANAGED[LAMBDA_BASIC]]
    _, ev = pairs[0]
    assert ev.address == "aws_iam_role_policy_attachment.billing_job_logs"
    assert ev.note == "AWS-managed AWSLambdaBasicExecutionRole"
    assert evaluate([s for s, _ in pairs], "s3:GetObject", LOGS).result == "none"


def test_an_unknown_managed_policy_is_an_unknown_policy() -> None:
    pairs = statements_for("role", "mystery", WORLD, ACCOUNT, locate)
    assert evaluate([s for s, _ in pairs], "s3:GetObject", LOGS).result == "unknown"
    assert pairs[0][1].note == "unknown policy arn:aws:iam::aws:policy/AdministratorAccess"


def test_a_policy_not_known_until_apply_is_an_unknown_policy() -> None:
    pairs = statements_for("role", "pending", WORLD, ACCOUNT, locate)
    assert evaluate([s for s, _ in pairs], "dynamodb:GetItem", TABLE).result == "unknown"
    assert pairs[0][1].note == "policy unknown until apply"


def test_a_principal_with_no_policies_has_no_statements() -> None:
    assert statements_for("user", "priya-intern", WORLD, ACCOUNT, locate) == []


def test_a_path_in_the_policy_arn_still_resolves() -> None:
    world = [
        res(
            "aws_iam_policy.p",
            name="p",
            path="/team/",
            policy=doc({"Effect": "Allow", "Action": "s3:*", "Resource": "*"}),
        ),
        res(
            "aws_iam_user_policy_attachment.a",
            user="sam-support",
            policy_arn=f"arn:aws:iam::{ACCOUNT}:policy/team/p",
        ),
    ]
    pairs = statements_for("user", "sam-support", world, ACCOUNT, locate)
    assert evaluate([s for s, _ in pairs], "s3:GetObject", LOGS).result == "allow"
