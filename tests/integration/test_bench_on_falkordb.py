"""Benchmark operations use real graph copies and the database algorithm on a tiny world."""

from __future__ import annotations

from pathlib import Path

import pytest

from bench.run import benchmark_lock
from bench.scale import run_scale
from theseus.config import get_settings
from theseus.errors import GraphError
from theseus.graph.client import get_client
from theseus.graph.store import FalkorStore

pytestmark = pytest.mark.falkordb


def test_benchmark_operations_preserve_the_source_and_clean_their_graphs(tmp_path: Path) -> None:
    database = get_client(get_settings())
    store = FalkorStore(database)
    with benchmark_lock(database) as check_owner:
        with pytest.raises(GraphError, match="another benchmark"):
            with benchmark_lock(database):
                pytest.fail("a second benchmark must not acquire the active lock")
        before = store.list_graphs()  # The shared, empty coordination graph deliberately persists.
        result = run_scale(store, tmp_path, 20, check_owner=check_owner)
    assert result.edges == 20 and result.sinks == 16
    assert all(len(timing.samples_ns) == 5 for timing in result.measurements.values())
    assert store.list_graphs() == before
