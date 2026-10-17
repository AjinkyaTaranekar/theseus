"""receipt-renderer: turns a stored invoice into a short receipt for the support portal.

It reads the invoice PDF's metadata from company files and the mail footer settings, and returns the receipt
text. It never writes.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

INVOICES_BUCKET = os.environ["INVOICES_BUCKET"]
SMTP_SECRET = os.environ["SMTP_SECRET"]

CURRENCY_SIGNS = {"EUR": "€", "GBP": "£", "USD": "$"}

_s3 = boto3.client("s3")
_sm = boto3.client("secretsmanager")


def _amount(metadata: dict[str, str]) -> str:
    """The invoice total as a customer reads it, such as €12.40; empty when the PDF carries no total."""
    total, currency = metadata.get("total", ""), metadata.get("currency", "EUR")
    if not total:
        return ""
    sign = CURRENCY_SIGNS.get(currency)
    return f"{sign}{total}" if sign else f"{total} {currency}"


def _footer() -> str:
    settings = json.loads(_sm.get_secret_value(SecretId=SMTP_SECRET)["SecretString"])
    return settings.get("footer", "")


def handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    order_id = event["order_id"]
    head = _s3.get_object(Bucket=INVOICES_BUCKET, Key=f"invoices/{order_id}.pdf")
    amount = _amount(head.get("Metadata", {}))
    lines = [f"Order {order_id}", f"Total: {amount}" if amount else "Total: see the attached invoice", _footer()]
    log.info("rendered the receipt for %s", order_id)
    return {"receipt": "\n".join(line for line in lines if line)}
