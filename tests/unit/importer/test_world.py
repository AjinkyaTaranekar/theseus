"""World input ownership, source collection and coverage through the frozen adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from theseus.adapters.aws.adapter import AwsAdapter
from theseus.adapters.github.adapter import GithubAdapter
from theseus.adapters.python.adapter import PythonAdapter
from theseus.adapters.terraform.adapter import TerraformAdapter
from theseus.contracts.adapters import Adapters
from theseus.errors import IngestError
from theseus.importer.world import load_world

ROOT = Path(__file__).resolve().parents[3]


def adapters(config: dict[str, Any]) -> Adapters:
    return Adapters(
        iac=TerraformAdapter(), cloud=AwsAdapter(config), ci=GithubAdapter(), code=PythonAdapter()
    )


def test_world_reads_fixture_and_counts_skipped_types() -> None:
    root = ROOT / "fixtures/intern/base"
    config = yaml.safe_load((root / "theseus.yaml").read_text())
    plan = json.loads((root.parent / "base.plan.json").read_text())
    world = load_world(root, plan, adapters(config))
    assert len(world.resources) == 137  # 15 of them in legacy.tf
    # C1's skipped files: the network, the platform services, and each bucket's settings.
    assert world.skipped_types == {
        "aws_apigatewayv2_api": 1,
        "aws_cloudwatch_event_rule": 2,
        "aws_cloudwatch_event_target": 2,
        "aws_db_parameter_group": 1,
        "aws_db_subnet_group": 1,
        "aws_default_security_group": 1,
        "aws_ecr_repository": 2,
        "aws_ecs_cluster": 1,
        "aws_internet_gateway": 1,
        "aws_kms_alias": 1,
        "aws_kms_key": 1,
        "aws_lambda_permission": 2,
        "aws_route53_record": 2,
        "aws_route53_zone": 1,
        "aws_route_table": 1,
        "aws_route_table_association": 2,
        "aws_s3_bucket_lifecycle_configuration": 4,
        "aws_s3_bucket_notification": 4,
        "aws_s3_bucket_public_access_block": 4,
        "aws_s3_bucket_server_side_encryption_configuration": 4,
        "aws_s3_bucket_versioning": 4,
        "aws_security_group": 2,
        "aws_subnet": 4,
        "aws_vpc": 1,
        "aws_vpc_endpoint": 1,
        "aws_vpc_security_group_egress_rule": 1,
        "aws_vpc_security_group_ingress_rule": 1,
    }
    assert len(world.iac_files) == 13 and len(world.ci_files) == 5 and len(world.code_files) == 27
    assert all(
        not Path(path).is_absolute()
        for files in [world.iac_files, world.ci_files, world.code_files]
        for path in files
    )
    assert world.config == config
    assert not world.unknown_fields and not world.unknowns


def test_made_up_resource_is_counted_without_unknown_field_noise(tmp_path: Path) -> None:
    (tmp_path / "theseus.yaml").write_text('account: "111122223333"\nregion: eu-west-1\n')
    config = yaml.safe_load((tmp_path / "theseus.yaml").read_text())
    plan = {
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "address": "fictional_widget.one",
                        "type": "fictional_widget",
                        "name": "one",
                        "values": {},
                    }
                ]
            }
        },
        "resource_changes": [
            {"address": "fictional_widget.one", "change": {"after_unknown": {"name": True}}}
        ],
    }
    world = load_world(tmp_path, plan, adapters(config))
    assert world.skipped_types == {"fictional_widget": 1}
    assert not world.unknown_fields and not world.unknowns


@pytest.mark.parametrize("text", ["[one, two]", "account: [", "null", "1: value"])
def test_bad_config_is_ingest_error(tmp_path: Path, text: str) -> None:
    (tmp_path / "theseus.yaml").write_text(text)
    with pytest.raises(IngestError):
        load_world(
            tmp_path,
            {"planned_values": {"root_module": {}}},
            adapters({"account": "111122223333", "region": "eu-west-1"}),
        )


def test_missing_root_is_ingest_error(tmp_path: Path) -> None:
    with pytest.raises(IngestError):
        load_world(tmp_path / "missing", {}, adapters({"account": "111122223333", "region": "eu-west-1"}))


def test_staged_adapters_contribute_nothing() -> None:
    from theseus.contracts.result import GraphRows

    assert not GithubAdapter().read({"workflows/org/repo/a.yml": "bad: ["}).rows.nodes
    assert not PythonAdapter().read({"services/a.py": "not python"}, GraphRows(), []).edges
