"""Loading, copying and deleting a state's graph (05-contracts.md, "Engine functions")."""

from __future__ import annotations

import logging

from theseus.contracts.engine import GraphDelta, GraphState, GraphStore

log = logging.getLogger(__name__)


def load_graph(store: GraphStore, state: GraphState) -> None:
    """Replace the graph the state's name names with the state's rows."""
    store.load(state.name, state.rows)


def copy_graph(store: GraphStore, src: str, dst: str) -> None:
    """GRAPH.COPY `src` to `dst`, replacing `dst`."""
    store.copy(src, dst)


def delete_graph(store: GraphStore, name: str) -> None:
    """Delete the graph; no error when it does not exist."""
    store.delete(name)


def apply_delta(store: GraphStore, name: str, delta: GraphDelta) -> None:
    """Remove, then add, the delta's nodes and edges."""
    store.apply_delta(name, delta)
