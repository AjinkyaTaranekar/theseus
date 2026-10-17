"""Plan facts, reference resolution and unknown fields without provider calls."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from theseus.adapters.aws.catalog import load_catalog
from theseus.adapters.terraform.adapter import TerraformAdapter
from theseus.adapters.terraform.plan import READ_FIELDS
from theseus.errors import IngestError


def test_every_catalog_read_field_is_tracked_for_unknown_values() -> None:
    catalog = load_catalog()
    paths = [entry.name for entry in catalog.data]
    for entry in catalog.workloads:
        paths.extend([entry.name, entry.role.field, entry.role.join, entry.role.match])
    assert {path.split(".")[0] for path in paths if path} <= READ_FIELDS


def plan_for(values: dict[str, Any], unknown: dict[str, Any]) -> dict[str, Any]:
    return {
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "address": "aws_iam_role.demo",
                        "type": "aws_iam_role",
                        "name": "demo",
                        "provider_name": "registry.terraform.io/hashicorp/aws",
                        "values": values,
                    }
                ]
            }
        },
        "resource_changes": [{"address": "aws_iam_role.demo", "change": {"after_unknown": unknown}}],
    }


@pytest.mark.parametrize(
    "field",
    [
        "name",
        "policy",
        "assume_role_policy",
        "role",
        "policy_arn",
        "groups",
        "tags",
        "environment",
        "task_role_arn",
        "container_definitions",
        "task_definition",
        "bucket",
    ],
)
def test_unknown_fields_the_importer_reads(tmp_path: Path, field: str) -> None:
    result = TerraformAdapter().read(tmp_path, plan_for({field: None}, {field: True, "subnet_id": True}))
    assert [(u.address, u.field, u.references) for u in result.unknown_fields] == [
        ("aws_iam_role.demo", field, [])
    ]


@pytest.mark.parametrize("value", [False, [False], {"variables": {}}, [{"variables": {}}], [], {}])
def test_unknown_shape_requires_literal_true(tmp_path: Path, value: Any) -> None:
    assert not TerraformAdapter().read(tmp_path, plan_for({}, {"environment": value})).unknown_fields


@pytest.mark.parametrize(
    "rtype", ["aws_s3_bucket", "aws_secretsmanager_secret", "aws_sns_topic", "aws_sqs_queue"]
)
def test_computed_policy_is_not_a_policy_document(tmp_path: Path, rtype: str) -> None:
    plan = plan_for({"name": "demo"}, {"arn": True, "policy": True})
    plan["planned_values"]["root_module"]["resources"][0]["type"] = rtype
    assert not TerraformAdapter().read(tmp_path, plan).unknown_fields


def test_nested_modules_data_and_reference_resolution(tmp_path: Path) -> None:
    prefix = 'module.app["blue"]'
    address = f"{prefix}.aws_iam_role.demo"
    plan = plan_for({"name": "demo"}, {})
    root = plan["planned_values"]["root_module"]
    role = root.pop("resources")[0]
    role["address"] = address
    root["child_modules"] = [
        {
            "address": prefix,
            "resources": [
                role,
                {
                    "address": f"{prefix}.aws_lambda_function.fn",
                    "type": "aws_lambda_function",
                    "name": "fn",
                    "values": {"function_name": "fn", "role": None},
                },
                {
                    "address": f"{prefix}.data.aws_region.current",
                    "mode": "data",
                    "type": "aws_region",
                    "name": "current",
                    "values": {"name": "eu-west-1"},
                },
            ],
        }
    ]
    plan["resource_changes"] = [
        {"address": f"{prefix}.aws_lambda_function.fn", "change": {"after_unknown": {"role": True}}}
    ]
    plan["configuration"] = {
        "root_module": {
            "module_calls": {
                "app": {
                    "module": {
                        "resources": [
                            {
                                "address": "aws_lambda_function.fn",
                                "expressions": {
                                    "role": {"references": ["aws_iam_role.demo.name", "aws_iam_role.demo"]}
                                },
                            }
                        ]
                    }
                }
            }
        }
    }
    original = deepcopy(plan)
    result = TerraformAdapter().read(tmp_path, plan)
    assert len(result.resources) == 2
    fn = next(r for r in result.resources if r.type == "aws_lambda_function")
    assert fn.values["role"] == "demo"
    assert not result.unknown_fields
    assert plan == original


def test_unknown_policy_clears_stale_value_and_keeps_references(tmp_path: Path) -> None:
    plan = plan_for({"policy": '{"Statement": []}'}, {"policy": True})
    refs = ["data.external.policy.result", "data.external.policy"]
    plan["configuration"] = {
        "root_module": {
            "resources": [{"address": "aws_iam_role.demo", "expressions": {"policy": {"references": refs}}}]
        }
    }
    result = TerraformAdapter().read(tmp_path, plan)
    assert result.resources[0].values["policy"] is None
    assert result.unknown_fields[0].references == sorted(refs)


@pytest.mark.parametrize("plan", [{}, {"planned_values": []}, {"errored": True}, {"complete": False}])
def test_invalid_or_incomplete_plan_is_ingest_error(tmp_path: Path, plan: dict[str, Any]) -> None:
    with pytest.raises(IngestError):
        TerraformAdapter().read(tmp_path, plan)


def test_read_source_and_render_boundary(tmp_path: Path) -> None:
    source = tmp_path / "terraform" / "nested" / "main.tf"
    source.parent.mkdir(parents=True)
    source.write_text('resource "aws_iam_role" "demo" {}\n')
    result = TerraformAdapter().read(tmp_path, plan_for({"name": "demo"}, {}))
    assert result.files == {"terraform/nested/main.tf": source.read_text()}
    rendered = TerraformAdapter().render(result.files, [])
    assert rendered == result.files
    assert rendered is not result.files


def test_reference_in_a_counted_resource_with_a_dot_in_its_key(tmp_path: Path) -> None:
    plan = plan_for({"name": "demo"}, {})
    role = plan["planned_values"]["root_module"].pop("resources")[0]
    role["address"] = "module.app.aws_iam_role.demo"
    fn = {
        "address": 'module.app.aws_lambda_function.fn["api.example"]',
        "type": "aws_lambda_function",
        "name": "fn",
        "values": {"role": None},
    }
    plan["planned_values"]["root_module"]["child_modules"] = [{"resources": [role, fn]}]
    plan["resource_changes"] = [{"address": fn["address"], "change": {"after_unknown": {"role": True}}}]
    plan["configuration"] = {
        "root_module": {
            "module_calls": {
                "app": {
                    "module": {
                        "resources": [
                            {
                                "address": "aws_lambda_function.fn",
                                "expressions": {
                                    "role": {"references": ["aws_iam_role.demo.name", "aws_iam_role.demo"]}
                                },
                            }
                        ]
                    }
                }
            }
        }
    }
    result = TerraformAdapter().read(tmp_path, plan)
    assert next(r for r in result.resources if r.type == "aws_lambda_function").values["role"] == "demo"
    assert not result.unknown_fields


def test_reference_with_an_unresolved_second_input_is_not_resolved(tmp_path: Path) -> None:
    plan = plan_for({"name": "demo"}, {})
    fn = {
        "address": "aws_lambda_function.fn",
        "type": "aws_lambda_function",
        "name": "fn",
        "values": {"role": None},
    }
    plan["planned_values"]["root_module"]["resources"].append(fn)
    plan["resource_changes"] = [{"address": fn["address"], "change": {"after_unknown": {"role": True}}}]
    plan["configuration"] = {
        "root_module": {
            "resources": [
                {
                    "address": fn["address"],
                    "expressions": {
                        "role": {"references": ["aws_iam_role.demo.name", "data.external.role.result"]}
                    },
                }
            ]
        }
    }
    result = TerraformAdapter().read(tmp_path, plan)
    assert next(r for r in result.resources if r.type == "aws_lambda_function").values["role"] is None
    assert result.unknown_fields


def test_a_child_reference_does_not_fall_back_to_a_root_resource(tmp_path: Path) -> None:
    plan = plan_for({"name": "root-role"}, {})
    fn = {
        "address": "module.child.aws_lambda_function.fn",
        "type": "aws_lambda_function",
        "name": "fn",
        "values": {"role": None},
    }
    plan["planned_values"]["root_module"]["child_modules"] = [{"resources": [fn]}]
    plan["resource_changes"] = [{"address": fn["address"], "change": {"after_unknown": {"role": True}}}]
    plan["configuration"] = {
        "root_module": {
            "module_calls": {
                "child": {
                    "module": {
                        "resources": [
                            {
                                "address": "aws_lambda_function.fn",
                                "expressions": {"role": {"references": ["aws_iam_role.demo.name"]}},
                            }
                        ]
                    }
                }
            }
        }
    }
    result = TerraformAdapter().read(tmp_path, plan)
    assert next(r for r in result.resources if r.type == "aws_lambda_function").values["role"] is None
    assert result.unknown_fields


@pytest.mark.parametrize("address", [None, [], {}, 42, ""])
def test_a_malformed_change_address_is_a_typed_error(tmp_path: Path, address: Any) -> None:
    plan = plan_for({"name": "demo"}, {})
    plan["resource_changes"] = [{"address": address, "change": {}}]
    with pytest.raises(IngestError):
        TerraformAdapter().read(tmp_path, plan)


def test_malformed_referenced_expression_is_a_typed_error(tmp_path: Path) -> None:
    plan = plan_for({}, {})
    plan["planned_values"]["root_module"]["resources"].append(
        {
            "address": "aws_lambda_function.fn",
            "type": "aws_lambda_function",
            "name": "fn",
            "values": {"role": None},
        }
    )
    plan["resource_changes"] = [
        {"address": "aws_lambda_function.fn", "change": {"after_unknown": {"role": True}}}
    ]
    plan["configuration"] = {
        "root_module": {
            "resources": [
                {"address": "aws_iam_role.demo", "expressions": {"name": None}},
                {
                    "address": "aws_lambda_function.fn",
                    "expressions": {"role": {"references": ["aws_iam_role.demo.name"]}},
                },
            ]
        }
    }
    with pytest.raises(IngestError):
        TerraformAdapter().read(tmp_path, plan)


@pytest.mark.parametrize("plan", [None, [], 1, "plan"])
def test_a_non_object_plan_is_a_typed_error(tmp_path: Path, plan: Any) -> None:
    with pytest.raises(IngestError):
        TerraformAdapter().read(tmp_path, plan)
