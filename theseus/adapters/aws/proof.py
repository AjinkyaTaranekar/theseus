"""Where AWS publishes each price, and how to confirm with AWS's own telemetry that a resource is idle before
removing it: the proof a reader can check for a saving, outside Theseus's graph.

Every URL is AWS's official pricing page for the service. Every command is a read-only AWS CLI call, except
the retirement steps, which are listed for a person to run after the check, never run by Theseus. A command
names the resource as the plan declares it; one whose name is unknown at plan time is left out.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from theseus.contracts.adapters import IacResource

CALCULATOR = "https://calculator.aws/"

PRICING = {
    "aws_apigatewayv2_api": "https://aws.amazon.com/api-gateway/pricing/",
    "aws_cloudwatch_event_rule": "https://aws.amazon.com/eventbridge/pricing/",
    "aws_cloudwatch_log_group": "https://aws.amazon.com/cloudwatch/pricing/",
    "aws_db_instance": "https://aws.amazon.com/rds/pricing/",
    "aws_dynamodb_table": "https://aws.amazon.com/dynamodb/pricing/",
    "aws_ecr_repository": "https://aws.amazon.com/ecr/pricing/",
    "aws_ecs_service": "https://aws.amazon.com/fargate/pricing/",
    "aws_eip": "https://aws.amazon.com/vpc/pricing/",
    "aws_instance": "https://aws.amazon.com/ec2/pricing/on-demand/",
    "aws_kms_key": "https://aws.amazon.com/kms/pricing/",
    "aws_lambda_function": "https://aws.amazon.com/lambda/pricing/",
    "aws_lb": "https://aws.amazon.com/elasticloadbalancing/pricing/",
    "aws_alb": "https://aws.amazon.com/elasticloadbalancing/pricing/",
    "aws_nat_gateway": "https://aws.amazon.com/vpc/pricing/",
    "aws_route53_zone": "https://aws.amazon.com/route53/pricing/",
    "aws_s3_bucket": "https://aws.amazon.com/s3/pricing/",
    "aws_secretsmanager_secret": "https://aws.amazon.com/secrets-manager/pricing/",
    "aws_sns_topic": "https://aws.amazon.com/sns/pricing/",
    "aws_sqs_queue": "https://aws.amazon.com/sqs/pricing/",
    "aws_vpc_endpoint": "https://aws.amazon.com/privatelink/pricing/",
}
RDS_ENGINES = {
    "postgres": "https://aws.amazon.com/rds/postgresql/pricing/",
    "mysql": "https://aws.amazon.com/rds/mysql/pricing/",
    "mariadb": "https://aws.amazon.com/rds/mariadb/pricing/",
}

# The last 30 days, in the form the AWS CLI takes (GNU date, as in CloudShell).
SINCE = (
    "--start-time $(date -u -d '30 days ago' +%Y-%m-%dT%H:%M:%SZ) --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ)"
)


def pricing_url(r: IacResource) -> str | None:
    """AWS's pricing page for the resource's service; the engine's own page for a database."""
    if r.type == "aws_db_instance":
        return RDS_ENGINES.get(str(r.values.get("engine") or ""), PRICING["aws_db_instance"])
    return PRICING.get(r.type)


def _metric(
    namespace: str, metric: str, dimension: str, value: str, region: str, stat: str = "Maximum"
) -> str:
    return (
        f"aws cloudwatch get-metric-statistics --namespace {namespace} --metric-name {metric} "
        f"--dimensions Name={dimension},Value={value} --statistics {stat} --period 86400 {SINCE} "
        f"--region {region}"
    )


# Each type: (the check, what an idle resource shows, the steps to retire it). `name` is its plan name.
Check = tuple[str, str, list[str]]


def _rds(r: IacResource, region: str) -> Check | None:
    name = r.values.get("identifier")
    if not isinstance(name, str):
        return None
    return (
        _metric("AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", name, region),
        "Every daily Maximum is 0: nothing connected to it in 30 days.",
        [
            f"aws rds create-db-snapshot --db-instance-identifier {name} "
            f"--db-snapshot-identifier {name}-final --region {region}",
            f"aws rds stop-db-instance --db-instance-identifier {name} --region {region}  "
            "# stops the instance charge; AWS starts a stopped instance again after 7 days",
            f"Remove `{r.address}` from Terraform once the snapshot exists, and apply.",
        ],
    )


