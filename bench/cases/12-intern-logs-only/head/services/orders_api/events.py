"""`order.created` events on the order-events queue.

orders-worker consumes them and fulfils the order. A message that fails five times moves to the dead-letter
queue, where the on-call engineer replays it from the console.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

import boto3

log = logging.getLogger(__name__)

ORDER_EVENTS_QUEUE_URL = os.environ["ORDER_EVENTS_QUEUE_URL"]
EVENT_VERSION = "1"

_sqs = boto3.client("sqs")


def _envelope(event_type: str, payload: dict[str, str]) -> str:
    """The message body every consumer of this queue expects: type, version, time and payload."""
    return json.dumps(
        {
            "type": event_type,
            "version": EVENT_VERSION,
            "occurred_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "payload": payload,
        },
        separators=(",", ":"),
    )


def publish_order_created(order_id: str, customer_id: str) -> str:
    """Queue an `order.created` event. Returns the SQS message ID."""
    sent = _sqs.send_message(
        QueueUrl=ORDER_EVENTS_QUEUE_URL,
        MessageBody=_envelope("order.created", {"order_id": order_id, "customer_id": customer_id}),
        MessageAttributes={
            "type": {"DataType": "String", "StringValue": "order.created"},
            "version": {"DataType": "String", "StringValue": EVENT_VERSION},
        },
    )
    log.info("queued order.created for %s as %s", order_id, sent["MessageId"])
    return sent["MessageId"]
