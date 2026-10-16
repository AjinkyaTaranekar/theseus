"""Finding mode: what an advisory's workflows can reach if they are compromised (04-engine.md section 16).

An advisory's text is untrusted: it names the Action and its versions here and nothing else, and it is never
evidence. Core reasons on categories and edge types; the Action and its workflows are plain nodes.
"""

from __future__ import annotations

import logging
from typing import Any

from theseus.contracts.engine import Analysis, GraphState, GraphStore
from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow, PathRecord
from theseus.engine.analyze import analyze

log = logging.getLogger(__name__)

SECRET = "Secret"


def action_id(advisory: dict[str, Any]) -> str:
    """The graph ID of the advisory's Action."""
    return f"action:{advisory['action']}"


def match_advisory(rows: GraphRows, advisory: dict[str, Any]) -> list[str]:
    """The workflows that use the advisory's Action at an affected version, sorted."""
    action = action_id(advisory)
    affected = set(advisory.get("affected_versions") or [])
    return sorted(
        {
            e.src
            for e in rows.edges
            if e.type == "USES" and e.dst == action and e.props.get("version") in affected
        }
    )


def with_finding(rows: GraphRows, advisory: dict[str, Any]) -> GraphRows:
    """The rows plus a `Finding` node with an `AFFECTS` edge to the Action, when a workflow uses it.

    The edge is assumed and cites the advisory by ID with `file="unknown"`: an advisory is not a source file.
    """
    node = f"finding:{advisory['id']}"
    action = action_id(advisory)
    finding = NodeRow(
        id=node, labels=["Node", "Finding"], name=advisory["id"], props={"finding_id": advisory["id"]}
    )
    if not any(n.id == action for n in rows.nodes):
        log.info("advisory %s names %s, which no workflow uses; no AFFECTS edge", advisory["id"], action)
        return rows.model_copy(update={"nodes": [*rows.nodes, finding]})
    evidence = Evidence(
        address=f"advisory:{advisory['id']}", file="unknown", line=None, note="assumed compromise (advisory)"
    )
    eid = f"e{max((int(e.eid.removeprefix('e')) for e in rows.edges), default=0) + 1}"
    edge = EdgeRow(eid=eid, type="AFFECTS", src=node, dst=action, kind="assumed", evidence=[evidence])
    return rows.model_copy(update={"nodes": [*rows.nodes, finding], "edges": [*rows.edges, edge]})


def blast_radius(store: GraphStore, state: GraphState, workflows: list[str]) -> list[PathRecord]:
    """The dangerous paths of these workflows, assumed compromised, one per (workflow, target), sorted."""
    return analyze(store, state, [], workflows).dangerous


def secrets_reached(analysis: Analysis, state: GraphState) -> list[str]:
    """Every secret any analyzed actor can reach by a valid path, sorted."""
    nodes = {n.id: n for n in state.rows.nodes}
    return sorted(
        {p.target for paths in analysis.paths.values() for p in paths if nodes[p.target].category == SECRET}
    )


def rotate_list(store: GraphStore, state: GraphState, workflows: list[str]) -> list[str]:
    """Every secret any of these workflows can reach, sorted: the credentials to rotate."""
    return secrets_reached(analyze(store, state, [], workflows), state)
