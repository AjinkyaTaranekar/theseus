"""The graph store: FalkorDB in the product, MemoryStore for offline tests (03-graph.md, 05-contracts.md).

Both answer the canonical queries alike; `tests/integration/test_store_parity.py` holds them to it. Only
`FalkorStore` may serve the API: rule 3 says the product does not work without FalkorDB.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any

from falkordb import FalkorDB
from redis.exceptions import RedisError

from theseus.contracts.engine import (
    CallRow,
    FlowResult,
    FlowRow,
    GrantRow,
    GraphDelta,
    WorkflowUse,
)
from theseus.contracts.result import ChokePoint, EdgeRow, GraphRows, NodeRow
from theseus.contracts.schema import MAX_PATH_EDGES, PATH_TYPES, RESOURCE
from theseus.errors import GraphError
from theseus.graph import queries

log = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z0-9_-]+$")
# Small documents kept next to the graphs, such as a review's result for its page (api/reviews.py).
DOCS = "theseus__docs"
PATH_SET = frozenset(PATH_TYPES)


def _check_name(graph: str) -> None:
    if not NAME.fullmatch(graph):
        raise GraphError(f"graph names use only a-z, 0-9, - and _: {graph!r}")


# In memory ------------------------------------------------------------------------------------------------


class MemoryStore:
    """Graphs held as rows, for offline tests only. Never serves the API (AGENTS.md, rule 3)."""

    def __init__(self) -> None:
        self._graphs: dict[str, GraphRows] = {}
        self._docs: dict[str, str] = {}

    def _rows(self, graph: str) -> GraphRows:
        if graph not in self._graphs:
            raise GraphError(f"no graph {graph!r} in the store")
        return self._graphs[graph]

    def list_graphs(self) -> list[str]:
        return sorted(self._graphs)

    def load(self, graph: str, rows: GraphRows) -> None:
        _check_name(graph)
        self._graphs[graph] = rows.model_copy(deep=True)

    def copy(self, src: str, dst: str) -> None:
        _check_name(dst)
        self._graphs[dst] = self._rows(src).model_copy(deep=True)

    def delete(self, graph: str) -> None:
        self._graphs.pop(graph, None)

    def view(self, graph: str) -> GraphView:
        rows = self._rows(graph)
        return _view(
            [(n.labels, node_properties(n)) for n in rows.nodes],
            [(e.src, e.type, e.dst, edge_properties(e)) for e in rows.edges],
        )

    def put_doc(self, key: str, text: str) -> None:
        self._docs[key] = text

    def get_doc(self, key: str) -> str | None:
        return self._docs.get(key)

    def apply_delta(self, graph: str, delta: GraphDelta) -> None:
        rows = self._rows(graph)
        gone_edges = set(delta.remove_edges)
        gone_nodes = set(delta.remove_nodes)
        nodes = [n for n in rows.nodes if n.id not in gone_nodes] + list(delta.add_nodes)
        edges = [
            e
            for e in rows.edges
            if (e.src, e.type, e.dst) not in gone_edges
            and e.src not in gone_nodes
            and e.dst not in gone_nodes
        ] + list(delta.add_edges)
        self._graphs[graph] = rows.model_copy(update={"nodes": nodes, "edges": edges}, deep=True)

    def paths(self, graph: str, actor: str) -> list[list[str]]:
        """Q_PATHS: like Cypher, a route never repeats an edge, may revisit a node, and ends at a Resource."""
        rows = self._rows(graph)
        resources = {n.id for n in rows.nodes if RESOURCE in n.labels}
        out_edges: dict[str, list[EdgeRow]] = defaultdict(list)
        for e in rows.edges:
            if e.type in PATH_SET:
                out_edges[e.src].append(e)
        if actor not in {n.id for n in rows.nodes}:
            return []
        found: list[list[str]] = []

        def walk(here: str, route: list[str], used: set[str]) -> None:
            for e in out_edges.get(here, []):
                if e.eid in used:
                    continue
                step = [*route, e.eid]
                if e.dst in resources:
                    found.append(step)
                if len(step) < MAX_PATH_EDGES:
                    walk(e.dst, step, used | {e.eid})

        walk(actor, [], set())
        return sorted(found)

    def max_flow(self, graph: str, sources: list[str], sinks: list[str], rows: list[FlowRow]) -> FlowResult:
        raise GraphError("MemoryStore has no max flow yet; task E4 adds it")

    def betweenness(self, graph: str) -> list[ChokePoint]:
        raise GraphError("MemoryStore has no betweenness yet; task FM4 adds it")

    def workflows_using(self, graph: str, action: str) -> list[WorkflowUse]:
        rows = self._rows(graph)
        workflows = {n.id for n in rows.nodes if "Workflow" in n.labels}
        return sorted(
            (
                WorkflowUse(workflow=e.src, version=str(e.props.get("version", "")))
                for e in rows.edges
                if e.type == "USES" and e.dst == action and e.src in workflows
            ),
            key=lambda w: w.workflow,
        )

    def unused_grants(self, graph: str) -> list[GrantRow]:
        rows = self._rows(graph)
        nodes = {n.id: n for n in rows.nodes}
        runs_as = defaultdict(list)
        cans = defaultdict(list)
        calls: dict[tuple[str, str], EdgeRow] = {}
        for e in rows.edges:
            if e.type == "RUNS_AS" and "Workload" in nodes[e.src].labels and "Role" in nodes[e.dst].labels:
                runs_as[e.src].append(e.dst)
            elif e.type == "CAN":
                cans[e.src].append(e)
            elif e.type == "CALLS":
                calls[(e.src, e.dst)] = e
        out = []
        for workload, roles in runs_as.items():
            for role in roles:
                for c in cans[role]:
                    target = nodes[c.dst]
                    if RESOURCE not in target.labels or not target.sensitive:
                        continue
                    x = calls.get((workload, c.dst))
                    if x is None or not set(c.grants) & set(x.grants):
                        out.append(GrantRow(workload=workload, resource=c.dst, eid=c.eid))
        return sorted(out, key=lambda g: (g.workload, g.resource, g.eid))

    def calls(self, graph: str) -> list[CallRow]:
        rows = self._rows(graph)
        nodes = {n.id: n for n in rows.nodes}
        out = [
            CallRow(workload=e.src, resource=e.dst, access=access, eid=e.eid)
            for e in rows.edges
            if e.type == "CALLS" and "Workload" in nodes[e.src].labels and RESOURCE in nodes[e.dst].labels
            for access in e.grants
        ]
        return sorted(out, key=lambda c: (c.workload, c.resource, c.access))


# FalkorDB -------------------------------------------------------------------------------------------------


def _value(v: Any) -> Any:
    """A FalkorDB property value: scalars and lists of scalars as they are; anything nested as JSON text."""
    if isinstance(v, dict) or (isinstance(v, list) and any(isinstance(x, (dict, list)) for x in v)):
        return json.dumps(v, sort_keys=True)
    return v


def node_properties(n: NodeRow) -> dict[str, Any]:
    """A node's stored properties: the typed fields and its `props`, with nothing null (03-graph.md)."""
    out = {k: v for k, v in n.model_dump(exclude={"labels", "props"}).items() if v is not None}
    out.update({k: _value(v) for k, v in n.props.items() if v is not None})
    return out


