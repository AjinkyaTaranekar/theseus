"""Card charges through the payment provider.

The provider's API key lives in Secrets Manager (`payments-api-key`). The key is read once per run, not per
charge, because the nightly run can bill a few thousand orders. Charges are idempotent on the order ID, so a
re-run never charges a customer twice.
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from functools import lru_cache
from typing import Any

import boto3
import httpx

log = logging.getLogger(__name__)

PAYMENTS_SECRET = os.environ["PAYMENTS_SECRET"]

_sm = boto3.client("secretsmanager")


class ChargeDeclined(Exception):
    pass


@lru_cache(maxsize=1)
def _api_key() -> str:
    secret = _sm.get_secret_value(SecretId=PAYMENTS_SECRET)
    return json.loads(secret["SecretString"])["api_key"]


def _minor_units(amount: str, currency: str) -> int:
    """Cents (or the currency's minor unit), as the provider expects."""
    digits = 0 if currency in {"JPY", "KRW"} else 2
    return int((Decimal(amount) * (10**digits)).to_integral_value())


def charge(order: dict[str, Any]) -> str:
    """Charge the customer's card on file for the order. Returns the provider's charge ID."""
    response = httpx.post(
        "https://api.payments.example/v1/charges",
        headers={"Authorization": f"Bearer {_api_key()}", "Idempotency-Key": order["order_id"]},
        json={
            "customer": order["customer_id"],
            "amount": _minor_units(order["total"], order["currency"]),
            "currency": order["currency"].lower(),
            "description": f"Order {order['order_id']}",
        },
        timeout=10,
    )
    if response.status_code == 402:
        raise ChargeDeclined(f"order {order['order_id']}: {response.json().get('decline_code', 'declined')}")
    response.raise_for_status()
    charge_id = response.json()["id"]
    log.info("charged order %s as %s", order["order_id"], charge_id)
    return charge_id
