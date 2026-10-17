"""What the support portal shows: the ticket's context, and the refund confirmation page.

The refund page is shown to the support engineer, who reads it out or pastes it to the customer, so its wording
is customer-facing. Copy changes go through the support lead.
"""

from __future__ import annotations

import html
from typing import Any

from support_portal import clients

REFUND_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Refund {refund_id}</title></head>
<body>
  <h1>Refund {refund_id}</h1>
  <p>We have received your refund request for {amount} {currency}.</p>
  <p>It will reach the original payment method within 5 to 10 working days.</p>
</body>
</html>
"""


def ticket_context(ticket_id: str, customer_id: str | None, order_id: str | None) -> dict[str, Any] | None:
    """The customer, their order and its invoice, for the ticket on screen."""
    if not customer_id:
        return None
    customer = clients.get_customer(customer_id)
    if customer is None:
        return None
    context: dict[str, Any] = {"ticket_id": ticket_id, "customer": customer, "order": None, "invoice": None}
    if order_id:
        order = clients.get_order(order_id)
        context["order"] = order
        if order and order.get("invoice_id"):
            context["invoice"] = clients.get_invoice(order["invoice_id"])
    return context


def refund_page(refund_id: str, amount: str, currency: str) -> str:
    """The confirmation the engineer gives the customer."""
    return REFUND_PAGE.format(
        refund_id=html.escape(refund_id),
        amount=html.escape(amount),
        currency=html.escape(currency),
    )
