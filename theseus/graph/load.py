"""Loading, copying and deleting a state's graph (05-contracts.md, "Engine functions")."""

from __future__ import annotations

import logging

from theseus.contracts.engine import GraphDelta, GraphState, GraphStore
from theseus.contracts.result import GraphRows
from theseus.errors import GraphError

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


def delta(old: GraphRows, new: GraphRows) -> GraphDelta:
    """Sorted node and edge replacements that turn the old graph into the rebuilt graph.

    Edges are matched by endpoints and type, but replacements retain the rebuilt eids and properties.
    A changed node is replaced to remove stale properties and labels; its incident edges are restored.
    """
    before = {node.id: node for node in old.nodes}
    after = {node.id: node for node in new.nodes}
    old_edges = {(edge.src, edge.type, edge.dst): edge for edge in old.edges}
    new_edges = {(edge.src, edge.type, edge.dst): edge for edge in new.edges}
    if len(before) != len(old.nodes) or len(after) != len(new.nodes):
        raise GraphError("delta needs unique node IDs")
    if len(old_edges) != len(old.edges) or len(new_edges) != len(new.edges):
        raise GraphError("delta needs unique (source, type, destination) edges")
    replaced = {
        identifier for identifier in before.keys() & after.keys() if before[identifier] != after[identifier]
    }
    removed = (before.keys() - after.keys()) | replaced
    added = (after.keys() - before.keys()) | replaced
    changed_edges = {
        key
        for key in old_edges.keys() & new_edges.keys()
        if old_edges[key] != new_edges[key] or key[0] in replaced or key[2] in replaced
    }
    return GraphDelta(
        remove_nodes=sorted(removed),
        add_nodes=[after[key].model_copy(deep=True) for key in sorted(added)],
        remove_edges=sorted((old_edges.keys() - new_edges.keys()) | changed_edges),
        add_edges=[
            new_edges[key].model_copy(deep=True)
            for key in sorted((new_edges.keys() - old_edges.keys()) | changed_edges)
        ],
    )
