"""The FalkorDB connection, from Settings (docs/spec/07-github-and-deploy.md, "Where FalkorDB runs")."""

from __future__ import annotations

import logging
from dataclasses import dataclass

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


# What one review graph costs on FalkorDB Cloud, on average: the 49 graphs leaked by tests took about 40 MB. A
# graph's own size cannot be read (`GRAPH.MEMORY USAGE` says 0), so a dry run estimates with this, and a
# delete measures with the server's memory before and after.
GRAPH_MB = 0.8


@dataclass(frozen=True)
class Memory:
    """The server's memory in megabytes: what it holds, and the most it may hold (None for no limit)."""

    used_mb: float
    limit_mb: float | None


def memory(db: FalkorDB) -> Memory:
    """The server's memory in use and its limit, from `INFO memory`. Raises GraphError when it will not say.

    A FalkorDB Cloud instance sets `maxmemory` with the `noeviction` policy, so a full one refuses writes
    instead of dropping old data: this is the number to watch before a run that writes many graphs.
    """
    try:
        info = db.connection.info("memory")
    except RedisError as e:
        raise GraphError(f"cannot read the memory of FalkorDB: {e}") from e
    if "used_memory" not in info:
        raise GraphError("cannot read the memory of FalkorDB: the server reports no used_memory")
    limit = float(info.get("maxmemory") or 0)
    return Memory(used_mb=float(info["used_memory"]) / 1e6, limit_mb=limit / 1e6 if limit > 0 else None)
