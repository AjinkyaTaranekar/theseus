"""HTTP clients for the services support-portal reads from.

Both services are internal (`*.internal.demo.test`). support-portal has no credentials of its own for any data
store: everything goes through billing-api and orders-api, which apply their own checks.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

BILLING_API_URL = os.environ["BILLING_API_URL"]
ORDERS_API_URL = os.environ["ORDERS_API_URL"]
TIMEOUT_SECONDS = 3


class UpstreamError(Exception):
    pass


def _json_or_none(response: httpx.Response, what: str) -> dict[str, Any] | None:
    if response.status_code == 404:
        return None
    if response.is_error:
        log.warning("%s answered %s", what, response.status_code)
        raise UpstreamError(f"{what} answered {response.status_code}")
    return response.json()


def get_invoice(invoice_id: str) -> dict[str, Any] | None:
    response = httpx.get(f"{BILLING_API_URL}/invoices/{invoice_id}", timeout=TIMEOUT_SECONDS)
    return _json_or_none(response, "billing-api")


def get_customer(customer_id: str) -> dict[str, Any] | None:
    response = httpx.get(f"{BILLING_API_URL}/customers/{customer_id}", timeout=TIMEOUT_SECONDS)
    return _json_or_none(response, "billing-api")


def get_order(order_id: str) -> dict[str, Any] | None:
    response = httpx.get(f"{ORDERS_API_URL}/orders/{order_id}", timeout=TIMEOUT_SECONDS)
    return _json_or_none(response, "orders-api")
