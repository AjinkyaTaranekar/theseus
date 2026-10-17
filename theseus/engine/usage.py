"""Scan mode and code checks (04-engine.md section 17): the grants a workload holds but its code never uses,
and the code a PR adds that reads sensitive data no owner approved.

An unused grant to sensitive data is exposure that costs nothing to remove, so the scan lists each one that
lies on a dangerous path and proposes candidate U to take them away, verified like any candidate. A use beyond
intent is the other way round: no IAM changes, but the code starts calling data the grant always allowed.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from theseus.contracts.adapters import Change
from theseus.contracts.engine import Analysis, GraphState, GraphStore, RuleFix
from theseus.contracts.result import BeyondIntent, EdgeRow, Evidence, NodeInfo, Requirement, UnusedGrant
from theseus.contracts.schema import RESOURCE
from theseus.engine.analyze import evidence_id, primary_evidence
from theseus.engine.intent_effect import RANK, describe
from theseus.engine.words import kind, name
from theseus.errors import GraphError

log = logging.getLogger(__name__)

WORKLOAD = "Workload"


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


def use_beyond_intent(
    base: GraphState, head: GraphState, requirements: list[Requirement]
) -> list[BeyondIntent]:
    """Each code call in head but not in base, by (workload, resource, access), to sensitive data or to what
    unlocks it, that no `theseus.yaml` requirement of that workload covers. Most sensitive first, as the
    headline picks it (a database before the secret that unlocks it), then by resource, workload and access.

    A requirement covers the resource it names and a secret that unlocks it: the secret on the way to a
    required database (04-engine.md section 10). Intent requirements cover nothing, since words never approve:
    a use the PR asks for is still listed, and the headline says it asked.
    """
    nodes = {n.id: n for n in head.rows.nodes}
    unlocks: dict[str, set[str]] = defaultdict(set)
    for edge in head.rows.edges:
        if edge.type == "UNLOCKS":
            unlocks[edge.src].add(edge.dst)
    covered: dict[str, set[str]] = defaultdict(set)
    for r in requirements:
        if r.source == "config":
            covered[r.principal].add(r.resource)
    before = _calls(base)
    found: list[BeyondIntent] = []
    for (workload, resource), edge in sorted(_calls(head).items()):
        opens = sorted(unlocks[resource])
        if not nodes[resource].sensitive and not any(nodes[d].sensitive for d in opens):
            continue
        if resource in covered[workload] or covered[workload] & set(opens):
            log.info("call %s -> %s is covered by a theseus.yaml requirement", workload, resource)
            continue
        old = before.get((workload, resource))
        added = sorted(set(edge.grants) - set(old.grants if old is not None else []))
        if not added:
            continue
        file, line = _new_line(edge, old.evidence if old is not None else [])
        found.extend(
            BeyondIntent(workload=workload, resource=resource, access=a, file=file, line=line, unlocks=opens)  # type: ignore[arg-type]
            for a in added
        )
    unlocked = {u for use in found for u in use.unlocks}
    return sorted(
        found,
        key=lambda u: (
            RANK.get(nodes[u.resource].sensitivity or "", len(RANK)),
            0 if u.resource in unlocked else 1,
            u.resource,
            u.workload,
            u.access,
        ),
    )


def _calls(state: GraphState) -> dict[tuple[str, str], EdgeRow]:
    """The one CALLS edge from each workload to each resource (Q_CALLS), by (workload, resource)."""
    labels = {n.id: n.labels for n in state.rows.nodes}
    return {
        (e.src, e.dst): e
        for e in state.rows.edges
        if e.type == "CALLS" and WORKLOAD in labels.get(e.src, []) and RESOURCE in labels.get(e.dst, [])
    }


def _new_line(edge: EdgeRow, known: list[Evidence]) -> tuple[str, int]:
    """The file and line of the edge's first call that base does not have, else of its first call; `unknown`
    and 0 when no call carries a line."""
    calls = sorted({(ev.file, ev.line) for ev in edge.evidence if ev.file != "unknown" and ev.line})
    if not calls:
        log.info("call %s -> %s carries no line; cited as unknown", edge.src, edge.dst)
        return "unknown", 0
    seen = {(ev.file, ev.line) for ev in known}
    return next((c for c in calls if c not in seen), calls[0])
