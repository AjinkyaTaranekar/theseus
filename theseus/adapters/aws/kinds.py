"""AWS resource kinds and the Terraform resource types the AWS adapter models (04-engine.md section 1).

Data resources and workloads come from the catalog (catalog.yaml); IAM resources are structural, and the
adapter reads them to build principals and their edges.
"""

from __future__ import annotations

from typing import Final

from theseus.adapters.aws.catalog import load_catalog
from theseus.contracts.schema import location_id

PROVIDER: Final = "aws"

# Resource kind (the node ID prefix) -> its neutral category. The engine only ever sees the category.
RESOURCE_KINDS: Final[dict[str, str]] = {d.kind: d.category for d in load_catalog().data}

STRUCTURAL_TYPES: Final = frozenset(
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
        "aws_s3_bucket_policy",
    }
)

# Every other resource type is skipped and counted by type in the result's coverage.
MODELED_TYPES: Final = STRUCTURAL_TYPES | load_catalog().types


def s3_id(bucket: str, prefix: str = "") -> str:
    """The node ID of a location in a bucket: `s3://<bucket>/<prefix>`, the prefix possibly empty."""
    return location_id("s3", f"{bucket}/{prefix}")
