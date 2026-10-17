"""Connections to the customer database.

Credentials come from the `prod-db-credentials` secret, never from the environment: the secret is rotated, and a
cold start picks up the new password. The connection is opened per request; Lambda freezes the container between
invocations, so a pooled connection would go stale and Postgres would drop it anyway.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import boto3
import psycopg

log = logging.getLogger(__name__)

DB_SECRET = os.environ["DB_SECRET"]
SECRET_TTL_SECONDS = 300

_sm = boto3.client("secretsmanager")
_cached: tuple[float, dict[str, Any]] | None = None


def _credentials() -> dict[str, Any]:
    """The secret's JSON, cached for five minutes so a busy minute does not hit Secrets Manager every call."""
    global _cached
    if _cached and time.monotonic() - _cached[0] < SECRET_TTL_SECONDS:
        return _cached[1]
    secret = _sm.get_secret_value(SecretId=DB_SECRET)
    _cached = (time.monotonic(), json.loads(secret["SecretString"]))
    return _cached[1]


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """A read-only connection to the customer database, closed when the block ends."""
    creds = _credentials()
    conn = psycopg.connect(
        host=creds["host"],
        port=creds.get("port", 5432),
        dbname=os.environ["DB_NAME"],
        user=creds["username"],
        password=creds["password"],
        connect_timeout=3,
        sslmode="require",
        options="-c default_transaction_read_only=on -c statement_timeout=5000",
    )
    try:
        yield conn
    finally:
        conn.close()
