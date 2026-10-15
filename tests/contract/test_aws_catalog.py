"""The AWS catalog against AWS's own service reference (tests/data/aws_service_reference.json).

When this fails after a catalog change, run `tools/aws_service_reference.py` and commit the snapshot.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from theseus.adapters.aws.catalog import (
    Catalog,
    CatalogAction,
    DataEntry,
    WorkloadEntry,
    load_catalog,
    value_at,
)
from theseus.adapters.aws.iam import ASSUME
from theseus.adapters.aws.kinds import MODELED_TYPES, RESOURCE_KINDS, STRUCTURAL_TYPES
from theseus.contracts.schema import CORE_KINDS, RESOURCE_CATEGORIES, WORKLOAD_LABELS
from theseus.errors import IngestError

REFERENCE = json.loads(Path("tests/data/aws_service_reference.json").read_text(encoding="utf-8"))
CATALOG = load_catalog()
CONFIG = {"account": "111122223333", "region": "eu-west-1"}
SAMPLE = {"name": "/team/sample", "bucket": "demo-bucket", "prefix": "some/prefix/"}
ACTIONS = [(e, a) for e in CATALOG.data for a in e.actions()]


def ident(pair: tuple[DataEntry, CatalogAction]) -> str:
    return f"{pair[0].kind}-{pair[1].action}"


def fits(arn: str, formats: list[str]) -> bool:
    """Whether an ARN fits one of AWS's formats, each `${Placeholder}` standing for any text."""
    patterns = [".+".join(re.escape(part) for part in re.split(r"\$\{\w+\}", f)) for f in formats]
    return any(re.fullmatch(p, arn) for p in patterns)


@pytest.mark.parametrize("pair", ACTIONS, ids=ident)
def test_every_action_exists_in_the_service_reference(pair: tuple[DataEntry, CatalogAction]) -> None:
    entry, action = pair
    service, name = action.action.split(":", 1)
    assert name in REFERENCE[service]["actions"], f"run tools/aws_service_reference.py ({action.action})"


@pytest.mark.parametrize("pair", ACTIONS, ids=ident)
def test_reads_are_read_level_and_writes_are_write_level(pair: tuple[DataEntry, CatalogAction]) -> None:
    entry, action = pair
    service, name = action.action.split(":", 1)
    flags = REFERENCE[service]["actions"][name]
    assert not flags["list"] and not flags["permissions"] and not flags["tagging"], action.action
    assert flags["write"] is (action.access == "write"), action.action


@pytest.mark.parametrize("pair", ACTIONS, ids=ident)
def test_every_arn_we_test_an_action_on_fits_aws_formats(pair: tuple[DataEntry, CatalogAction]) -> None:
    entry, action = pair
    service, name = action.action.split(":", 1)
    ref = REFERENCE[service]
    assert action.resource_type in ref["actions"][name]["resources"], action.action
    formats = ref["resources"][action.resource_type]
    node_arn = entry.resource_arn(SAMPLE, CONFIG)
    for arn in action.arns_for(node_arn):
        if arn.endswith(":*"):
            continue  # the alternative log-group form AWS may check; tested in test_access.py
        assert fits(arn, formats), (arn, formats)


@pytest.mark.parametrize("entry", CATALOG.data, ids=lambda e: e.kind)
def test_every_node_arn_fits_its_resource_type(entry: DataEntry) -> None:
    formats = REFERENCE[entry.service]["resources"][entry.resource_type]
    assert fits(entry.resource_arn(SAMPLE, CONFIG), formats)


def test_assume_role_is_in_the_reference() -> None:
    service, name = ASSUME.split(":")
    assert REFERENCE[service]["actions"][name]["resources"] == ["role"]


def test_kinds_categories_and_modeled_types_come_from_the_catalog() -> None:
    assert RESOURCE_KINDS == {
        "s3": "ObjectStorage",
        "secret": "Secret",
        "ssm-parameter": "Secret",
        "dynamodb": "Database",
        "db": "Database",
        "opensearch": "Database",
        "log-group": "LogStore",
        "sqs": "MessageQueue",
        "sns": "MessageTopic",
        "kinesis": "DataStream",
    }
    assert set(RESOURCE_KINDS.values()) <= set(RESOURCE_CATEGORIES)
    assert not set(RESOURCE_KINDS) & set(CORE_KINDS)
    assert MODELED_TYPES == STRUCTURAL_TYPES | CATALOG.types
    assert {"aws_ecs_task_definition", "aws_iam_instance_profile"} <= CATALOG.types  # through `via`
    assert {"aws_ssm_parameter", "aws_cloudwatch_log_group"} <= MODELED_TYPES
    assert "aws_glue_catalog_table" not in MODELED_TYPES


def test_the_ssm_arn_drops_the_leading_slash() -> None:
    ssm = CATALOG.by_kind["ssm-parameter"]
    assert ssm.resource_arn({"name": "/prod/db-password"}, CONFIG) == (
        "arn:aws:ssm:eu-west-1:111122223333:parameter/prod/db-password"
    )


