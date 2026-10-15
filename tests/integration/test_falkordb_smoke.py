"""Smoke test against a real FalkorDB: the Cloud instance from .env, or CI's pinned container."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator

import pytest
from falkordb import FalkorDB

from theseus.config import get_settings
from theseus.graph.client import get_client, ping, server_version

pytestmark = pytest.mark.falkordb

PREFIX = f"smoke__{os.getpid()}__"


@pytest.fixture(scope="module")
def db() -> Iterator[FalkorDB]:
    client = get_client(get_settings())
    yield client
    for name in client.list_graphs():
        if name.startswith(PREFIX):
            client.select_graph(name).delete()


def test_connects_and_reports_a_version(db: FalkorDB) -> None:
    assert ping(db)
    assert re.fullmatch(r"\d+\.\d+\.\d+", server_version(db))


def test_a_graph_answers_a_query(db: FalkorDB) -> None:
    g = db.select_graph(PREFIX + "one")
    assert g.query("RETURN 1").result_set == [[1]]


def test_graph_copy_makes_an_independent_copy(db: FalkorDB) -> None:
    src = db.select_graph(PREFIX + "src")
    src.query("CREATE (:Node {id: 'user:a'})-[:MEMBER_OF]->(:Node {id: 'group:b'})")
    src.copy(PREFIX + "copy")
    copy = db.select_graph(PREFIX + "copy")
    copy.query("MATCH ()-[e:MEMBER_OF]->() DELETE e")
    assert src.query("MATCH ()-[e]->() RETURN count(e)").result_set == [[1]]
    assert copy.query("MATCH ()-[e]->() RETURN count(e)").result_set == [[0]]


def test_the_algorithms_the_engine_needs_exist(db: FalkorDB) -> None:
    g = db.select_graph(PREFIX + "procs")
    names = {r[0] for r in g.query("CALL dbms.procedures() YIELD name RETURN name").result_set}
    assert {"algo.maxFlow", "algo.betweenness"} <= names
