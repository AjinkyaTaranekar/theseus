"""billing-api: invoices and customer records, behind the internal API Gateway.

orders-api asks it whether a customer may order; support-portal asks it for invoices and customer details. It is
the only service that talks to the customer database. Routes come from API Gateway's HTTP API (payload v2).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from billing_api import db, queries

log = logging.getLogger()
log.setLevel(logging.INFO)

Route = Callable[[Any, str], dict[str, Any] | None]

ROUTES: list[tuple[re.Pattern[str], Route]] = [
    (re.compile(r"^/invoices/(?P<id>[\w-]+)$"), queries.invoice),
    (re.compile(r"^/customers/(?P<id>[\w-]+)/status$"), queries.customer_status),
    (re.compile(r"^/customers/(?P<id>[\w-]+)$"), queries.customer),
]


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]
    if method != "GET":
        return _response(405, {"error": "method not allowed"})

    for pattern, route in ROUTES:
        match = pattern.match(path)
        if match is None:
            continue
        with db.connect() as conn:
            found = route(conn, match["id"])
        if found is None:
            return _response(404, {"error": "not found"})
        return _response(200, found)

    log.info("no route for %s %s", method, path)
    return _response(404, {"error": "no such route"})