def test_a_location_arn_names_a_key_under_the_prefix() -> None:
    s3 = CATALOG.by_kind["s3"]
    assert s3.per == "location"
    assert s3.resource_arn({"bucket": "b", "prefix": "invoices/"}, CONFIG) == "arn:aws:s3:::b/invoices/x"


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"kind": "Bad Kind"}, "not a node ID prefix"),
        ({"arn": "arn:{nope}"}, "unknown ARN variables"),
        ({"read": ["sqs:ReceiveMessage"]}, "is not a s3 action"),
        ({"read": [{"action": "s3:GetObject", "arns": ["{name}"]}]}, "may use only {arn}"),
    ],
)
def test_a_bad_entry_is_refused(patch: dict, message: str) -> None:
    raw = CATALOG.by_kind["s3"].model_dump() | patch
    with pytest.raises(ValueError, match=re.escape(message)):
        DataEntry.model_validate(raw)


def test_kinds_and_types_must_be_unique() -> None:
    s3 = CATALOG.by_kind["s3"].model_dump()
    with pytest.raises(ValueError, match="kinds must be unique"):
        Catalog.model_validate({"version": 1, "data": [s3, s3 | {"type": "aws_other"}]})
    lam = CATALOG.workloads[0].model_dump()
    with pytest.raises(ValueError, match="either data or a workload"):
        Catalog.model_validate({"version": 1, "data": [s3], "workloads": [lam | {"type": "aws_s3_bucket"}]})


def test_an_unreadable_catalog_is_an_ingest_error(tmp_path: Path) -> None:
    bad = tmp_path / "catalog.yaml"
    bad.write_text("version: 2\ndata: []\n", encoding="utf-8")
    with pytest.raises(IngestError):
        load_catalog(bad)


def test_the_refresh_tool_keeps_only_what_the_tests_need() -> None:
    spec = importlib.util.spec_from_file_location("svcref", Path("tools/aws_service_reference.py"))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    doc = {
        "Version": "v1",
        "Actions": [
            {
                "Name": "GetThing",
                "Annotations": {"Properties": {"IsWrite": False}},
                "Resources": [{"Name": "thing"}],
            },
            {"Name": "Other", "Annotations": {"Properties": {"IsWrite": True}}, "Resources": []},
        ],
        "Resources": [
            {"Name": "thing", "ARNFormats": ["arn:${Partition}:x:::${Thing}"]},
            {"Name": "unused", "ARNFormats": ["arn:x"]},
        ],
    }
    assert tool.trim(doc, {"GetThing": {"thing"}}, set()) == {
        "version": "v1",
        "actions": {
            "GetThing": {
                "write": False,
                "list": False,
                "permissions": False,
                "tagging": False,
                "resources": ["thing"],
            }
        },
        "resources": {"thing": ["arn:${Partition}:x:::${Thing}"]},
    }


def test_fits_rejects_an_arn_of_the_wrong_shape() -> None:
    formats = REFERENCE["s3"]["resources"]["object"]
    assert fits("arn:aws:s3:::bucket/key", formats)
    assert not fits("arn:aws:s3:::bucket", formats)
    assert not fits("arn:aws:dynamodb:eu-west-1:1:table/t", formats)


# Workloads ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("workload", CATALOG.workloads, ids=lambda w: w.type)
def test_every_workload_names_its_role_and_a_known_label(workload: WorkloadEntry) -> None:
    assert workload.role.field
    assert workload.label is None or workload.label in WORKLOAD_LABELS


def test_the_common_compute_types_are_workloads() -> None:
    by_type = {w.type: w for w in CATALOG.workloads}
    assert (by_type["aws_lambda_function"].runtime, by_type["aws_lambda_function"].label) == (
        "lambda",
        "Function",
    )
    ecs = by_type["aws_ecs_service"].role
    assert (ecs.via, ecs.join, ecs.match, ecs.field) == (
        "aws_ecs_task_definition",
        "task_definition",
        "family",
        "task_role_arn",
    )
    assert by_type["aws_instance"].role.via == "aws_iam_instance_profile"


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"runtime": "Lambda Fn"}, "lowercase words"),
        ({"label": "Lambda"}, "not one of"),
        ({"role": {"field": "x", "via": "aws_thing"}}, "via, join and match together"),
    ],
)
def test_a_bad_workload_is_refused(patch: dict, message: str) -> None:
    raw = CATALOG.workloads[0].model_dump() | patch
    with pytest.raises(ValueError, match=re.escape(message)):
        WorkloadEntry.model_validate(raw)


def test_value_at_follows_dotted_paths() -> None:
    values = {"tags": {"Name": "web-1"}, "instance_configuration": [{"instance_role_arn": "arn:x"}]}
    assert value_at(values, "tags.Name") == "web-1"
    assert value_at(values, "instance_configuration.0.instance_role_arn") == "arn:x"
    assert value_at(values, "instance_configuration.3.instance_role_arn") is None
    assert value_at(values, "missing.path") is None
