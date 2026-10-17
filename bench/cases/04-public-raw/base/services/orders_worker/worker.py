"""orders-worker: fulfils orders as their `order.created` events arrive.

Long-polls the order-events queue, hands each event to `fulfil.handle`, and deletes the message only after the
order is fulfilled. A message that keeps failing is retried by SQS and, after five tries, moves to the
dead-letter queue. Runs as an ECS service; ECS sends SIGTERM on deploy, and we finish the current batch first.
"""

from __future__ import annotations

import json
import logging
import os
import signal
from types import FrameType

import boto3

from orders_worker import fulfil

log = logging.getLogger("orders_worker")

ORDER_EVENTS_QUEUE_URL = os.environ["ORDER_EVENTS_QUEUE_URL"]
WAIT_SECONDS = 20
BATCH_SIZE = 10

_sqs = boto3.client("sqs")
_stopping = False


def _stop(signum: int, frame: FrameType | None) -> None:
    global _stopping
    log.info("signal %s: finishing this batch, then stopping", signum)
    _stopping = True


def _process(message: dict) -> bool:
    """Handle one message. Returns whether it can be deleted."""
    try:
        event = json.loads(message["Body"])
    except json.JSONDecodeError:
        log.error("message %s is not JSON; leaving it for the dead-letter queue", message["MessageId"])
        return False
    if event.get("type") != "order.created":
        log.info("ignoring %s event %s", event.get("type"), message["MessageId"])
        return True
    try:
        fulfil.handle(event["payload"]["order_id"])
    except Exception:
        log.exception("could not fulfil order from message %s; SQS will retry it", message["MessageId"])
        return False
    return True


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    log.info("polling %s", ORDER_EVENTS_QUEUE_URL)
    while not _stopping:
        received = _sqs.receive_message(
            QueueUrl=ORDER_EVENTS_QUEUE_URL,
            MaxNumberOfMessages=BATCH_SIZE,
            WaitTimeSeconds=WAIT_SECONDS,
            MessageAttributeNames=["All"],
        )
        for message in received.get("Messages", []):
            if _process(message):
                _sqs.delete_message(QueueUrl=ORDER_EVENTS_QUEUE_URL, ReceiptHandle=message["ReceiptHandle"])
    log.info("stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    main()
