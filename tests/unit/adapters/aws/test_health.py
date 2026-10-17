"""What an AWS outage takes down in the demo world (adapters/aws/health.py), and AWS Health's public feed."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from theseus.adapters.aws.adapter import AwsAdapter
from theseus.adapters.aws.health import read_status
from theseus.adapters.github.adapter import GithubAdapter
from theseus.adapters.python.adapter import PythonAdapter
from theseus.adapters.terraform.adapter import TerraformAdapter
from theseus.contracts.adapters import Adapters
from theseus.importer.build import build_rows
from theseus.importer.world import load_world

ROOT = Path(__file__).resolve().parents[4] / "fixtures" / "intern" / "base"


def outages():
    config = yaml.safe_load((ROOT / "theseus.yaml").read_text(encoding="utf-8"))
    adapters = Adapters(
        iac=TerraformAdapter(config), cloud=AwsAdapter(config), ci=GithubAdapter(), code=PythonAdapter()
    )
    plan = json.loads(ROOT.with_name("base.plan.json").read_text(encoding="utf-8"))
    world = load_world(ROOT, plan, adapters)
    return adapters.cloud.outages(world.resources, build_rows(world, {}, adapters))


def by(service: str) -> dict[str, str]:
    return {t.node: t.effect for t in outages().tags if t.service == service}


def test_every_lambda_goes_down_with_lambda_in_the_world_s_region() -> None:
    found = outages()
    lam = [t for t in found.tags if t.service == "lambda"]
    assert {t.node for t in lam} == {
        "workload:analytics-export",
        "workload:billing-api",
        "workload:billing-job",
        "workload:invoice-mailer",
        "workload:receipt-renderer",
        "workload:support-portal",
    }
    assert {(t.region, t.effect, t.provider) for t in lam} == {("eu-west-1", "down", "aws")}
    assert lam[0].address.startswith("aws_lambda_function.")


def test_ec2_degrades_fargate_services_and_databases_and_takes_down_nothing_here() -> None:
    ec2 = by("ec2")
    assert ec2["workload:orders-api"] == ec2["workload:orders-worker"] == "degraded"
    assert ec2["db:customer-db"] == "degraded"
    assert "down" not in ec2.values()  # no EC2 instance or EC2-backed ECS service in the demo world
    assert by("fargate") == {"workload:orders-api": "down", "workload:orders-worker": "down"}


def test_one_bucket_takes_down_each_of_its_locations_and_sts_every_role() -> None:
    s3 = by("s3")
    assert {"s3://demo-company-files/invoices/", "s3://demo-company-files/public/"} <= set(s3)
    assert len(by("sts")) == 14 and set(by("sts").values()) == {"down"}


def test_iam_is_global_and_only_degrades() -> None:
    iam = [t for t in outages().tags if t.service == "iam"]
    assert iam and {(t.region, t.effect) for t in iam} == {(None, "degraded")}


def test_the_terms_name_every_service_with_a_rule_and_the_regions() -> None:
    found = outages()
    services = {t.service for t in found.terms}
    assert {t.service for t in found.tags} <= services
    assert {"ec2", "lambda", "s3", "secretsmanager", "sts", "rds"} <= services
    assert "eu-west-1" in {r.code for r in found.regions}
    ec2 = next(t for t in found.terms if t.service == "ec2")
    assert ec2.name == "Amazon EC2" and "EC2" in ec2.aliases and "AWS" in ec2.provider_names


def test_the_feed_s_impacted_services_become_incidents_and_the_rest_is_skipped() -> None:
    feed = [
        {
            "service": "multipleservices-us-east-1",
            "summary": "Increased Error Rates",
            "status": "3",
            "impacted_services": {
                "ec2-us-east-1": {"service_name": "Amazon EC2", "current": "3"},
                "lambda-us-east-1": {"service_name": "AWS Lambda", "current": "2"},
                "lambda-us-east-1-dup": {"current": "3"},
                "cloudsearch-us-east-1": {"current": "3"},
                "s3-us-east-1": {"current": "1"},
            },
        },
        {"service": "rds-eu-west-1", "status": "2", "summary": "Elevated latency"},
        {"service": "ec2-us-east-1", "status": "2", "summary": "Second event"},
        "not an event",
    ]
    found = read_status(feed)
    assert [(i.service, i.region, i.severity) for i in found] == [
        ("ec2", "us-east-1", "down"),
        ("lambda", "us-east-1", "degraded"),
        ("rds", "eu-west-1", "degraded"),
    ]
    assert {i.source for i in found} == {"feed"} and found[0].title == "Increased Error Rates"
    assert read_status({"unexpected": True}) == [] and read_status("text") == []
