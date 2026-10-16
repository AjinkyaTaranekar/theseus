"""Customer standing from billing-api.

A customer with an unpaid invoice older than 30 days is put on hold by billing and cannot place new orders.
billing-api is internal (`*.internal.demo.test`) and answers in well under a second; if it does not, we let the
order through and log it, because a missed sale costs more than a late invoice.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

BILLING_API_URL = os.environ["BILLING_API_URL"]


@dataclass(frozen=True)
class CustomerStatus:
    customer_id: str
    can_order: bool
    reason: str | None = None


def customer_status(customer_id: str) -> CustomerStatus:
    """Whether the customer may order now. Fails open when billing-api is slow or down."""
    try:
        response = httpx.get(f"{BILLING_API_URL}/customers/{customer_id}/status", timeout=2)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return CustomerStatus(customer_id, can_order=False, reason="unknown customer")
        log.warning("billing-api answered %s for %s; letting the order through", e.response.status_code, customer_id)
        return CustomerStatus(customer_id, can_order=True)
    except httpx.HTTPError as e:
        log.warning("billing-api unreachable for %s (%s); letting the order through", customer_id, e)
        return CustomerStatus(customer_id, can_order=True)

    body = response.json()
    on_hold = body.get("status") == "on_hold"
    return CustomerStatus(
        customer_id,
        can_order=not on_hold,
        reason=body.get("reason") if on_hold else None,
    )