def edge_properties(e: EdgeRow) -> dict[str, Any]:
    """An edge's stored properties: `eid`, `kind`, `grants`, `evidence` as JSON text, and its `props`."""
    out: dict[str, Any] = {
        "eid": e.eid,
        "kind": e.kind,
        "grants": list(e.grants),
        "evidence": json.dumps([ev.model_dump() for ev in e.evidence], sort_keys=True),
    }
    out.update({k: _value(v) for k, v in e.props.items() if v is not None})
    return out


GraphView = dict[str, list[dict[str, Any]]]


def _view(nodes: list[tuple[Any, dict[str, Any]]], edges: list[tuple[Any, ...]]) -> GraphView:
    """A graph as JSON-ready nodes and edges, as stored, sorted by ID and by (src, type, dst): each node's
    labels and properties, each edge's endpoints, type and properties with its evidence as a list."""
    out_nodes = [{"labels": sorted(labels), **props} for labels, props in nodes]
    out_edges = []
    for src, edge_type, dst, props in edges:
        edge = {"src": src, "type": edge_type, "dst": dst, **props}
        if isinstance(edge.get("evidence"), str):
            edge["evidence"] = json.loads(edge["evidence"])
        out_edges.append(edge)
    return {
        "nodes": sorted(out_nodes, key=lambda n: n["id"]),
        "edges": sorted(out_edges, key=lambda e: (e["src"], e["type"], e["dst"], e.get("eid", ""))),
    }


