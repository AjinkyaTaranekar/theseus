"""List-price estimates for AWS resources (O3): what the code declares is priced, what is billed by use is
listed at 0, and a type the table cannot price is left out."""

from __future__ import annotations

from typing import Any

import pytest

from theseus.adapters.aws.adapter import AwsAdapter
from theseus.adapters.aws.cost import FARGATE_GB, FARGATE_VCPU, HOURS, RDS_HOURLY, monthly_cost
from theseus.contracts.adapters import IacResource


def res(kind: str, name: str, **values: Any) -> IacResource:
    return IacResource(address=f"{kind}.{name}", type=kind, name=name, provider="aws", values=values)


def lines(*resources: IacResource) -> dict[str, tuple[float, str, bool]]:
    return {
        line.address: (line.monthly_usd, line.basis, line.usage_billed)
        for line in monthly_cost(list(resources))
    }


def test_an_ecs_service_is_priced_from_its_task_definition_and_count() -> None:
    found = lines(
        res("aws_ecs_task_definition", "api", family="api", cpu="256", memory="512"),
        res("aws_ecs_service", "api", task_definition="api", desired_count=2, launch_type="FARGATE"),
    )
    usd, basis, usage = found["aws_ecs_service.api"]
    assert usd == round(2 * (0.25 * FARGATE_VCPU + 0.5 * FARGATE_GB) * HOURS, 2)
    assert basis == "2 Fargate task(s) of 0.25 vCPU and 0.5 GB" and not usage
    assert "aws_ecs_task_definition.api" not in found  # the service carries its cost


def test_a_multi_az_database_doubles_instance_and_storage() -> None:
    single = lines(res("aws_db_instance", "a", instance_class="db.t4g.micro", allocated_storage=20))
    multi = lines(
        res("aws_db_instance", "a", instance_class="db.t4g.micro", allocated_storage=20, multi_az=True)
    )
    assert single["aws_db_instance.a"][0] == round(RDS_HOURLY["db.t4g.micro"] * HOURS + 20 * 0.115, 2)
    assert multi["aws_db_instance.a"][0] == round(2 * (RDS_HOURLY["db.t4g.micro"] * HOURS + 20 * 0.115), 2)
    assert multi["aws_db_instance.a"][1] == "db.t4g.micro, Multi-AZ, 20 GB storage"


@pytest.mark.parametrize(
    ("kind", "values", "usd"),
    [
        ("aws_kms_key", {}, 1.0),
        ("aws_secretsmanager_secret", {}, 0.4),
        ("aws_route53_zone", {}, 0.5),
        ("aws_vpc_endpoint", {"vpc_endpoint_type": "Gateway"}, 0.0),
        ("aws_vpc_endpoint", {"vpc_endpoint_type": "Interface", "subnet_ids": ["a", "b"]}, 14.6),
    ],
)
def test_flat_prices(kind: str, values: dict[str, Any], usd: float) -> None:
    assert lines(res(kind, "x", **values))[f"{kind}.x"][0] == usd


def test_what_is_billed_by_use_is_listed_at_zero_and_marked() -> None:
    found = lines(res("aws_s3_bucket", "b"), res("aws_dynamodb_table", "t", billing_mode="PAY_PER_REQUEST"))
    assert found["aws_s3_bucket.b"] == (0.0, "billed by gigabytes stored and requests", True)
    assert found["aws_dynamodb_table.t"][0] == 0.0 and found["aws_dynamodb_table.t"][2]


def test_an_unknown_type_or_size_is_left_out_never_guessed() -> None:
    found = lines(
        res("aws_iam_role", "r"),
        res("aws_db_instance", "big", instance_class="db.x99.huge", allocated_storage=10),
        res("aws_ecs_service", "orphan", task_definition="missing", desired_count=1),
    )
    assert found == {}


def test_the_adapter_publishes_the_catalog() -> None:
    resources = [res("aws_kms_key", "k")]
    adapter = AwsAdapter({"account": "111122223333", "region": "eu-west-1"})
    assert adapter.monthly_cost(resources) == monthly_cost(resources)
