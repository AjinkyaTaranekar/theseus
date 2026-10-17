"""Requirement capacities and evidence-backed cuts derived from the residual network."""

from __future__ import annotations

import logging
from collections import defaultdict

from theseus.contracts.engine import Analysis, FlowRow, GraphState, GraphStore
from theseus.contracts.result import CutEdge, EdgeRow, GraphRows, MinCut, Requirement
from theseus.contracts.schema import BIG, MAX_PATH_EDGES, PATH_TYPES, TRAVERSE, USED
from theseus.engine.analyze import evidence_id, primary_evidence
from theseus.errors import GraphError
from theseus.graph.algos import max_flow, reachable

log = logging.getLogger(__name__)


def _required_paths(rows: GraphRows, requirement: Requirement) -> list[list[EdgeRow]]:
    adjacency: dict[str, list[EdgeRow]] = defaultdict(list)
    for edge in rows.edges:
        if edge.type in PATH_TYPES and edge.kind != "unknown":
            adjacency[edge.src].append(edge)
    found: list[list[EdgeRow]] = []
    nodes = {node.id: node for node in rows.nodes}

    def walk(here: str, seen: set[str], path: list[EdgeRow]) -> None:
        if path and here == requirement.resource:
            if (requirement.access == "assume" and path[-1].type in TRAVERSE) or (
                path[-1].type in {"CAN", "UNLOCKS"} and requirement.access in path[-1].grants
            ):
                found.append(path)
            return
        if len(path) == MAX_PATH_EDGES:
            return
        for edge in sorted(adjacency[here], key=lambda e: e.eid):
            traversing = not path or path[-1].type in TRAVERSE
            allowed = edge.type in TRAVERSE or (requirement.access != "assume" and edge.type == "CAN")
            if not traversing:
                allowed = (
                    path[-1].type == "CAN"
                    and edge.type == "UNLOCKS"
                    and here in nodes
                    and nodes[here].category == "Secret"
                )
            if allowed and edge.dst not in seen:
                walk(edge.dst, seen | {edge.dst}, [*path, edge])

    walk(requirement.principal, {requirement.principal}, [])
    return found


def used_grants(rows: GraphRows) -> set[str]:
    """IDs of the CAN edges a workload's code uses: its role grants an access that a CALLS edge, from a
    workload running as that role to the same resource, also names (04-engine.md section 12)."""
    roles: dict[str, set[str]] = defaultdict(set)
    for edge in rows.edges:
        if edge.type == "RUNS_AS":
            roles[edge.dst].add(edge.src)
    called: dict[tuple[str, str], set[str]] = defaultdict(set)
    for edge in rows.edges:
        if edge.type == "CALLS":
            called[edge.src, edge.dst].update(edge.grants)
    return {
        edge.eid
        for edge in rows.edges
        if edge.type == "CAN"
        and edge.kind != "unknown"
        and any(called[workload, edge.dst] & set(edge.grants) for workload in roles[edge.src])
    }


def _capacity(edge: EdgeRow, protected: set[str], used: set[str]) -> int:
    if edge.type in {"RUNS_AS", "UNLOCKS"} or edge.eid in protected:
        return BIG
    return USED if edge.eid in used else 1


def capacities(rows: GraphRows, analysis: Analysis, requirements: list[Requirement]) -> list[FlowRow]:
    """FLOW rows protecting config and approved intent requirements, with parallel capacities summed.

    A grant the code uses costs `USED`, so a cut prefers a grant nobody calls.

    Callers exclude intent requirements from suspicious text before passing them here.
    Sensitive targets cannot be approved by intent, even if a caller includes them.
    """
    sensitive = {n.id for n in rows.nodes if n.sensitive}
    protected: set[str] = set()
    nodes = {node.id: node for node in rows.nodes}
    for req in requirements:
        if req.source == "intent" and req.resource in sensitive:
            continue
        if req.access == "assume" or req.principal not in analysis.paths:
            # Analysis reports actor paths only; a role can still own a config requirement.
            for route in _required_paths(rows, req):
                protected.update(edge.eid for edge in route)
        for path in analysis.paths.get(req.principal, []):
            if path.target == req.resource and req.access in path.grants and not path.unknown:
                for index, step in enumerate(path.steps):
                    protected.update(
                        edge.eid
                        for edge in rows.edges
                        if (edge.src, edge.type, edge.dst) == (step.src, step.type, step.dst)
                        and edge.kind != "unknown"
                        and edge.evidence
                        and evidence_id(primary_evidence(edge, nodes)) == step.evidence
                        and (index != len(path.steps) - 1 or req.access in edge.grants)
                    )
    used = used_grants(rows)
    pairs = defaultdict(list)
    for edge in rows.edges:
        if edge.type in PATH_TYPES:
            pairs[edge.src, edge.dst].append(edge)
    return [
        FlowRow(
            src=src,
            dst=dst,
            eids=sorted(e.eid for e in edges),
            capacity=sum(_capacity(e, protected, used) for e in edges),
        )
        for (src, dst), edges in sorted(pairs.items())
    ]


def min_cut(
    store: GraphStore,
    state: GraphState,
    analysis: Analysis,
    sources: list[str],
    requirements: list[Requirement],
) -> MinCut:
    """The residual minimum cut to these sources' dangerous targets, with cited original edges."""
    sources = sorted(set(sources))
    sinks = sorted({p.target for p in analysis.dangerous if p.actor in sources} - set(sources))
    caps = capacities(state.rows, analysis, requirements)
    flow = max_flow(store, state.name, sources, sinks, caps)
    reached = reachable(sources, caps, flow)
    eids = {eid for row in caps if row.src in reached and row.dst not in reached for eid in row.eids}
    if any(not e.evidence for e in state.rows.edges if e.eid in eids):
        raise GraphError("cut edge has no source evidence")
    nodes = {n.id: n for n in state.rows.nodes}
    cut = (
        [
            CutEdge(
                eid=e.eid, src=e.src, type=e.type, dst=e.dst, evidence=evidence_id(primary_evidence(e, nodes))
            )
            for e in sorted(state.rows.edges, key=lambda e: (e.src, e.type, e.dst, e.eid))
            if e.eid in eids
        ]
        if sinks
        else []
    )
    return MinCut(sources=sources, sinks=sinks, value=int(flow.value), cuttable=flow.value < BIG, cut=cut)
