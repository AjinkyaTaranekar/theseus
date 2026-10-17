"""Order storage in the `demo-orders` DynamoDB table.

Orders are stored as one item each, keyed by `order_id`. The `by_status` index (status, created_at) lets
billing-job find fulfilled orders without scanning the table.
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

ORDERS_TABLE = os.environ["ORDERS_TABLE"]

_ddb = boto3.client("dynamodb")


def _to_item(order: dict[str, Any]) -> dict[str, Any]:
    """An order as a DynamoDB item. Lines are kept as one JSON attribute; nothing queries inside them."""
    return {
        "order_id": {"S": order["order_id"]},
        "customer_id": {"S": order["customer_id"]},
        "status": {"S": order["status"]},
        "created_at": {"S": order["created_at"]},
        "currency": {"S": order["currency"]},
        "total": {"N": str(order["total"])},
        "lines": {"S": json.dumps(order["lines"], separators=(",", ":"))},
    }


def _from_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_id": item["order_id"]["S"],
        "customer_id": item["customer_id"]["S"],
        "status": item["status"]["S"],
        "created_at": item["created_at"]["S"],
        "currency": item["currency"]["S"],
        "total": Decimal(item["total"]["N"]),
        "lines": json.loads(item["lines"]["S"]),
    }


def put_order(order: dict[str, Any]) -> None:
    """Store a new order. Refuses to overwrite an existing one with the same ID."""
    try:
        _ddb.put_item(
            TableName=ORDERS_TABLE,
            Item=_to_item(order),
            ConditionExpression="attribute_not_exists(order_id)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            log.warning("order %s already exists; not overwriting", order["order_id"])
            raise ValueError(f"duplicate order {order['order_id']}") from e
        raise


def get_order(order_id: str) -> dict[str, Any] | None:
    """The order, or None if there is no such order."""
    found = _ddb.get_item(TableName=ORDERS_TABLE, Key={"order_id": {"S": order_id}}, ConsistentRead=True)
    item = found.get("Item")
    return _from_item(item) if item else None
