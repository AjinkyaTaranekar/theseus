"""The FalkorDB connection, from Settings (docs/spec/07-github-and-deploy.md, "Where FalkorDB runs")."""

from __future__ import annotations

import logging

from falkordb import FalkorDB
from redis.exceptions import RedisError

from theseus.config import Settings
from theseus.errors import GraphError

log = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 5.0


def get_client(settings: Settings) -> FalkorDB:
    """A client connected to the configured FalkorDB. Raises GraphError when it cannot connect or log in."""
    password = settings.falkordb_password.get_secret_value() if settings.falkordb_password else None
    try:
        db = FalkorDB(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            username=settings.falkordb_username or None,
            password=password,
            ssl=settings.falkordb_tls,
            socket_connect_timeout=CONNECT_TIMEOUT_S,
            socket_timeout=CONNECT_TIMEOUT_S * 6,
        )
        db.connection.ping()
    except RedisError as e:
        where = f"{settings.falkordb_host}:{settings.falkordb_port}"
        raise GraphError(f"cannot reach FalkorDB at {where}: {type(e).__name__}: {e}") from e
    log.info("connected to FalkorDB at %s:%s", settings.falkordb_host, settings.falkordb_port)
    return db


def ping(db: FalkorDB) -> bool:
    """True when the server answers; False when it does not."""
    try:
        return bool(db.connection.ping())
    except RedisError as e:
        log.warning("FalkorDB ping failed: %s", e)
        return False


def server_version(db: FalkorDB) -> str:
    """The graph module's version, such as "4.22.0". Raises GraphError when the server will not say."""
    try:
        modules = db.connection.execute_command("MODULE", "LIST")
    except RedisError as e:
        raise GraphError(f"cannot read the FalkorDB version: {e}") from e
    for module in modules:
        fields = dict(zip(module[::2], module[1::2], strict=False))
        name = fields.get("name", fields.get(b"name"))
        if name in ("graph", b"graph"):
            ver = int(fields.get("ver", fields.get(b"ver", 0)))
            return f"{ver // 10000}.{ver // 100 % 100}.{ver % 100}"
    raise GraphError("the server has no graph module")
