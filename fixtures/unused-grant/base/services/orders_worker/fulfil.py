"""Fulfilment: reserve stock for an order and mark it fulfilled.

Stock lives in the warehouse system, which we do not call yet: `reserve_stock` checks the order against the
per-SKU limits the warehouse gave us. The status change is conditional, so a redelivered event cannot fulfil an
order twice.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

ORDERS_TABLE = os.environ["ORDERS_TABLE"]
MAX_PER_SKU = 20

_ddb = boto3.client("dynamodb")


class OutOfStock(Exception):
    pass


def reserve_stock(lines: list[dict]) -> None:
    """Check each line against the warehouse's per-SKU limit. Raises OutOfStock."""
    for line in lines:
        if line["quantity"] > MAX_PER_SKU:
            raise OutOfStock(f"{line['sku']}: {line['quantity']} over the limit of {MAX_PER_SKU}")


def handle(order_id: str) -> None:
    """Fulfil one pending order. An order that is already fulfilled is left alone."""
    found = _ddb.get_item(TableName=ORDERS_TABLE, Key={"order_id": {"S": order_id}}, ConsistentRead=True)
    item = found.get("Item")
    if item is None:
        log.warning("order %s does not exist; dropping the event", order_id)
        return
    if item["status"]["S"] != "pending":
        log.info("order %s is %s; nothing to do", order_id, item["status"]["S"])
        return

    reserve_stock(json.loads(item["lines"]["S"]))
    try:
        _ddb.update_item(
            TableName=ORDERS_TABLE,
            Key={"order_id": {"S": order_id}},
            UpdateExpression="SET #s = :fulfilled, fulfilled_at = :now",
            ConditionExpression="#s = :pending",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":fulfilled": {"S": "fulfilled"},
                ":pending": {"S": "pending"},
                ":now": {"S": datetime.now(UTC).isoformat(timespec="seconds")},
            },
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            log.info("order %s was fulfilled by another worker", order_id)
            return
        raise
    log.info("order %s fulfilled", order_id)