def _lambda(r: IacResource, region: str) -> Check | None:
    name = r.values.get("function_name")
    if not isinstance(name, str):
        return None
    return (
        _metric("AWS/Lambda", "Invocations", "FunctionName", name, region, "Sum"),
        "Every daily Sum is 0: it never ran in 30 days.",
        [f"Remove `{r.address}` from Terraform and apply."],
    )


def _dynamodb(r: IacResource, region: str) -> Check | None:
    name = r.values.get("name")
    if not isinstance(name, str):
        return None
    return (
        _metric("AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", name, region, "Sum"),
        "Every daily Sum is 0: nothing read it in 30 days. Check ConsumedWriteCapacityUnits the same way.",
        [
            f"aws dynamodb create-backup --table-name {name} --backup-name {name}-final --region {region}",
            f"Remove `{r.address}` from Terraform once the backup exists, and apply.",
        ],
    )


def _secret(r: IacResource, region: str) -> Check | None:
    name = r.values.get("name")
    if not isinstance(name, str):
        return None
    return (
        f"aws secretsmanager describe-secret --secret-id {name} --query LastAccessedDate --region {region}",
        "LastAccessedDate is empty or older than 30 days: nothing read it since.",
        [
            f"aws secretsmanager delete-secret --secret-id {name} --recovery-window-in-days 30 "
            f"--region {region}  # recoverable for 30 days",
            f"Remove `{r.address}` from Terraform and apply.",
        ],
    )


def _queue(r: IacResource, region: str) -> Check | None:
    name = r.values.get("name")
    if not isinstance(name, str):
        return None
    return (
        _metric("AWS/SQS", "NumberOfMessagesReceived", "QueueName", name, region, "Sum"),
        "Every daily Sum is 0: nothing read from it in 30 days.",
        [f"Remove `{r.address}` from Terraform and apply."],
    )


def _topic(r: IacResource, region: str) -> Check | None:
    name = r.values.get("name")
    if not isinstance(name, str):
        return None
    return (
        _metric("AWS/SNS", "NumberOfMessagesPublished", "TopicName", name, region, "Sum"),
        "Every daily Sum is 0: nothing published to it in 30 days.",
        [f"Remove `{r.address}` from Terraform and apply."],
    )


def _logs(r: IacResource, region: str) -> Check | None:
    name = r.values.get("name")
    if not isinstance(name, str):
        return None
    return (
        f"aws logs describe-log-streams --log-group-name {name} --order-by LastEventTime --descending "
        f"--max-items 1 --query 'logStreams[0].lastEventTimestamp' --region {region}",
        "The last event is more than 30 days old, or there is none.",
        [f"Remove `{r.address}` from Terraform and apply."],
    )


def _bucket(r: IacResource, region: str) -> Check | None:
    name = r.values.get("bucket")
    if not isinstance(name, str):
        return None
    return (
        f"aws s3 ls s3://{name} --recursive --summarize --region {region} | tail -2",
        "Shows what it holds. Reads are visible only with S3 server access logs or CloudTrail data events.",
        [
            f"aws s3 sync s3://{name} s3://<archive-bucket>/{name}/  # keep a copy first",
            f"Remove `{r.address}` from Terraform and apply.",
        ],
    )


CHECKS: dict[str, Callable[[IacResource, str], Check | None]] = {
    "aws_db_instance": _rds,
    "aws_lambda_function": _lambda,
    "aws_dynamodb_table": _dynamodb,
    "aws_secretsmanager_secret": _secret,
    "aws_sqs_queue": _queue,
    "aws_sns_topic": _topic,
    "aws_cloudwatch_log_group": _logs,
    "aws_s3_bucket": _bucket,
}


def proof_fields(r: IacResource, region: str) -> dict[str, Any]:
    """The CostLine fields that let a reader check a price and an idle resource: the pricing page, the
    read-only check, what idle looks like, and the steps to retire it."""
    fields: dict[str, Any] = {"pricing_url": pricing_url(r)}
    check = CHECKS.get(r.type)
    found = check(r, region) if check is not None else None
    if found is not None:
        fields |= {"idle_check": found[0], "idle_expect": found[1], "retire": found[2]}
    return fields
