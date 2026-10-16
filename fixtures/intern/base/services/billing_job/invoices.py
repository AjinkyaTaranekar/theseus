"""Invoices: find the orders to bill, render each as a PDF, and store it in company files.

PDFs go to `invoices/<order_id>.pdf` in the company-files bucket, which billing-api serves to customers and the
support team. The PDF is deliberately plain: one page, one table, no fonts beyond the PDF standard set.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from datetime import date
from typing import Any

import boto3

log = logging.getLogger(__name__)

ORDERS_TABLE = os.environ["ORDERS_TABLE"]
INVOICES_BUCKET = os.environ["INVOICES_BUCKET"]

_ddb = boto3.client("dynamodb")
_s3 = boto3.client("s3")


def fulfilled_orders(day: date) -> Iterator[dict[str, Any]]:
    """Orders fulfilled on `day`, oldest first, through the `by_status` index."""
    start_key: dict[str, Any] | None = None
    while True:
        page = _ddb.query(
            TableName=ORDERS_TABLE,
            IndexName="by_status",
            KeyConditionExpression="#s = :fulfilled AND begins_with(created_at, :day)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":fulfilled": {"S": "fulfilled"}, ":day": {"S": day.isoformat()}},
            **({"ExclusiveStartKey": start_key} if start_key else {}),
        )
        for item in page.get("Items", []):
            yield {
                "order_id": item["order_id"]["S"],
                "customer_id": item["customer_id"]["S"],
                "currency": item["currency"]["S"],
                "total": item["total"]["N"],
                "lines": json.loads(item["lines"]["S"]),
            }
        start_key = page.get("LastEvaluatedKey")
        if not start_key:
            return


def render(order: dict[str, Any]) -> bytes:
    """A one-page PDF invoice."""
    rows = [f"{line['quantity']} x {line['sku']} @ {line['unit_price']}" for line in order["lines"]]
    text = [f"Invoice {order['order_id']}", f"Customer {order['customer_id']}", *rows]
    text.append(f"Total {order['total']} {order['currency']}")
    stream = "BT /F1 11 Tf 72 760 Td 14 TL " + " ".join(f"({t}) '" for t in text) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = "".join(f"{i} 0 obj\n{obj}\nendobj\n" for i, obj in enumerate(objects, 1))
    return f"%PDF-1.4\n{body}trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\n%%EOF\n".encode("latin-1")


def store(order_id: str, pdf: bytes) -> str:
    """Store the invoice PDF. Returns its key."""
    key = f"invoices/{order_id}.pdf"
    _s3.put_object(Bucket=INVOICES_BUCKET, Key=f"invoices/{order_id}.pdf", Body=pdf, ContentType="application/pdf")
    log.info("stored %s (%d bytes)", key, len(pdf))
    return key
