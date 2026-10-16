"""The SQL behind billing-api's routes, run on the connection the handler passes in.

Every query is parameterized and reads one row. Customer standing is computed here, not stored: a customer is on
hold when an invoice has been unpaid for more than 30 days.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

HOLD_AFTER_DAYS = 30

INVOICE_SQL = """
    SELECT i.invoice_id, i.order_id, i.customer_id, i.amount, i.currency, i.issued_at, i.paid_at
    FROM invoices i
    WHERE i.invoice_id = %(id)s
"""

CUSTOMER_SQL = """
    SELECT c.customer_id, c.name, c.email, c.country, c.created_at
    FROM customers c
    WHERE c.customer_id = %(id)s AND c.deleted_at IS NULL
"""

STATUS_SQL = """
    SELECT c.customer_id,
           COUNT(i.invoice_id) FILTER (
               WHERE i.paid_at IS NULL AND i.issued_at < now() - make_interval(days => %(days)s)
           ) AS overdue
    FROM customers c
    LEFT JOIN invoices i ON i.customer_id = c.customer_id
    WHERE c.customer_id = %(id)s AND c.deleted_at IS NULL
    GROUP BY c.customer_id
"""


def _one(conn: psycopg.Connection, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def invoice(conn: psycopg.Connection, invoice_id: str) -> dict[str, Any] | None:
    return _one(conn, INVOICE_SQL, {"id": invoice_id})


def customer(conn: psycopg.Connection, customer_id: str) -> dict[str, Any] | None:
    return _one(conn, CUSTOMER_SQL, {"id": customer_id})


def customer_status(conn: psycopg.Connection, customer_id: str) -> dict[str, Any] | None:
    """`active`, or `on_hold` with the reason, for orders-api."""
    row = _one(conn, STATUS_SQL, {"id": customer_id, "days": HOLD_AFTER_DAYS})
    if row is None:
        return None
    if row["overdue"]:
        return {"status": "on_hold", "reason": f"{row['overdue']} invoice(s) unpaid after {HOLD_AFTER_DAYS} days"}
    return {"status": "active"}
