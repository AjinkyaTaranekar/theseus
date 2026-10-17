"""Monthly cost estimates for AWS resources at list price (issue O3).

On-demand prices in us-east-1, before tax, as AWS publishes them, for 730 hours a month. Only what the code
declares is counted: an instance's class, a service's task size and count, a database's storage. Anything
billed by use (requests, gigabytes stored or transferred) is listed at 0 and marked `usage_billed`. A type
missing from this table is left out, never guessed.
"""

from __future__ import annotations

import logging
from typing import Any

from theseus.contracts.adapters import IacResource
from theseus.contracts.posture import CostLine

log = logging.getLogger(__name__)

HOURS = 730

# Fargate, Linux on x86, per vCPU-hour and per GB-hour.
FARGATE_VCPU = 0.04048
FARGATE_GB = 0.004445

# RDS single-AZ instance prices per hour; Multi-AZ doubles the instance and the storage.
RDS_HOURLY = {
    "db.t3.micro": 0.017,
    "db.t3.small": 0.034,
    "db.t3.medium": 0.068,
    "db.t4g.micro": 0.016,
    "db.t4g.small": 0.032,
    "db.t4g.medium": 0.065,
    "db.t4g.large": 0.129,
    "db.m6g.large": 0.152,
    "db.m7g.large": 0.168,
    "db.r6g.large": 0.215,
    "db.r7g.large": 0.239,
}
RDS_STORAGE_GB = {"gp2": 0.115, "gp3": 0.115, "io1": 0.125, "standard": 0.10}

# EC2 Linux per hour.
EC2_HOURLY = {
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
    "t3.medium": 0.0416,
    "t4g.micro": 0.0084,
    "t4g.small": 0.0168,
    "t4g.medium": 0.0336,
    "m6i.large": 0.096,
    "m7g.large": 0.0816,
    "c6i.large": 0.085,
}

# A flat monthly price for one of these, whatever its settings.
FLAT = {
    "aws_kms_key": (1.00, "one customer managed key"),
    "aws_secretsmanager_secret": (0.40, "one secret"),
    "aws_route53_zone": (0.50, "one hosted zone"),
    "aws_nat_gateway": (0.045 * HOURS, "one NAT gateway, before data processed"),
    "aws_lb": (0.0225 * HOURS, "one load balancer, before capacity units"),
    "aws_alb": (0.0225 * HOURS, "one load balancer, before capacity units"),
    "aws_eip": (0.005 * HOURS, "one public IPv4 address"),
}

# Billed only by use: listed at 0, so the reader sees they were counted.
USAGE = {
    "aws_apigatewayv2_api": "requests",
    "aws_cloudwatch_event_rule": "events",
    "aws_cloudwatch_log_group": "gigabytes ingested and stored",
    "aws_ecr_repository": "gigabytes stored",
    "aws_lambda_function": "requests and duration",
    "aws_s3_bucket": "gigabytes stored and requests",
    "aws_sns_topic": "messages",
    "aws_sqs_queue": "requests",
}


def _line(r: IacResource, usd: float, basis: str, usage: bool = False) -> CostLine:
    return CostLine(
        address=r.address, type=r.type, monthly_usd=round(usd, 2), basis=basis, usage_billed=usage
    )


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ecs(service: IacResource, tasks: dict[str, IacResource]) -> CostLine | None:
    values = service.values
    if (values.get("launch_type") or "FARGATE") != "FARGATE":
        log.info("%s is not on Fargate; its instances are priced as EC2", service.address)
        return None
    task = tasks.get(str(values.get("task_definition") or ""))
    if task is None:
        log.info("%s: no task definition %r to size it", service.address, values.get("task_definition"))
        return None
    vcpu = _number(task.values.get("cpu")) / 1024
    gb = _number(task.values.get("memory")) / 1024
    count = int(_number(values.get("desired_count"), 1))
    usd = count * (vcpu * FARGATE_VCPU + gb * FARGATE_GB) * HOURS
    return _line(service, usd, f"{count} Fargate task(s) of {vcpu:g} vCPU and {gb:g} GB")


def _rds(db: IacResource) -> CostLine | None:
    values = db.values
    klass = str(values.get("instance_class") or "")
    hourly = RDS_HOURLY.get(klass)
    if hourly is None:
        log.info("%s: no list price for %r", db.address, klass)
        return None
    copies = 2 if values.get("multi_az") else 1
    storage = _number(values.get("allocated_storage"))
    per_gb = RDS_STORAGE_GB.get(str(values.get("storage_type") or "gp2"), RDS_STORAGE_GB["gp2"])
    usd = copies * (hourly * HOURS + storage * per_gb)
    az = ", Multi-AZ" if copies == 2 else ""
    return _line(db, usd, f"{klass}{az}, {storage:g} GB storage")


def _endpoint(r: IacResource) -> CostLine:
    if (r.values.get("vpc_endpoint_type") or "Gateway") == "Gateway":
        return _line(r, 0.0, "gateway endpoint: no hourly charge")
    zones = max(1, len(r.values.get("subnet_ids") or []))
    return _line(r, 0.01 * HOURS * zones, f"interface endpoint in {zones} zone(s), before data processed")


def _dynamodb(r: IacResource) -> CostLine:
    if (r.values.get("billing_mode") or "PROVISIONED") == "PAY_PER_REQUEST":
        return _line(r, 0.0, "on demand: billed by requests and storage", usage=True)
    reads, writes = _number(r.values.get("read_capacity")), _number(r.values.get("write_capacity"))
    usd = (reads * 0.00013 + writes * 0.00065) * HOURS
    return _line(r, usd, f"{reads:g} read and {writes:g} write capacity units")


def monthly_cost(resources: list[IacResource]) -> list[CostLine]:
    """One line per resource this table can price, sorted by address."""
    tasks = {
        str(r.values.get("family") or r.name): r for r in resources if r.type == "aws_ecs_task_definition"
    }
    lines: list[CostLine] = []
    for r in resources:
        line: CostLine | None
        if r.type in FLAT:
            usd, basis = FLAT[r.type]
            line = _line(r, usd, basis)
        elif r.type in USAGE:
            line = _line(r, 0.0, f"billed by {USAGE[r.type]}", usage=True)
        elif r.type == "aws_ecs_service":
            line = _ecs(r, tasks)
        elif r.type == "aws_db_instance":
            line = _rds(r)
        elif r.type == "aws_vpc_endpoint":
            line = _endpoint(r)
        elif r.type == "aws_dynamodb_table":
            line = _dynamodb(r)
        elif r.type == "aws_instance" and str(r.values.get("instance_type")) in EC2_HOURLY:
            klass = str(r.values["instance_type"])
            line = _line(r, EC2_HOURLY[klass] * HOURS, f"one {klass} instance")
        else:
            line = None
        if line is not None:
            lines.append(line)
    return sorted(lines, key=lambda line: line.address)
