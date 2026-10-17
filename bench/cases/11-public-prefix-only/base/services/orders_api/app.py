"""orders-api: the HTTP front of the order flow.

The website posts new orders here. We check the customer with billing-api first, so a customer on hold cannot
place an order, then store the order and queue an `order.created` event for orders-worker to fulfil.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from orders_api import billing, events, store

log = logging.getLogger("orders_api")
app = FastAPI(title="orders-api", version="2.3.1")


class OrderLine(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0, le=100)
    unit_price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class NewOrder(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    lines: list[OrderLine] = Field(min_length=1, max_length=50)
    currency: str = Field(default="EUR", pattern="^[A-Z]{3}$")


class Order(NewOrder):
    order_id: str
    status: str
    created_at: str
    total: Decimal


@app.post("/orders", status_code=201)
def create_order(new: NewOrder) -> Order:
    """Accept an order: the customer must be in good standing with billing."""
    status = billing.customer_status(new.customer_id)
    if not status.can_order:
        log.info("customer %s cannot order: %s", new.customer_id, status.reason)
        raise HTTPException(status_code=402, detail=status.reason or "account on hold")

    order = Order(
        **new.model_dump(),
        order_id=f"ord_{uuid.uuid4().hex[:16]}",
        status="pending",
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        total=sum((line.unit_price * line.quantity for line in new.lines), Decimal("0")),
    )
    store.put_order(order.model_dump(mode="json"))
    events.publish_order_created(order.order_id, order.customer_id)
    log.info("order %s created for %s, total %s %s", order.order_id, order.customer_id, order.total, order.currency)
    return order


@app.get("/orders/{order_id}")
def get_order(order_id: str) -> Order:
    found = store.get_order(order_id)
    if found is None:
        raise HTTPException(status_code=404, detail="order not found")
    return Order(**found)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
