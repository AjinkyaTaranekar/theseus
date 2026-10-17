"""Catch a test that leaves a graph behind on a shared FalkorDB.

The FalkorDB Cloud instance in `.env` has a 100 MB cap and never evicts, and every graph costs about 0.8 MB,
so a few leaked graphs per run fill it and fail the next run with an out-of-memory error. `tests/conftest.py`
runs this around every module that has FalkorDB tests.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from falkordb import FalkorDB, Graph

from theseus.graph.store import DOCS

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
