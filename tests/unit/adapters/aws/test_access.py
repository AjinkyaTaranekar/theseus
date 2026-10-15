"""CAN and CAN_ASSUME edges on a small world shaped like docs/spec/02-demo-world.md."""

from __future__ import annotations

import json

import pytest

from theseus.adapters.aws.access import derive_access_edges
from theseus.contracts.adapters import IacResource
from theseus.contracts.result import EdgeRow, Evidence, NodeRow

ACCOUNT = "111122223333"
REGION = "eu-west-1"
CONFIG = {"account": ACCOUNT, "region": REGION}
ROOT = f"arn:aws:iam::{ACCOUNT}:root"


def locate(address: str, part: str | None) -> Evidence:
    return Evidence(address=address, part=part, file="terraform/test.tf", line=1)


def res(address: str, **values: object) -> IacResource:
    rtype, name = address.split(".")
    return IacResource(address=address, type=rtype, name=name, provider="aws", values=values)


def doc(*stmts: dict) -> str:
    return json.dumps({"Version": "2012-10-17", "Statement": list(stmts)})


def allow(sid: str, action: object, resource: object, **extra: object) -> dict:
    return {"Sid": sid, "Effect": "Allow", "Action": action, "Resource": resource, **extra}


def trust_account() -> str:
    return doc(
        {
            "Sid": "TrustAccountPrincipals",
            "Effect": "Allow",
            "Action": "sts:AssumeRole",
            "Principal": {"AWS": ROOT},
        }
    )


def trust_service(service: str) -> str:
    return doc({"Effect": "Allow", "Action": "sts:AssumeRole", "Principal": {"Service": service}})


def principal(kind: str, name: str) -> NodeRow:
    label = {"user": "User", "group": "Group", "role": "Role"}[kind]
    return NodeRow(
        id=f"{kind}:{name}",
        labels=["Node", "Principal", label],
        name=name,
        props={"arn": f"arn:aws:iam::{ACCOUNT}:{kind}/{name}"},
    )


def resource(node: str, category: str, arn: str) -> NodeRow:
    return NodeRow(
        id=node,
        labels=["Node", "Resource"],
        name=node,
        category=category,
        provider="aws",
        props={"arn_pattern": arn},
    )


