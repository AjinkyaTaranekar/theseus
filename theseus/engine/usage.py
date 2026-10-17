"""Scan mode and code checks (04-engine.md section 17): the grants a workload holds but its code never uses.

An unused grant to sensitive data is exposure that costs nothing to remove, so the scan lists each one that
lies on a dangerous path and proposes candidate U to take them away, verified like any candidate.
"""

from __future__ import annotations

import logging

from theseus.contracts.adapters import Change
from theseus.contracts.engine import Analysis, GraphState, GraphStore, RuleFix
from theseus.contracts.result import NodeInfo, UnusedGrant
from theseus.engine.analyze import evidence_id, primary_evidence
from theseus.engine.intent_effect import describe
from theseus.engine.words import kind, name
from theseus.errors import GraphError

log = logging.getLogger(__name__)


def unused_grants(
    store: GraphStore, state: GraphState, analysis: Analysis | None = None
) -> list[UnusedGrant]:
    """Each access of each grant to sensitive data that no code of the workload calls, sorted by (workload,
    resource, access).

    Only grants on one of that workload's dangerous paths are listed, so a grant a requirement needs is not.
    Without an `analysis` every such grant counts as dangerous. A grant whose edge is `unknown` (a condition
    the engine cannot decide) is left out: it may not exist.
    """
    edges = {edge.eid: edge for edge in state.rows.edges}
    nodes = {node.id: node for node in state.rows.nodes}
    on_path = (
        None
        if analysis is None
        else {(p.actor, s.src, s.type, s.dst) for p in analysis.dangerous for s in p.steps}
    )
    found: list[UnusedGrant] = []
    for row in store.unused_grants(state.name):
        edge = edges.get(row.eid)
        if edge is None:
            raise GraphError(
                f"graph {state.name} lists an unused grant for an edge it has no row for: {row.eid}"
            )
        if edge.kind == "unknown":
            log.info("grant %s -> %s is conditional; not called unused", edge.src, edge.dst)
            continue
        if on_path is not None and (row.workload, edge.src, edge.type, edge.dst) not in on_path:
            continue
        cite = evidence_id(primary_evidence(edge, nodes))
        found.extend(
            UnusedGrant(
                workload=row.workload, resource=row.resource, access=access, eid=edge.eid, evidence=cite
            )
            for access in sorted(set(edge.grants))
        )
    return sorted(found, key=lambda g: (g.workload, g.resource, g.access))


def unused_fix(state: GraphState, grants: list[UnusedGrant]) -> RuleFix | None:
    """Candidate U: remove every unused grant at once, or None when there is none to remove."""
    eids = sorted({g.eid for g in grants})
    if not eids:
        return None
    edges = {edge.eid: edge for edge in state.rows.edges}
    parts = sorted({ev.part for eid in eids for ev in edges[eid].evidence if ev.part})
    title = (
        "Remove the unused grant" + ("s" if len(eids) > 1 else "") + (f" {', '.join(parts)}" if parts else "")
    )
    return RuleFix(id="U", title=title, changes=[Change(kind="remove_edge", eid=eid) for eid in eids])


def scan_headline(grants: list[UnusedGrant], nodes: dict[str, NodeInfo]) -> str:
    """The scan's first line, in the words the comment uses: what is granted and never called."""
    if not grants:
        return "Every grant to sensitive data in main is backed by a call in the code."
    first = grants[0]
    one = (
        f"the {kind(first.workload)} {name(first.workload)} can reach {describe(first.resource, nodes)},"
        " but no line of its code calls it."
    )
    pairs = {(g.workload, g.resource) for g in grants}
    if len(pairs) == 1:
        return one[0].upper() + one[1:]
    return (
        f"{len(pairs)} grants to sensitive data are never called by the code that holds them."
        f" For example, {one}"
    )
