"""Customer export for the support team's mailing tool.

Support asked for a list of active customers' emails to send the refund-policy update. This reads them
straight from the customer database with the shared credentials, one query, and returns them for the admin
page.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
import psycopg

log = logging.getLogger(__name__)

DB_SECRET = os.environ["DB_SECRET"]

_sm = boto3.client("secretsmanager")

ACTIVE_CUSTOMERS_SQL = """
    SELECT c.customer_id, c.name, c.email
    FROM customers c
    WHERE c.deleted_at IS NULL AND c.marketing_opt_out IS FALSE
    ORDER BY c.customer_id
"""


def _credentials() -> dict[str, Any]:
    secret = _sm.get_secret_value(SecretId=DB_SECRET)
    return json.loads(secret["SecretString"])


def export_customers() -> list[dict[str, str]]:
    """Every active customer's ID, name and email."""
    creds = _credentials()
    with psycopg.connect(
        host=creds["host"],
        port=creds.get("port", 5432),
        dbname=creds.get("dbname", "customers"),
        user=creds["username"],
        password=creds["password"],
        connect_timeout=3,
        sslmode="require",
    ) as conn, conn.cursor() as cur:
        cur.execute(ACTIVE_CUSTOMERS_SQL)
        rows = [{"customer_id": r[0], "name": r[1], "email": r[2]} for r in cur.fetchall()]
    log.info("exported %d customers", len(rows))
    return rows
