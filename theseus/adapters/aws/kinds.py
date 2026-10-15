"""AWS resource kinds and the Terraform resource types the AWS adapter models (04-engine.md section 1)."""

from __future__ import annotations

from typing import Final

from theseus.contracts.schema import location_id

PROVIDER: Final = "aws"

# Resource kind (the node ID prefix) -> its neutral category. The engine only ever sees the category.
RESOURCE_KINDS: Final[dict[str, str]] = {
    "s3": "object_store",
    "secret": "secret",
    "db": "database",
    "dynamodb": "table",
}

# Every other resource type is skipped and counted by type in the result's coverage.
MODELED_TYPES: Final = frozenset(
    {
        "aws_iam_user",
        "aws_iam_group",
        "aws_iam_user_group_membership",
        "aws_iam_user_policy",
        "aws_iam_group_policy",
        "aws_iam_role",
        "aws_iam_role_policy",
        "aws_iam_policy",
        "aws_iam_user_policy_attachment",
        "aws_iam_group_policy_attachment",
        "aws_iam_role_policy_attachment",
        "aws_iam_openid_connect_provider",
        "aws_s3_bucket",
        "aws_s3_bucket_policy",
        "aws_secretsmanager_secret",
        "aws_db_instance",
        "aws_dynamodb_table",
        "aws_lambda_function",
        "aws_ecs_task_definition",
        "aws_ecs_service",
    }
)


def s3_id(bucket: str, prefix: str = "") -> str:
    """The node ID of a location in a bucket: `s3://<bucket>/<prefix>`, the prefix possibly empty."""
    return location_id("s3", f"{bucket}/{prefix}")
