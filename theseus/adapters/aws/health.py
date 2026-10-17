"""What an AWS outage takes down, and AWS Health's public status feed read as incidents.

Each rule says which Terraform type an AWS service runs or serves, and whether an outage of that service
takes it down or only degrades it. The service codes are the ones AWS Health uses
(https://health.aws.amazon.com/health/status), so a feed event and a picked service name the same thing.
A resource's region is the world's (theseus.yaml); IAM is global.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from theseus.contracts.adapters import IacResource
from theseus.contracts.incident import Effect, Incident, OutageMap, RegionTerm, ServiceTag, ServiceTerm
from theseus.contracts.result import GraphRows

log = logging.getLogger(__name__)

PROVIDER = "aws"
PROVIDER_NAMES = ["AWS", "Amazon Web Services", "Amazon"]


def _fargate(r: IacResource) -> bool:
    return (r.values.get("launch_type") or "FARGATE") == "FARGATE"


def _in_vpc(r: IacResource) -> bool:
    return bool(r.values.get("vpc_config"))


def _always(r: IacResource) -> bool:
    return True


# (service, Terraform type, effect, why, when): `why` completes "<node> ...".
Rule = tuple[str, str, Effect, str, Callable[[IacResource], bool]]
RULES: list[Rule] = [
    ("lambda", "aws_lambda_function", "down", "runs on Lambda", _always),
    ("ec2", "aws_instance", "down", "is an EC2 instance", _always),
    ("ec2", "aws_ecs_service", "down", "runs its tasks on EC2 instances", lambda r: not _fargate(r)),
    (
        "ec2",
        "aws_ecs_service",
        "degraded",
        "runs on Fargate, which runs on EC2 capacity: running tasks carry on, new ones may not start",
        _fargate,
    ),
    ("ec2", "aws_lambda_function", "degraded", "reaches its VPC through network interfaces on EC2", _in_vpc),
    (
        "ec2",
        "aws_db_instance",
        "degraded",
        "runs on EC2 instances: a restart or failover may not come back",
        _always,
    ),
    ("ecs", "aws_ecs_service", "down", "is an ECS service", _always),
    ("fargate", "aws_ecs_service", "down", "runs on Fargate", _fargate),
    ("ecr", "aws_ecs_service", "degraded", "pulls its image from ECR: new tasks cannot start", _always),
    ("rds", "aws_db_instance", "down", "is an RDS database", _always),
    ("s3", "aws_s3_bucket", "down", "is stored in S3", _always),
    ("secretsmanager", "aws_secretsmanager_secret", "down", "is kept in Secrets Manager", _always),
    (
        "kms",
        "aws_secretsmanager_secret",
        "down",
        "is encrypted with a KMS key: reading it needs KMS",
        _always,
    ),
    ("ssm", "aws_ssm_parameter", "down", "is a Systems Manager parameter", _always),
    ("dynamodb", "aws_dynamodb_table", "down", "is a DynamoDB table", _always),
    ("sqs", "aws_sqs_queue", "down", "is an SQS queue", _always),
    ("sns", "aws_sns_topic", "down", "is an SNS topic", _always),
    ("cloudwatch", "aws_cloudwatch_log_group", "down", "is a CloudWatch Logs group", _always),
    ("kinesis", "aws_kinesis_stream", "down", "is a Kinesis stream", _always),
    ("es", "aws_opensearch_domain", "down", "is an OpenSearch domain", _always),
    ("apprunner", "aws_apprunner_service", "down", "runs on App Runner", _always),
    ("codebuild", "aws_codebuild_project", "down", "runs on CodeBuild", _always),
    ("states", "aws_sfn_state_machine", "down", "runs on Step Functions", _always),
    ("glue", "aws_glue_job", "down", "runs on Glue", _always),
    (
        "sts",
        "aws_iam_role",
        "down",
        "is a role: switching into it needs STS to issue credentials",
        _always,
    ),
    (
        "iam",
        "aws_iam_role",
        "degraded",
        "cannot be changed while IAM is out; its grants keep working",
        _always,
    ),
    (
        "iam",
        "aws_iam_user",
        "degraded",
        "cannot be changed while IAM is out; its grants keep working",
        _always,
    ),
    (
        "iam",
        "aws_iam_group",
        "degraded",
        "cannot be changed while IAM is out; its grants keep working",
        _always,
    ),
]
GLOBAL = frozenset({"iam"})

SERVICES: dict[str, tuple[str, list[str]]] = {
    "apprunner": ("AWS App Runner", ["App Runner"]),
    "cloudwatch": ("Amazon CloudWatch", ["CloudWatch", "CloudWatch Logs"]),
    "codebuild": ("AWS CodeBuild", ["CodeBuild"]),
    "dynamodb": ("Amazon DynamoDB", ["DynamoDB", "Dynamo"]),
    "ec2": ("Amazon EC2", ["EC2", "Elastic Compute Cloud"]),
    "ecr": ("Amazon ECR", ["ECR", "Elastic Container Registry"]),
    "ecs": ("Amazon ECS", ["ECS", "Elastic Container Service"]),
    "es": ("Amazon OpenSearch Service", ["OpenSearch", "Elasticsearch"]),
    "fargate": ("AWS Fargate", ["Fargate"]),
    "glue": ("AWS Glue", ["Glue"]),
    "iam": ("AWS IAM", ["IAM", "Identity and Access Management"]),
    "kinesis": ("Amazon Kinesis", ["Kinesis"]),
    "kms": ("AWS KMS", ["KMS", "Key Management Service"]),
    "lambda": ("AWS Lambda", ["Lambda"]),
    "rds": ("Amazon RDS", ["RDS", "Relational Database Service", "Aurora"]),
    "s3": ("Amazon S3", ["S3", "Simple Storage Service"]),
    "secretsmanager": ("AWS Secrets Manager", ["Secrets Manager"]),
    "sns": ("Amazon SNS", ["SNS", "Simple Notification Service"]),
    "sqs": ("Amazon SQS", ["SQS", "Simple Queue Service"]),
    "ssm": ("AWS Systems Manager", ["Systems Manager", "Parameter Store", "SSM"]),
    "states": ("AWS Step Functions", ["Step Functions"]),
    "sts": ("AWS STS", ["STS", "Security Token Service", "AssumeRole"]),
}

REGIONS: dict[str, tuple[str, list[str]]] = {
    "af-south-1": ("Africa (Cape Town)", ["Cape Town"]),
    "ap-east-1": ("Asia Pacific (Hong Kong)", ["Hong Kong"]),
    "ap-northeast-1": ("Asia Pacific (Tokyo)", ["Tokyo"]),
    "ap-northeast-2": ("Asia Pacific (Seoul)", ["Seoul"]),
    "ap-south-1": ("Asia Pacific (Mumbai)", ["Mumbai"]),
    "ap-southeast-1": ("Asia Pacific (Singapore)", ["Singapore"]),
    "ap-southeast-2": ("Asia Pacific (Sydney)", ["Sydney"]),
    "ca-central-1": ("Canada (Central)", ["Montreal"]),
    "eu-central-1": ("Europe (Frankfurt)", ["Frankfurt"]),
    "eu-north-1": ("Europe (Stockholm)", ["Stockholm"]),
    "eu-south-1": ("Europe (Milan)", ["Milan"]),
    "eu-west-1": ("Europe (Ireland)", ["Ireland", "Dublin"]),
    "eu-west-2": ("Europe (London)", ["London"]),
    "eu-west-3": ("Europe (Paris)", ["Paris"]),
    "me-central-1": ("Middle East (UAE)", ["UAE"]),
    "me-south-1": ("Middle East (Bahrain)", ["Bahrain"]),
    "sa-east-1": ("South America (Sao Paulo)", ["Sao Paulo", "São Paulo"]),
    "us-east-1": ("US East (N. Virginia)", ["N. Virginia", "Northern Virginia", "Virginia"]),
    "us-east-2": ("US East (Ohio)", ["Ohio"]),
    "us-west-1": ("US West (N. California)", ["N. California", "Northern California"]),
    "us-west-2": ("US West (Oregon)", ["Oregon"]),
}


def terms() -> tuple[list[ServiceTerm], list[RegionTerm]]:
    """Every service an AWS incident can name, and every region, sorted."""
    services = [
        ServiceTerm(
            provider=PROVIDER, service=code, name=name, aliases=aliases, provider_names=PROVIDER_NAMES
        )
        for code, (name, aliases) in sorted(SERVICES.items())
    ]
    regions = [RegionTerm(code=c, name=n, aliases=a) for c, (n, a) in sorted(REGIONS.items())]
    return services, regions


def outages(resources: list[IacResource], rows: GraphRows, region: str) -> OutageMap:
    """A tag for every node an AWS service runs or serves, by the IaC address its node came from."""
    by_address: dict[str, list[str]] = {}
    for n in rows.nodes:
        address = n.props.get("address")
        if isinstance(address, str):
            by_address.setdefault(address, []).append(n.id)
    tags: list[ServiceTag] = []
    for r in resources:
        for service, type_, effect, why, when in RULES:
            if r.type != type_ or not when(r):
                continue
            for node in by_address.get(r.address, []):
                tags.append(
                    ServiceTag(
                        node=node,
                        provider=PROVIDER,
                        service=service,
                        region=None if service in GLOBAL else region,
                        effect=effect,
                        why=why,
                        address=r.address,
                    )
                )
    services, regions = terms()
    return OutageMap(
        tags=sorted(tags, key=lambda t: (t.node, t.service, t.effect)), terms=services, regions=regions
    )


# AWS Health: 0 operating normally, 1 informational, 2 degraded, 3 disrupted.
STATUS: dict[str, Effect] = {"2": "degraded", "3": "down"}
KEY = re.compile(r"^(?P<service>[a-z0-9]+)-(?P<region>[a-z]{2}(?:-gov)?-[a-z]+-\d)$")


def _events(feed: Any) -> list[dict[str, Any]]:
    if isinstance(feed, dict):
        feed = feed.get("events", feed.get("current", []))
    return [e for e in feed if isinstance(e, dict)] if isinstance(feed, list) else []


def read_status(feed: Any) -> list[Incident]:
    """An incident for each service the feed's current events name as degraded or disrupted, in a region
    and a service Theseus knows, sorted and without repeats. Anything else in the feed is skipped."""
    found: dict[tuple[str, str], Incident] = {}
    for event in _events(feed):
        impacted = event.get("impacted_services")
        entries = (
            [(k, v.get("current")) for k, v in impacted.items() if isinstance(v, dict)]
            if isinstance(impacted, dict) and impacted
            else [(event.get("service"), event.get("status"))]
        )
        title = " ".join(str(event.get("summary") or event.get("service_name") or "").split())[:200]
        for key, status in entries:
            match = KEY.match(str(key or ""))
            effect = STATUS.get(str(status))
            if match is None or effect is None or match["service"] not in SERVICES:
                continue
            service, region = match["service"], match["region"]
            old = found.get((service, region))
            if old is None or (old.severity == "degraded" and effect == "down"):
                found[(service, region)] = Incident(
                    provider=PROVIDER,
                    service=service,
                    region=region,
                    severity=effect,
                    title=title or SERVICES[service][0],
                    source="feed",
                    url="https://health.aws.amazon.com/health/status",
                )
    log.info("AWS Health: %d incident(s) in services Theseus maps", len(found))
    return [found[k] for k in sorted(found)]
