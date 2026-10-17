"""Catalog-driven nodes, workload identities and their structural evidence."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from theseus.adapters.aws.adapter import AwsAdapter
from theseus.adapters.aws.catalog import load_catalog
from theseus.adapters.terraform.adapter import TerraformAdapter
from theseus.contracts.adapters import Change, IacResource
from theseus.contracts.result import Evidence, GraphRows, PatchOp
from theseus.errors import IngestError, PatchError

ROOT = Path(__file__).resolve().parents[4]
CONFIG = yaml.safe_load((ROOT / "demo-infra/theseus.yaml").read_text())


def locate(address: str, part: str | None) -> Evidence:
    return Evidence(address=address, part=part, file="unknown", note="synthetic plan has no source")


def resource(rtype: str, address_name: str, **values: Any) -> IacResource:
    return IacResource(
        address=f"{rtype}.{address_name}", type=rtype, name=address_name, provider="aws", values=values
    )


def test_intern_structural_nodes_and_iam_integration() -> None:
    root = ROOT / "fixtures/intern/base"
    plan = json.loads((root.parent / "base.plan.json").read_text())
    read = TerraformAdapter().read(root, plan)
    rows = AwsAdapter(CONFIG).rows(
        read.resources, [], lambda a, p: TerraformAdapter().locate(read.files, a, p)
    )
    for label, count in [("User", 4), ("Group", 3), ("Role", 11), ("Workload", 6), ("Resource", 20)]:
        assert sum(label in n.labels for n in rows.nodes) == count
    assert all(n.props.get("arn") for n in rows.nodes if set(n.labels) & {"User", "Group", "Role"})
    assert all(
        n.props.get("arn_pattern") and n.category in n.labels and n.provider == "aws"
        for n in rows.nodes
        if "Resource" in n.labels
    )
    assert any(
        e.type == "CAN" and e.src == "role:prod-support" and e.dst == "secret:prod-db-credentials"
        for e in rows.edges
    )
    assert any(
        e.type == "CAN_ASSUME" and e.src == "group:support-engineers" and e.dst == "role:prod-support"
        for e in rows.edges
    )
    assert all(e.evidence and all(ev.file != "unknown" and ev.line for ev in e.evidence) for e in rows.edges)


@pytest.mark.parametrize(
    "task_definition",
    ["orders-api", "orders-api:17", "arn:aws:ecs:eu-west-1:111122223333:task-definition/orders-api:17"],
)
def test_ecs_task_role_and_environment(task_definition: str) -> None:
    resources = [
        resource("aws_iam_role", "runtime", name="runtime"),
        resource("aws_iam_role", "execution", name="execution"),
        resource("aws_secretsmanager_secret", "db", name="db-password"),
        resource(
            "aws_ecs_task_definition",
            "api",
            family="orders-api",
            task_role_arn="runtime",
            execution_role_arn="execution",
            container_definitions=json.dumps(
                [
                    {"name": "api", "environment": [{"name": "DB_SECRET", "value": "db-password"}]},
                    {"name": "sidecar", "environment": [{"name": "OTHER", "value": "db-password"}]},
                ]
            ),
        ),
        resource("aws_ecs_service", "api", name="orders-api", task_definition=task_definition),
    ]
    rows = AwsAdapter(CONFIG).rows(resources, [], locate)
    runs = [e for e in rows.edges if e.type == "RUNS_AS"]
    assert [(e.src, e.dst) for e in runs] == [("workload:orders-api", "role:runtime")]
    assert {ev.address for ev in runs[0].evidence} == {"aws_ecs_service.api", "aws_ecs_task_definition.api"}
    env = [e for e in rows.edges if e.type == "HAS_ENV"]
    assert [(e.dst, e.props["var"]) for e in env] == [("secret:db-password", "DB_SECRET")]


@pytest.mark.parametrize("entry", load_catalog().data, ids=lambda d: d.type)
def test_every_data_catalog_entry(entry: Any) -> None:
    values = {entry.name: "sample", "arn": None}
    if entry.per == "location":
        values = {"bucket": "bucket"}
    config = {**CONFIG, "data_locations": [{"id": "s3://bucket/a/", "bucket": "bucket", "prefix": "a/"}]}
    rows = AwsAdapter(config).rows([resource(entry.type, "sample", **values)], [], locate)
    data = [n for n in rows.nodes if "Resource" in n.labels]
    assert len(data) == 1
    assert data[0].category == entry.category and data[0].provider == "aws"
    assert data[0].props["kind"] == entry.kind and data[0].props["arn_pattern"].startswith("arn:aws:")


@pytest.mark.parametrize("entry", load_catalog().workloads, ids=lambda w: w.type)
def test_every_workload_catalog_entry(entry: Any) -> None:
    def put(values: dict[str, Any], path: str, value: str) -> None:
        parts = path.split(".")
        cursor: Any = values
        for i, part in enumerate(parts[:-1]):
            if isinstance(cursor, list):
                while len(cursor) <= int(part):
                    cursor.append({})
                cursor = cursor[int(part)]
            else:
                cursor = cursor.setdefault(part, [] if parts[i + 1].isdigit() else {})
        cursor[parts[-1]] = value

    values: dict[str, Any] = {}
    put(values, entry.name, "job")
    resources = [resource("aws_iam_role", "runtime", name="runtime")]
    if entry.role.via:
        put(values, entry.role.join, "indirect")
        via: dict[str, Any] = {}
        put(via, entry.role.match, "indirect")
        put(via, entry.role.field, "runtime")
        resources.append(resource(entry.role.via, "indirect", **via))
    else:
        put(values, entry.role.field, "runtime")
    resources.append(resource(entry.type, "job", **values))
    rows = AwsAdapter(CONFIG).rows(resources, [], locate)
    node = next(n for n in rows.nodes if n.id == "workload:job")
    assert node.props["runtime"] == entry.runtime
    assert not entry.label or entry.label in node.labels
    assert any(e.type == "RUNS_AS" and e.dst == "role:runtime" for e in rows.edges)


def test_unknown_policy_taints_access_and_is_reported() -> None:
    resources = [
        resource("aws_iam_role", "runtime", name="runtime"),
        resource("aws_iam_role_policy", "unknown", role="runtime", policy=None),
        resource("aws_secretsmanager_secret", "secret", name="password"),
    ]
    original = deepcopy(resources)
    rows = AwsAdapter(CONFIG).rows(resources, [], locate)
    assert any(e.type == "CAN" and e.kind == "unknown" for e in rows.edges)
    assert rows.unknowns
    assert resources == original


def test_missing_role_and_database_are_reported_without_dangling_edges() -> None:
    rows = AwsAdapter(CONFIG).rows(
        [
            resource("aws_lambda_function", "fn", function_name="fn", role="absent"),
            resource("aws_secretsmanager_secret", "secret", name="secret", tags={"db_instance": "absent"}),
        ],
        [],
        locate,
    )
    assert not any(e.type in {"RUNS_AS", "UNLOCKS"} for e in rows.edges)
    assert any("absent" in message for message in rows.unknowns)


def test_s3_locations_cannot_name_a_different_bucket() -> None:
    config = {**CONFIG, "data_locations": [{"id": "s3://other/", "bucket": "bucket", "prefix": ""}]}
    with pytest.raises(IngestError):
        AwsAdapter(config).rows([resource("aws_s3_bucket", "bucket", bucket="bucket")], [], locate)


def test_patch_handoffs_are_explicit() -> None:
    adapter = AwsAdapter(CONFIG)
    assert adapter.ops_schema()["oneOf"]
    with pytest.raises(PatchError, match="edge ID"):
        adapter.ops_for(Change(kind="remove_edge", eid="e1"), GraphRows(), [])
    assert adapter.apply_ops([], []) == []
    with pytest.raises(PatchError, match="unknown aws op"):
        adapter.apply_ops([], [PatchOp(provider="aws", op="not_an_operation")])


def test_a_known_secret_arn_is_used_instead_of_a_representative_suffix() -> None:
    arn = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:password-XyZ123"
    rows = AwsAdapter(CONFIG).rows(
        [resource("aws_secretsmanager_secret", "password", name="password", arn=arn)], [], locate
    )
    node = next(n for n in rows.nodes if n.id == "secret:password")
    assert node.props["arn_pattern"] == arn


@pytest.mark.parametrize(
    "arn",
    [
        "arn:aws:iam::999900001111:role/runtime",
        "arn:aws:iam::111122223333:role/different-path/runtime",
    ],
)
def test_an_arn_does_not_bind_a_different_role_with_the_same_basename(arn: str) -> None:
    rows = AwsAdapter(CONFIG).rows(
        [
            resource("aws_iam_role", "runtime", name="runtime"),
            resource("aws_lambda_function", "fn", function_name="fn", role=arn),
        ],
        [],
        locate,
    )
    assert not any(e.type == "RUNS_AS" for e in rows.edges)
    assert rows.unknowns


def test_a_catalogs_alternate_arn_form_keeps_its_action_variants() -> None:
    base = "arn:aws:logs:eu-west-1:111122223333:log-group:/app"
    rows = AwsAdapter(CONFIG).rows(
        [
            resource("aws_cloudwatch_log_group", "logs", name="/app", arn=base + ":*"),
            resource("aws_iam_role", "reader", name="reader"),
            resource(
                "aws_iam_role_policy",
                "read",
                role="reader",
                policy=json.dumps(
                    {
                        "Statement": [
                            {
                                "Sid": "Read",
                                "Effect": "Allow",
                                "Action": "logs:FilterLogEvents",
                                "Resource": base,
                            }
                        ]
                    }
                ),
            ),
        ],
        [],
        locate,
    )
    node = next(n for n in rows.nodes if n.id == "log-group:/app")
    assert node.props["arn_pattern"] == base
    assert any(e.type == "CAN" and e.dst == node.id and e.kind == "unknown" for e in rows.edges)


@pytest.mark.parametrize("locations", [None, "bad", {}, [None], ["bad"], [{"id": "s3://bucket/"}]])
def test_malformed_data_location_config_is_a_typed_error(locations: Any) -> None:
    with pytest.raises(IngestError):
        AwsAdapter({**CONFIG, "data_locations": locations})


@pytest.mark.parametrize(
    "task_arn",
    [
        "arn:aws:ecs:eu-west-1:999900001111:task-definition/orders-api:17",
        "arn:aws:ecs:us-east-1:111122223333:task-definition/orders-api:17",
    ],
)
def test_a_task_arn_in_another_scope_does_not_bind_a_local_family(task_arn: str) -> None:
    rows = AwsAdapter(CONFIG).rows(
        [
            resource("aws_iam_role", "runtime", name="runtime"),
            resource("aws_ecs_task_definition", "api", family="orders-api", task_role_arn="runtime"),
            resource("aws_ecs_service", "api", name="orders-api", task_definition=task_arn),
        ],
        [],
        locate,
    )
    assert not any(e.type == "RUNS_AS" for e in rows.edges)
    assert any("unresolved" in message for message in rows.unknowns)
