"""Valid paths, dangerous paths, requirement status, and the base-to-head diff (04-engine.md 9 to 11).

The store finds every route (Q_PATHS); this module keeps the valid ones. A valid path is a simple path of at
most MAX_PATH_EDGES edges: traversal edges, then CAN to a resource, then UNLOCKS when that resource is a
secret.
"""

from __future__ import annotations

import hashlib
import logging
from collections import deque

from theseus.contracts.engine import Analysis, GraphState, GraphStore, PathDiff
from theseus.contracts.result import (
    EdgeRow,
    Evidence,
    GraphRows,
    NodeRow,
    PathRecord,
    PathStep,
    Requirement,
    RequirementStatus,
)
from theseus.contracts.schema import MAX_PATH_EDGES, RESOURCE, TRAVERSE

log = logging.getLogger(__name__)

TRAVERSAL = frozenset(TRAVERSE)
SECRET = "Secret"


def evidence_id(ev: Evidence) -> str:
    """A stable name for one piece of evidence, the key of `AnalysisResult.evidence`."""
    return ":".join(
        [ev.file, "" if ev.line is None else str(ev.line), ev.address, *([ev.part] if ev.part else [])]
    )


def primary_evidence(edge: EdgeRow, nodes: dict[str, NodeRow]) -> Evidence:
    """The evidence a path step cites: what decided the edge. For CAN_ASSUME that is the caller's own
    permission, not the role's trust (04-engine.md section 6: the trust is the evidence only without one)."""
    if edge.type == "CAN_ASSUME":
        own = nodes[edge.dst].props.get("address") if edge.dst in nodes else None
        callers = [ev for ev in edge.evidence if own is None or ev.address != own]
        if callers:
            return callers[0]
    return edge.evidence[0]


def step_evidence(rows: GraphRows) -> dict[str, Evidence]:
    """Every edge's primary evidence by its ID, for the result's `evidence`."""
    nodes = {n.id: n for n in rows.nodes}
    out: dict[str, Evidence] = {}
    for e in rows.edges:
        if e.evidence:
            ev = primary_evidence(e, nodes)
            out[evidence_id(ev)] = ev
    return out


def path_id(actor: str, steps: list[PathStep]) -> str:
    """Stable across builds: named by (src, type, dst) of each step, never by eid."""
    text = actor + "|" + "|".join(f"{s.src},{s.type},{s.dst}" for s in steps)
    return "p" + hashlib.sha1(text.encode()).hexdigest()[:12]


def _record(
    actor: str, eids: list[str], nodes: dict[str, NodeRow], edges: dict[str, EdgeRow]
) -> PathRecord | None:
    """The path record for one route, or None when the route is not a valid path."""
    if not eids or len(eids) > MAX_PATH_EDGES or any(eid not in edges for eid in eids):
        return None
    route_edges = [edges[eid] for eid in eids]
    route = [actor]
    for e in route_edges:
        if e.src != route[-1]:
            return None
        route.append(e.dst)
    if len(set(route)) != len(route):
        return None  # a simple path: no node twice
    types = [e.type for e in route_edges]
    tail = 2 if types[-1] == "UNLOCKS" else 1
    if types[-tail] != "CAN" or any(t not in TRAVERSAL for t in types[:-tail]):
        return None
    if tail == 2 and nodes[route_edges[-2].dst].category != SECRET:
        return None
    target = nodes[route[-1]]
    if RESOURCE not in target.labels:
        return None
    steps = [
        PathStep.model_validate(
            {"from": e.src, "type": e.type, "to": e.dst, "evidence": evidence_id(primary_evidence(e, nodes))}
        )
        for e in route_edges
    ]
    return PathRecord(
        id=path_id(actor, steps),
        actor=actor,
        target=target.id,
        grants=sorted(set(route_edges[-1].grants)),  # type: ignore[arg-type]
        steps=steps,
        unknown=any(e.kind == "unknown" for e in route_edges),
        inferred=any(e.kind == "inferred" for e in route_edges),
        sensitivity=target.sensitivity,
    )


