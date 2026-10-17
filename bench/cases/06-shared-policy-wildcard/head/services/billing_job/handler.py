"""billing-job: the nightly invoice run.

EventBridge starts it at 02:00 UTC. For every order fulfilled the day before: render the invoice, store the PDF,
charge the card, and announce `invoice.created` so finance tooling can pick it up. One failed order is logged
and skipped; it is picked up again the next night, because its status stays `fulfilled`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

import boto3

from billing_job import invoices, payments

log = logging.getLogger()
log.setLevel(logging.INFO)

INVOICE_TOPIC_ARN = os.environ["INVOICE_TOPIC_ARN"]

_sns = boto3.client("sns")


def _billing_day(event: dict[str, Any]) -> date:
    """The day to bill: the event's `day` when re-run by hand, else yesterday in UTC."""
    if "day" in event:
        return date.fromisoformat(event["day"])
    return (datetime.now(UTC) - timedelta(days=1)).date()


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    day = _billing_day(event)
    billed, failed = 0, 0
    for order in invoices.fulfilled_orders(day):
        order_id = order["order_id"]
        try:
            pdf = invoices.render(order)
            key = invoices.store(order_id, pdf)
            charge_id = payments.charge(order)
        except Exception:
            log.exception("could not bill order %s; it will be retried tomorrow", order_id)
            failed += 1
            continue
        _sns.publish(
            TopicArn=INVOICE_TOPIC_ARN,
            Subject="invoice.created",
            Message=json.dumps({"order_id": order_id, "invoice_key": key, "charge_id": charge_id}),
        )
        billed += 1
    log.info("billing run for %s: %d billed, %d failed", day, billed, failed)
    return {"billed": billed, "failed": failed}
