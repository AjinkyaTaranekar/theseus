"""The export steps: scan orders, write and read the raw zone, aggregate, write the curated zone.

Raw files are JSON lines, one order per line, at `raw/orders/<day>.jsonl`. Curated files are CSV, one row per
currency, at `curated/daily_sales/<day>.csv`. A scan is acceptable here: it runs once a night on a table of a
few hundred thousand items, and it filters to one day server-side.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

import boto3

log = logging.getLogger(__name__)

ORDERS_TABLE = os.environ["ORDERS_TABLE"]
LAKE_BUCKET = os.environ["LAKE_BUCKET"]

_ddb = boto3.client("dynamodb")
_s3 = boto3.client("s3")


def dump_orders(day: date) -> list[dict[str, Any]]:
    """Every order created on `day`."""
    orders: list[dict[str, Any]] = []
    start_key: dict[str, Any] | None = None
    while True:
        page = _ddb.scan(
            TableName=ORDERS_TABLE,
            FilterExpression="begins_with(created_at, :day)",
            ExpressionAttributeValues={":day": {"S": day.isoformat()}},
            **({"ExclusiveStartKey": start_key} if start_key else {}),
        )
        for item in page.get("Items", []):
            orders.append({key: next(iter(value.values())) for key, value in item.items()})
        start_key = page.get("LastEvaluatedKey")
        if not start_key:
            return orders


def write_raw(day: date, orders: list[dict[str, Any]]) -> str:
    body = "".join(json.dumps(order, sort_keys=True) + "\n" for order in orders)
    _s3.put_object(Bucket=LAKE_BUCKET, Key=f"raw/orders/{day.isoformat()}.jsonl", Body=body.encode("utf-8"))
    return f"raw/orders/{day.isoformat()}.jsonl"


def read_raw(day: date) -> list[dict[str, Any]]:
    obj = _s3.get_object(Bucket=LAKE_BUCKET, Key=f"raw/orders/{day.isoformat()}.jsonl")
    return [json.loads(line) for line in obj["Body"].read().decode("utf-8").splitlines() if line]


def aggregate(rows: list[dict[str, Any]]) -> dict[str, tuple[int, Decimal]]:
    """Order count and revenue per currency. No customer IDs leave this function."""
    totals: dict[str, tuple[int, Decimal]] = defaultdict(lambda: (0, Decimal("0")))
    for row in rows:
        count, revenue = totals[row["currency"]]
        totals[row["currency"]] = (count + 1, revenue + Decimal(row["total"]))
    return dict(totals)


def write_curated(day: date, totals: dict[str, tuple[int, Decimal]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["day", "currency", "orders", "revenue"])
    for currency, (count, revenue) in sorted(totals.items()):
        writer.writerow([day.isoformat(), currency, count, f"{revenue:.2f}"])
    _s3.put_object(Bucket=LAKE_BUCKET, Key=f"curated/daily_sales/{day.isoformat()}.csv", Body=out.getvalue().encode())
    return f"curated/daily_sales/{day.isoformat()}.csv"