def _assume_status(rows: GraphRows, principal: str, role: str) -> str:
    """`assume` is satisfied by any traversal path that reaches the role; unknown if only unknown edges do."""
    out: dict[str, list[EdgeRow]] = {}
    for e in rows.edges:
        if e.type in TRAVERSAL:
            out.setdefault(e.src, []).append(e)
    best = {principal: False}  # node -> whether the cheapest way there needs an unknown edge
    queue = deque([principal])
    while queue:
        here = queue.popleft()
        for e in out.get(here, []):
            unknown = best[here] or e.kind == "unknown"
            if e.dst not in best or (best[e.dst] and not unknown):
                best[e.dst] = unknown
                queue.append(e.dst)
    if role not in best or role == principal:
        return "missing"
    return "unknown" if best[role] else "satisfied"


def _status(req: Requirement, paths: list[PathRecord], rows: GraphRows) -> RequirementStatus:
    if req.access == "assume":
        return RequirementStatus(id=req.id, status=_assume_status(rows, req.principal, req.resource))  # type: ignore[arg-type]
    reaching = [p for p in paths if p.target == req.resource and req.access in p.grants]
    status = "satisfied" if any(not p.unknown for p in reaching) else "unknown" if reaching else "missing"
    return RequirementStatus(id=req.id, status=status)  # type: ignore[arg-type]


def _covered(actor: str, requirements: list[Requirement], paths: list[PathRecord]) -> set[str]:
    """What a `theseus.yaml` requirement covers for this actor: the resources it names, and every node on the
    route of a path that satisfies one (a secret on the way to a required database). Intent requirements never
    cover."""
    covered: set[str] = set()
    for req in requirements:
        if req.source != "config" or req.principal != actor:
            continue
        covered.add(req.resource)
        for p in paths:
            if p.target == req.resource and req.access in p.grants and not p.unknown:
                covered.update(p.route)
    return covered


def _rank(p: PathRecord) -> tuple[bool, int, list[str]]:
    return (p.unknown, len(p.steps), p.route)


def analyze(
    store: GraphStore, state: GraphState, requirements: list[Requirement], actors: list[str]
) -> Analysis:
    """Valid paths per actor, one dangerous path per (actor, target), each requirement's status; sorted."""
    nodes = {n.id: n for n in state.rows.nodes}
    edges = {e.eid: e for e in state.rows.edges}
    principals = sorted(set(actors) | {r.principal for r in requirements})
    paths: dict[str, list[PathRecord]] = {}
    for actor in principals:
        records: dict[str, PathRecord] = {}
        if actor in nodes:
            for eids in store.paths(state.name, actor):
                rec = _record(actor, eids, nodes, edges)
                if rec is not None:
                    records.setdefault(rec.id, rec)
        paths[actor] = sorted(records.values(), key=lambda p: (p.target, *_rank(p)))
    dangerous: list[PathRecord] = []
    for actor in sorted(actors):
        covered = _covered(actor, requirements, paths[actor])
        best: dict[str, PathRecord] = {}
        for p in paths[actor]:
            if nodes[p.target].sensitive and p.target not in covered:
                if p.target not in best or _rank(p) < _rank(best[p.target]):
                    best[p.target] = p
        dangerous.extend(best[t] for t in sorted(best))
    statuses = [_status(r, paths[r.principal], state.rows) for r in sorted(requirements, key=lambda r: r.id)]
    return Analysis(
        actors=sorted(actors),
        paths={a: paths[a] for a in sorted(actors)},
        dangerous=dangerous,
        requirements=statuses,
    )


def diff(base: Analysis, head: Analysis) -> PathDiff:
    """Dangerous paths by (actor, target): opened (head only), closed (base only), unchanged (both; head)."""
    b = {(p.actor, p.target): p for p in base.dangerous}
    h = {(p.actor, p.target): p for p in head.dangerous}
    return PathDiff(
        opened=[h[k] for k in sorted(h.keys() - b.keys())],
        closed=[b[k] for k in sorted(b.keys() - h.keys())],
        unchanged=[h[k] for k in sorted(h.keys() & b.keys())],
    )
