"""support-portal: the support team's internal tool.

Support engineers open a ticket and see the customer, their recent order and its invoice on one page, and confirm
refunds. Everything it shows comes from billing-api and orders-api; it has no data store of its own.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from support_portal import export, views

log = logging.getLogger()
log.setLevel(logging.INFO)

TICKET_CONTEXT = re.compile(r"^/tickets/(?P<id>[\w-]+)/context$")
REFUND_PAGE = re.compile(r"^/refunds/(?P<id>[\w-]+)$")
ADMIN_EXPORT = "/admin/export"


def _json(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


def _html(status: int, page: str) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"content-type": "text/html; charset=utf-8"}, "body": page}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]
    params = event.get("queryStringParameters") or {}
    if method != "GET":
        return _json(405, {"error": "method not allowed"})

    if match := TICKET_CONTEXT.match(path):
        found = views.ticket_context(match["id"], params.get("customer_id"), params.get("order_id"))
        return _json(200, found) if found else _json(404, {"error": "not found"})

    if match := REFUND_PAGE.match(path):
        return _html(200, views.refund_page(match["id"], params.get("amount", ""), params.get("currency", "EUR")))

    if path == ADMIN_EXPORT:
        return _json(200, {"customers": export.export_customers()})

    log.info("no route for %s %s", method, path)
    return _json(404, {"error": "no such route"})