class FalkorStore:
    """Graphs in FalkorDB, one per state (03-graph.md, "One graph per state")."""

    def __init__(self, db: FalkorDB) -> None:
        self.db = db

    def _query(self, graph: str, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        try:
            return self.db.select_graph(graph).query(cypher, params or {}).result_set
        except RedisError as e:
            raise GraphError(f"{graph}: {type(e).__name__}: {e}") from e

    def list_graphs(self) -> list[str]:
        try:
            return sorted(self.db.list_graphs())
        except RedisError as e:
            raise GraphError(f"cannot list graphs: {e}") from e

    def delete(self, graph: str) -> None:
        if graph not in self.list_graphs():
            return
        try:
            self.db.select_graph(graph).delete()
        except RedisError as e:
            raise GraphError(f"cannot delete {graph}: {e}") from e

    def view(self, graph: str) -> GraphView:
        if graph not in self.list_graphs():
            raise GraphError(f"no graph {graph!r} in the store")
        nodes = self._query(graph, "MATCH (n:Node) RETURN labels(n), properties(n)")
        edges = self._query(graph, "MATCH (a:Node)-[e]->(b:Node) RETURN a.id, type(e), b.id, properties(e)")
        return _view([(labels, props) for labels, props in nodes], [tuple(row) for row in edges])

    def put_doc(self, key: str, text: str) -> None:
        self._query(DOCS, "MERGE (d:Doc {key: $key}) SET d.text = $text", {"key": key, "text": text})

    def get_doc(self, key: str) -> str | None:
        if DOCS not in self.list_graphs():
            return None
        found = self._query(DOCS, "MATCH (d:Doc {key: $key}) RETURN d.text", {"key": key})
        return found[0][0] if found else None

    def _add(self, graph: str, nodes: list[NodeRow], edges: list[EdgeRow]) -> None:
        by_labels: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for n in nodes:
            by_labels[tuple(sorted(set(n.labels)))].append(node_properties(n))
        for labels, rows in sorted(by_labels.items()):
            self._query(graph, queries.create_nodes(list(labels)), {"rows": rows})
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for e in edges:
            by_type[e.type].append({"src": e.src, "dst": e.dst, "props": edge_properties(e)})
        for edge_type, rows in sorted(by_type.items()):
            self._query(graph, queries.create_edges(edge_type), {"rows": rows})

    def load(self, graph: str, rows: GraphRows) -> None:
        _check_name(graph)
        self.delete(graph)
        nodes = sorted(rows.nodes, key=lambda n: n.id)
        by_labels: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for n in nodes:
            by_labels[tuple(sorted(set(n.labels)))].append(node_properties(n))
        for labels, batch in sorted(by_labels.items()):
            self._query(graph, queries.create_nodes(list(labels)), {"rows": batch})
        if nodes:
            self._query(graph, queries.INDEX)
        self._add(graph, [], sorted(rows.edges, key=lambda e: (e.type, e.src, e.dst)))
        log.info("loaded %s: %d nodes, %d edges", graph, len(rows.nodes), len(rows.edges))

    def copy(self, src: str, dst: str) -> None:
        _check_name(dst)
        self.delete(dst)
        try:
            self.db.select_graph(src).copy(dst)
        except RedisError as e:
            raise GraphError(f"cannot copy {src} to {dst}: {e}") from e

    def apply_delta(self, graph: str, delta: GraphDelta) -> None:
        by_type: dict[str, list[dict[str, str]]] = defaultdict(list)
        for src, edge_type, dst in delta.remove_edges:
            by_type[edge_type].append({"src": src, "dst": dst})
        for edge_type, rows in sorted(by_type.items()):
            self._query(graph, queries.delete_edges(edge_type), {"rows": rows})
        if delta.remove_nodes:
            self._query(graph, queries.DELETE_NODES, {"ids": sorted(delta.remove_nodes)})
        self._add(graph, list(delta.add_nodes), list(delta.add_edges))

    def paths(self, graph: str, actor: str) -> list[list[str]]:
        return sorted([list(row[0]) for row in self._query(graph, queries.Q_PATHS, {"actor": actor})])

    def max_flow(self, graph: str, sources: list[str], sinks: list[str], rows: list[FlowRow]) -> FlowResult:
        raise GraphError("FalkorStore runs max flow from task E4")

    def betweenness(self, graph: str) -> list[ChokePoint]:
        raise GraphError("FalkorStore runs betweenness from task FM4")

    def workflows_using(self, graph: str, action: str) -> list[WorkflowUse]:
        found = self._query(graph, queries.Q_WORKFLOWS_USING, {"action": action})
        return sorted((WorkflowUse(workflow=w, version=str(v)) for w, v in found), key=lambda w: w.workflow)

    def unused_grants(self, graph: str) -> list[GrantRow]:
        found = self._query(graph, queries.Q_UNUSED_GRANTS)
        return sorted(
            (GrantRow(workload=w, resource=r, eid=e) for w, r, e in found),
            key=lambda g: (g.workload, g.resource, g.eid),
        )

    def calls(self, graph: str) -> list[CallRow]:
        found = self._query(graph, queries.Q_CALLS)
        return sorted(
            (CallRow(workload=w, resource=r, access=a, eid=e) for w, r, a, e in found),
            key=lambda c: (c.workload, c.resource, c.access),
        )
