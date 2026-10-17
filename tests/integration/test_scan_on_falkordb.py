"""Scan mode answers the same from FalkorDB as from memory, including the unused-grant query (C3)."""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

from tests.golden.conftest import deps_for, expected, world
from theseus.config import get_settings
from theseus.contracts.result import compare, project
from theseus.engine import pipeline
from theseus.graph.client import get_client
from theseus.graph.store import FalkorStore

pytestmark = pytest.mark.falkordb


def test_scan_has_database_parity_and_matches_the_answer_key(monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = f"c3_scan__{os.getpid()}__"
    monkeypatch.setattr(pipeline, "graph_name", lambda world, side: prefix + side)
    main = world("unused-grant", "base")
    memory = deps_for("unused-grant")
    database = FalkorStore(get_client(get_settings()))
    try:
        want = pipeline.run_scan(main, memory)
        got = pipeline.run_scan(main, replace(memory, store=database))
        assert got.model_dump(exclude={"timings"}) == want.model_dump(exclude={"timings"})
        assert compare(project(got), expected("unused-grant")) == []
        assert any(name.startswith(prefix) and name.endswith("fix-u") for name in database.list_graphs())
    finally:
        for name in database.list_graphs():
            if name.startswith(prefix):
                database.delete(name)
