"""The server's memory as `prune` reports it, read through a fake client: no FalkorDB needed."""

from __future__ import annotations

from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from theseus.errors import GraphError
from theseus.graph.client import Memory, memory


class FakeConnection:
    def __init__(self, info: dict[str, Any] | Exception) -> None:
        self.result = info
        self.sections: list[str] = []

    def info(self, section: str) -> dict[str, Any]:
        self.sections.append(section)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeDb:
    def __init__(self, info: dict[str, Any] | Exception) -> None:
        self.connection = FakeConnection(info)


def test_memory_in_use_and_the_limit_are_read_in_megabytes() -> None:
    db = FakeDb({"used_memory": 96_300_000, "maxmemory": 105_000_000, "other": 1})
    assert memory(db) == Memory(used_mb=96.3, limit_mb=105.0)  # type: ignore[arg-type]
    assert db.connection.sections == ["memory"]


def test_a_server_with_no_limit_has_no_limit_mb() -> None:
    assert memory(FakeDb({"used_memory": 5_000_000, "maxmemory": 0})).limit_mb is None  # type: ignore[arg-type]
    assert memory(FakeDb({"used_memory": 5_000_000})).limit_mb is None  # type: ignore[arg-type]


def test_a_server_that_will_not_say_is_a_graph_error() -> None:
    with pytest.raises(GraphError, match="cannot read the memory of FalkorDB"):
        memory(FakeDb(RedisConnectionError("gone")))  # type: ignore[arg-type]
    with pytest.raises(GraphError, match="no used_memory"):
        memory(FakeDb({"maxmemory": 1}))  # type: ignore[arg-type]
