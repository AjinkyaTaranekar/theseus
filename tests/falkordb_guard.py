"""Keep `pytest -m falkordb` from filling a shared FalkorDB.

The FalkorDB Cloud instance in `.env` has a 100 MB cap and never evicts, and every graph costs about 0.8 MB,
so a few leaked graphs per run fill it and fail the next run with an out-of-memory error. `tests/conftest.py`
uses this two ways: it fails a module that leaves a graph behind (`GraphLedger`), and it stops a run before
the first test when the instance has less room than a full run needs (`refuse_a_full_instance`).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import pytest
from falkordb import FalkorDB, Graph

from theseus.config import get_settings
from theseus.errors import GraphError
from theseus.graph.client import get_client, memory
from theseus.graph.store import DOCS

log = logging.getLogger(__name__)

# What a full `pytest -m falkordb` run needs free on the instance. It peaked 10.5 MB above where it started on
# 2026-10-17, so this is that rounded up. Measure it again when a module that saves many graphs is added.
FULL_RUN_MB = 11.0

# The review documents' graph is shared with the product, which makes it on the first review it saves. Tests
# delete their own documents by key and leave the graph.
SHARED = frozenset({DOCS})


class GraphLedger:
    """The graphs this process touched on a FalkorDB.

    A leak is a graph this process touched that was not there before and still is. A graph another run makes
    on the same instance meanwhile is not this process's to judge, or to delete."""

    def __init__(self) -> None:
        self.touched: set[str] = set()

    def install(
        self,
        patch: pytest.MonkeyPatch,
        client: type = FalkorDB,
        graph: type = Graph,
    ) -> None:
        """Record every graph name `client.select_graph` is given and every `graph.copy` makes, until `patch`
        is undone."""
        select_graph = client.select_graph
        copy = graph.copy

        def recording_select_graph(db: FalkorDB, graph_id: str) -> Graph:
            if isinstance(graph_id, str):
                self.touched.add(graph_id)
            return select_graph(db, graph_id)

        def recording_copy(source: Graph, clone: str) -> Graph:
            if isinstance(clone, str):
                self.touched.add(clone)
            return copy(source, clone)

        patch.setattr(client, "select_graph", recording_select_graph)
        patch.setattr(graph, "copy", recording_copy)

    def left_behind(self, before: Iterable[str], after: Iterable[str]) -> list[str]:
        """The graphs this process touched that are in `after` but were not in `before`, sorted."""
        return sorted((self.touched & (set(after) - set(before))) - SHARED)


def drop_unused_docs_graph(db: FalkorDB, before: Iterable[str]) -> bool:
    """Delete the review documents' graph when it was not in `before` and holds no document; True if it did.

    The tests that save a review delete their own documents, which leaves the graph itself on an instance
    that had none. A graph with a document in it belongs to someone, so it stays."""
    if DOCS in set(before) or DOCS not in db.list_graphs():
        return False
    graph = db.select_graph(DOCS)
    if graph.query("MATCH (d:Doc) RETURN count(d)").result_set[0][0]:
        return False
    graph.delete()
    return True


def headroom_problem(db: FalkorDB, where: str, needed_mb: float = FULL_RUN_MB) -> str | None:
    """Why a full FalkorDB test run should not start on `db`, in words that say what to do; None when it can.

    A run can start when the server has no memory limit (a local container, CI's service container) or at
    least `needed_mb` of its limit free. `where` is how the person knows the instance, such as `host:port`.
    A server that will not say its memory is not refused: the tests will report what is wrong with it."""
    try:
        reading = memory(db)
    except GraphError as e:
        log.warning("not checking the room on FalkorDB at %s: %s", where, e)
        return None
    if reading.limit_mb is None:
        return None
    free = reading.limit_mb - reading.used_mb
    if free >= needed_mb:
        return None
    return (
        f"Not enough room on FalkorDB at {where}: {reading.used_mb:.1f} of {reading.limit_mb:.1f} MB used, "
        f"{free:.1f} MB free, and a full `pytest -m falkordb` run needs about {needed_mb:.0f} MB. It would "
        "fail halfway with an out-of-memory error, so no test was run.\n"
        "Make room, or use another instance:\n"
        "  - `python tools/purge_test_graphs.py` lists the graphs earlier test runs leaked "
        "(add --yes to delete them); `python -m theseus prune` lists those of closed PRs.\n"
        '  - AGENTS.md, "Run the falkordb tests on your own machine", starts a FalkorDB of your own.'
    )


def refuse_a_full_instance(session: Any) -> None:
    """Stop the run, with `headroom_problem`'s message, when a FalkorDB test will run on an instance that
    has less room than a full run needs. Does nothing otherwise, and does not connect: in the default
    offline run every FalkorDB test is skipped, and listing the tests (`--collect-only`) writes nothing."""
    if session.config.option.collectonly:
        return
    if not any(
        "falkordb" in item.keywords and item.get_closest_marker("skip") is None for item in session.items
    ):
        return
    settings = get_settings()
    where = f"{settings.falkordb_host}:{settings.falkordb_port}"
    try:
        db = get_client(settings)
    except GraphError as e:
        log.warning("not checking the room on FalkorDB at %s: %s", where, e)
        return
    problem = headroom_problem(db, where)
    if problem is not None:
        pytest.exit(problem, returncode=2)