TABLE = f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/demo-orders"
LOG_GROUP = f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/billing-job"
PARAM = f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter/prod/db-password"
NODES = [
    *(principal("user", u) for u in ("sam-support", "priya-intern", "auditor")),
    *(principal("group", g) for g in ("support-engineers", "data-analysts")),
    *(
        principal("role", r)
        for r in (
            "prod-support",
            "analytics-read",
            "orders-api-task",
            "orders-worker-task",
            "billing-job",
            "audit-read",
            "shadow",
        )
    ),
    NodeRow(id="entry:internet", labels=["Node", "Principal", "Entry"], name="internet"),
    resource("s3://demo-app-logs/", "ObjectStorage", "arn:aws:s3:::demo-app-logs/x"),
    resource(
        "s3://demo-company-files/invoices/", "ObjectStorage", "arn:aws:s3:::demo-company-files/invoices/x"
    ),
    resource("s3://demo-company-files/public/", "ObjectStorage", "arn:aws:s3:::demo-company-files/public/x"),
    resource(
        "secret:prod-db-credentials",
        "Secret",
        f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:prod-db-credentials-AbCdEf",
    ),
    resource("dynamodb:demo-orders", "Database", TABLE),
    resource("db:customer-db", "Database", f"arn:aws:rds:{REGION}:{ACCOUNT}:db:customer-db"),
    resource("ssm-parameter:/prod/db-password", "Secret", PARAM),
    resource("log-group:/aws/lambda/billing-job", "LogStore", LOG_GROUP),
    *(principal("role", r) for r in ("config-reader", "log-shipper", "log-reader", "log-reader-both")),
]
RESOURCES = [
    res(
        "aws_iam_group_policy.support_assume",
        name="assume-prod-support",
        group="support-engineers",
        policy=doc(allow("AssumeProdSupport", "sts:AssumeRole", f"arn:aws:iam::{ACCOUNT}:role/prod-support")),
    ),
    res(
        "aws_iam_group_policy.analysts_assume",
        name="assume-analytics-read",
        group="data-analysts",
        policy=doc(
            allow("AssumeAnalyticsRead", "sts:AssumeRole", f"arn:aws:iam::{ACCOUNT}:role/analytics-read")
        ),
    ),
    res("aws_iam_role.prod_support", name="prod-support", assume_role_policy=trust_account()),
    res(
        "aws_iam_role_policy.prod_support_read",
        name="prod-support-read",
        role="prod-support",
        policy=doc(
            allow(
                "ReadLogs",
                ["s3:GetObject", "s3:ListBucket"],
                ["arn:aws:s3:::demo-app-logs", "arn:aws:s3:::demo-app-logs/*"],
            ),
            allow("ReadInvoices", "s3:GetObject", "arn:aws:s3:::demo-company-files/invoices/*"),
            allow(
                "ReadDbSecret",
                "secretsmanager:GetSecretValue",
                f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:prod-db-credentials-*",
            ),
        ),
    ),
    res(
        "aws_iam_role.analytics_read",
        name="analytics-read",
        assume_role_policy=doc(
            {
                "Effect": "Allow",
                "Action": "sts:AssumeRole",
                "Principal": {"AWS": "arn:aws:iam::999988887777:root"},
            }
        ),
    ),
    res(
        "aws_iam_policy.orders_table_rw",
        name="orders-table-rw",
        policy=doc(
            allow(
                "OrdersTableReadWrite",
                ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                [TABLE, f"{TABLE}/index/*"],
            )
        ),
    ),
    *(
        res(
            f"aws_iam_role.{r.replace('-', '_')}",
            name=r,
            assume_role_policy=trust_service("ecs-tasks.amazonaws.com"),
        )
        for r in ("orders-api-task", "orders-worker-task")
    ),
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
        "aws_iam_role.billing_job",
        name="billing-job",
        assume_role_policy=trust_service("lambda.amazonaws.com"),
    ),
    res(
        "aws_iam_role_policy.billing_job",
        name="billing-job",
        role="billing-job",
        policy=doc(allow("ReadOrders", "dynamodb:Query", [TABLE, f"{TABLE}/index/*"])),
    ),
    res(
        "aws_iam_role.audit_read",
        name="audit-read",
        assume_role_policy=doc(
            {
                "Sid": "TrustAuditor",
                "Effect": "Allow",
                "Action": "sts:AssumeRole",
                "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:user/auditor"},
            }
        ),
    ),
    res(
        "aws_iam_role_policy.audit_read",
        name="audit-read",
        role="audit-read",
        policy=doc(allow("ReadLogs", "s3:GetObject", "arn:aws:s3:::demo-app-logs/*")),
    ),
    res("aws_iam_role.shadow", name="shadow", assume_role_policy=trust_account()),
    res("aws_iam_role_policy.shadow", name="shadow", role="shadow"),
    res(
        "aws_iam_role_policy.config_reader",
        name="config-reader",
        role="config-reader",
        policy=doc(
            allow("ReadProdParams", "ssm:GetParameter", f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter/prod/*")
        ),
    ),
    res(
        "aws_iam_role_policy_attachment.log_shipper_logs",
        role="log-shipper",
        policy_arn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    ),
    res(
        "aws_iam_role_policy.log_reader",
        name="log-reader",
        role="log-reader",
        policy=doc(allow("ReadOneGroup", "logs:FilterLogEvents", f"{LOG_GROUP}:*")),
    ),
    res(
        "aws_iam_role_policy.log_reader_both",
        name="log-reader-both",
        role="log-reader-both",
        policy=doc(
            allow(
                "ReadOneGroup", ["logs:FilterLogEvents", "logs:GetLogEvents"], [LOG_GROUP, f"{LOG_GROUP}:*"]
            )
        ),
    ),
    res(
        "aws_s3_bucket_policy.company_files_public",
        bucket="demo-company-files",
        policy=doc(allow("PublicRead", "s3:GetObject", "arn:aws:s3:::demo-company-files/*", Principal="*")),
    ),
    res(
        "aws_s3_bucket_policy.app_logs_office",
        bucket="demo-app-logs",
        policy=doc(
            allow(
                "OfficeRead",
                "s3:GetObject",
                "arn:aws:s3:::demo-app-logs/*",
                Principal={"AWS": "*"},
                Condition={"IpAddress": {"aws:SourceIp": "203.0.113.0/24"}},
            ),
            allow(
                "SamOnly",
                "s3:PutObject",
                "arn:aws:s3:::demo-app-logs/*",
                Principal={"AWS": f"arn:aws:iam::{ACCOUNT}:user/sam-support"},
            ),
        ),
    ),
]


@pytest.fixture(scope="module")
def edges() -> dict[tuple[str, str, str], EdgeRow]:
    rows = derive_access_edges(RESOURCES, NODES, CONFIG, locate)
    assert rows == sorted(rows, key=lambda e: (e.type, e.src, e.dst))
    return {(e.type, e.src, e.dst): e for e in rows}


def summary(
    edges: dict[tuple[str, str, str], EdgeRow], src: str
) -> dict[tuple[str, str], tuple[str, list[str]]]:
    return {(t, d): (e.kind, e.grants) for (t, s, d), e in edges.items() if s == src}


def test_a_role_reaches_what_its_inline_policy_names(edges: dict) -> None:
    assert summary(edges, "role:prod-support") == {
        ("CAN", "s3://demo-app-logs/"): ("configured", ["read"]),
        ("CAN", "s3://demo-company-files/invoices/"): ("configured", ["read"]),
        ("CAN", "secret:prod-db-credentials"): ("configured", ["read"]),
    }
    ev = edges[("CAN", "role:prod-support", "s3://demo-company-files/invoices/")].evidence
    assert [(e.address, e.part) for e in ev] == [("aws_iam_role_policy.prod_support_read", "ReadInvoices")]


def test_both_task_roles_reach_the_orders_table_through_the_shared_policy(edges: dict) -> None:
    for role in ("role:orders-api-task", "role:orders-worker-task"):
        edge = edges[("CAN", role, "dynamodb:demo-orders")]
        assert (edge.kind, edge.grants) == ("configured", ["read", "write"])
        [ev] = edge.evidence
        assert (ev.address, ev.part) == ("aws_iam_policy.orders_table_rw", "OrdersTableReadWrite")
        assert ev.note and ev.note.startswith("attached by aws_iam_role_policy_attachment.orders_")


def test_dynamodb_read_and_write_are_split(edges: dict) -> None:
    assert summary(edges, "role:billing-job") == {("CAN", "dynamodb:demo-orders"): ("configured", ["read"])}


def test_a_group_assumes_a_role_that_trusts_the_account(edges: dict) -> None:
    edge = edges[("CAN_ASSUME", "group:support-engineers", "role:prod-support")]
    assert edge.kind == "configured"
    assert [(e.address, e.part) for e in edge.evidence] == [
        ("aws_iam_group_policy.support_assume", "AssumeProdSupport"),
        ("aws_iam_role.prod_support", "TrustAccountPrincipals"),
    ]
    assert summary(edges, "group:support-engineers") == {
        ("CAN_ASSUME", "role:prod-support"): ("configured", [])
    }


def test_no_edge_for_a_group_whose_role_does_not_trust_the_account(edges: dict) -> None:
    assert summary(edges, "group:data-analysts") == {}


def test_account_trust_alone_does_not_let_a_user_assume(edges: dict) -> None:
    assert summary(edges, "user:sam-support") == {}
    assert summary(edges, "user:priya-intern") == {}


def test_explicit_trust_needs_no_permission_from_the_caller(edges: dict) -> None:
    edge = edges[("CAN_ASSUME", "user:auditor", "role:audit-read")]
    assert edge.kind == "configured"
    assert [(e.address, e.part) for e in edge.evidence] == [("aws_iam_role.audit_read", "TrustAuditor")]


def test_service_roles_are_assumed_by_no_principal(edges: dict) -> None:
    for role in ("role:orders-api-task", "role:orders-worker-task", "role:billing-job"):
        assert not any(t == "CAN_ASSUME" and d == role for t, _, d in edges)


def test_an_unknown_policy_makes_every_edge_it_could_create_unknown(edges: dict) -> None:
    got = summary(edges, "role:shadow")
    assert got[("CAN", "s3://demo-app-logs/")] == ("unknown", ["read", "write"])
    assert got[("CAN", "secret:prod-db-credentials")] == ("unknown", ["read"])
    assert got[("CAN", "dynamodb:demo-orders")] == ("unknown", ["read", "write"])
    assert got[("CAN_ASSUME", "role:prod-support")] == ("unknown", [])
    assert ("CAN_ASSUME", "role:audit-read") not in got
    assert all(kind == "unknown" for kind, _ in got.values())


def test_a_public_bucket_policy_lets_the_internet_read(edges: dict) -> None:
    got = summary(edges, "entry:internet")
    assert got[("CAN", "s3://demo-company-files/invoices/")] == ("configured", ["read"])
    assert got[("CAN", "s3://demo-company-files/public/")] == ("configured", ["read"])
    [ev] = edges[("CAN", "entry:internet", "s3://demo-company-files/public/")].evidence
    assert (ev.address, ev.part) == ("aws_s3_bucket_policy.company_files_public", "PublicRead")


def test_a_conditional_public_statement_is_unknown_and_a_named_principal_is_not_public(edges: dict) -> None:
    got = summary(edges, "entry:internet")
    assert got[("CAN", "s3://demo-app-logs/")] == ("unknown", ["read"])


def test_no_edge_reaches_a_database_directly(edges: dict) -> None:
    assert not any(d == "db:customer-db" for _, _, d in edges)


def test_a_permissions_boundary_makes_the_principal_s_access_unknown() -> None:
    bounded = [
        r.model_copy(
            update={"values": {**r.values, "permissions_boundary": f"arn:aws:iam::{ACCOUNT}:policy/limit"}}
        )
        if r.address == "aws_iam_role.prod_support"
        else r
        for r in RESOURCES
    ]
    rows = {(e.type, e.src, e.dst): e for e in derive_access_edges(bounded, NODES, CONFIG, locate)}
    edge = rows[("CAN", "role:prod-support", "s3://demo-company-files/invoices/")]
    assert (edge.kind, edge.grants) == ("unknown", ["read"])
    assert edge.evidence[-1].note == f"permissions boundary arn:aws:iam::{ACCOUNT}:policy/limit not modeled"
    assert rows[("CAN_ASSUME", "group:support-engineers", "role:prod-support")].kind == "configured"


def test_every_edge_is_can_or_can_assume_with_a_placeholder_eid(edges: dict) -> None:
    assert {t for t, _, _ in edges} == {"CAN", "CAN_ASSUME"}
    assert all(e.eid == "" for e in edges.values())


def test_an_ssm_parameter_is_read_like_a_secret(edges: dict) -> None:
    assert summary(edges, "role:config-reader") == {
        ("CAN", "ssm-parameter:/prod/db-password"): ("configured", ["read"])
    }


def test_the_lambda_basic_policy_writes_every_log_group(edges: dict) -> None:
    assert summary(edges, "role:log-shipper") == {
        ("CAN", "log-group:/aws/lambda/billing-job"): ("configured", ["write"])
    }
    [ev] = edges[("CAN", "role:log-shipper", "log-group:/aws/lambda/billing-job")].evidence
    assert ev.note == "AWS-managed AWSLambdaBasicExecutionRole"


def test_a_log_group_named_in_only_one_form_is_unknown(edges: dict) -> None:
    """`log-group:NAME:*` matches one ARN form AWS may check but not the other, so the answer is unknown."""
    assert summary(edges, "role:log-reader") == {
        ("CAN", "log-group:/aws/lambda/billing-job"): ("unknown", ["read"])
    }


def test_a_log_group_named_in_both_forms_is_read(edges: dict) -> None:
    got = summary(edges, "role:log-reader-both")
    assert got == {("CAN", "log-group:/aws/lambda/billing-job"): ("configured", ["read"])}


# One world per case below, each built from the pieces above.


def derive(resources: list[IacResource]) -> dict[tuple[str, str, str], EdgeRow]:
    return {(e.type, e.src, e.dst): e for e in derive_access_edges(resources, NODES, CONFIG, locate)}


def deny(sid: str, action: object, resource: object, **extra: object) -> dict:
    return {"Sid": sid, "Effect": "Deny", "Action": action, "Resource": resource, **extra}


def membership(user: str, *groups: str) -> IacResource:
    return res(f"aws_iam_user_group_membership.{user.replace('-', '_')}", user=user, groups=list(groups))


MFA = {"Bool": {"aws:MultiFactorAuthPresent": "true"}}
INVOICES = "arn:aws:s3:::demo-company-files/invoices/*"


def test_conditional_trust_naming_a_user_is_an_unknown_edge_without_permission() -> None:
    world = [
        res(
            "aws_iam_role.audit_read",
            name="audit-read",
            assume_role_policy=doc(
                {
                    "Sid": "TrustAuditorWithMfa",
                    "Effect": "Allow",
                    "Action": "sts:AssumeRole",
                    "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:user/auditor"},
                    "Condition": MFA,
                }
            ),
        ),
        res(
            "aws_iam_role.prod_support",
            name="prod-support",
            assume_role_policy=doc(
                {"Effect": "Allow", "Action": "sts:AssumeRole", "Principal": {"AWS": ROOT}, "Condition": MFA}
            ),
        ),
    ]
    rows = derive(world)
    edge = rows[("CAN_ASSUME", "user:auditor", "role:audit-read")]
    assert edge.kind == "unknown"
    assert [(e.address, e.part) for e in edge.evidence] == [
        ("aws_iam_role.audit_read", "TrustAuditorWithMfa")
    ]
    assert not any(t == "CAN_ASSUME" and d == "role:prod-support" for t, _, d in rows)


def test_a_group_deny_overrides_a_member_s_own_allow() -> None:
    world = [
        res(
            "aws_iam_user_policy.priya_read",
            name="priya-read",
            user="priya-intern",
            policy=doc(
                allow("ReadInvoices", "s3:GetObject", INVOICES),
                allow("AssumeProdSupport", "sts:AssumeRole", f"arn:aws:iam::{ACCOUNT}:role/prod-support"),
            ),
        ),
        res(
            "aws_iam_group_policy.support_guardrails",
            name="support-guardrails",
            group="support-engineers",
            policy=doc(
                deny("NoInvoices", "s3:GetObject", INVOICES),
                deny("NoProdSupport", "sts:AssumeRole", "*"),
            ),
        ),
        membership("priya-intern", "support-engineers"),
        res("aws_iam_role.prod_support", name="prod-support", assume_role_policy=trust_account()),
    ]
    assert summary(derive(world), "user:priya-intern") == {}


def test_a_conditional_group_deny_makes_a_member_s_allow_unknown() -> None:
    world = [
        res(
            "aws_iam_user_policy.priya_read",
            name="priya-read",
            user="priya-intern",
            policy=doc(allow("ReadInvoices", "s3:GetObject", INVOICES)),
        ),
        res(
            "aws_iam_group_policy.support_guardrails",
            name="support-guardrails",
            group="support-engineers",
            policy=doc(deny("NoInvoicesWithoutMfa", "s3:GetObject", INVOICES, Condition=MFA)),
        ),
        membership("priya-intern", "support-engineers"),
    ]
    rows = derive(world)
    edge = rows[("CAN", "user:priya-intern", "s3://demo-company-files/invoices/")]
    assert (edge.kind, edge.grants) == ("unknown", ["read"])
    assert [(e.address, e.part) for e in edge.evidence] == [
        ("aws_iam_group_policy.support_guardrails", "NoInvoicesWithoutMfa"),
        ("aws_iam_user_policy.priya_read", "ReadInvoices"),
    ]
    assert summary(rows, "group:support-engineers") == {}
