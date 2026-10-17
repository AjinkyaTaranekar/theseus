"""Where a PR's change lands and what depends on it, for every PR, whatever the data's class. Pure: it reads
the two states' rows and the paths the engine already traced for them.

An SRE's first questions about any change are what it touches and what breaks if it goes wrong. So besides
the dangerous paths (sensitive data nothing requires), the impact lists:

- **Touched** nodes: those an IaC address the change adds, updates or deletes, and the ends of every link it
  adds or removes; who reaches each one, how many dependencies run through it, and the services calling it.
- **Access** every actor gains or loses, to any resource.
- **Dependencies** (code calls and `theseus.yaml` requirements) whose routes run through what changed, or
  that gain or lose their last route.
- **The cost** of the world before and after, from the cloud adapter's list prices.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from theseus.contracts.engine import Analysis, GraphState
from theseus.contracts.posture import CostLine, Dependency
from theseus.contracts.result import (
    AccessChange,
    ChangeImpact,
    EdgeChange,
    PathRecord,
    Reliance,
    Requirement,
    ResourceChange,
    TouchedNode,
)
from theseus.contracts.schema import PATH_TYPES
from theseus.engine import words
from theseus.engine.posture import dependencies, routes_for

log = logging.getLogger(__name__)

# The links a change can add or remove that matter to someone: access, code and CI. Requirement bookkeeping
# (FOR, NEEDS) and findings are not part of the infrastructure.
LINKS = frozenset({*PATH_TYPES, "CALLS", "REQUESTS", "HAS_ENV", "USES"})
MOST = 3


def _edges(state: GraphState) -> dict[tuple[str, str, str], list[str]]:
    """Each link by (src, type, dst), with the IaC addresses of its evidence."""
    found: dict[tuple[str, str, str], list[str]] = {}
    for e in state.rows.edges:
        if e.type in LINKS:
            found[(e.src, e.type, e.dst)] = sorted({ev.address for ev in e.evidence if ev.address})
    return found


def _reach(analysis: Analysis) -> dict[tuple[str, str], PathRecord]:
    """Each (actor, target) a valid path joins, with one of its paths (the first, in the engine's order)."""
    found: dict[tuple[str, str], PathRecord] = {}
    for actor, paths in analysis.paths.items():
        for p in paths:
            if not p.unknown:
                found.setdefault((actor, p.target), p)
    return found


def _grants(analysis: Analysis, actor: str, target: str) -> list[str]:
    return sorted({g for p in analysis.paths.get(actor, []) if p.target == target for g in p.grants})


def change_impact(
    base: GraphState,
    head: GraphState,
    before: Analysis,
    after: Analysis,
    requirements: list[Requirement],
    changes: list[ResourceChange],
    cost_before: list[CostLine],
    cost_after: list[CostLine],
    evidence_keys: dict[tuple[str, str, str], str] | None = None,
) -> ChangeImpact:
    """The change's impact, with the most affected nodes first and a one-line headline."""
    changed = {c.address for c in changes}
    base_nodes = {n.id: n for n in base.rows.nodes}
    head_nodes = {n.id: n for n in head.rows.nodes}
    touched: dict[str, tuple[str, str]] = {}
    for nid, n in head_nodes.items():
        address = str(n.props.get("address", ""))
        if address in changed:
            touched[nid] = ("updated" if nid in base_nodes else "added", address)
    for nid, n in base_nodes.items():
        address = str(n.props.get("address", ""))
        if nid not in head_nodes and address in changed:
            touched[nid] = ("removed", address)
    base_edges, head_edges = _edges(base), _edges(head)
    keys = evidence_keys or {}
    edges = [
        EdgeChange(src=s, type=t, dst=d, action="added", evidence=keys.get((s, t, d)))  # type: ignore[arg-type]
        for (s, t, d) in sorted(set(head_edges) - set(base_edges))
    ] + [
        EdgeChange(src=s, type=t, dst=d, action="removed", evidence=keys.get((s, t, d)))  # type: ignore[arg-type]
        for (s, t, d) in sorted(set(base_edges) - set(head_edges))
    ]
    for e in edges:
        for end in (e.src, e.dst):
            if end not in touched:
                gone = end in base_nodes and end not in head_nodes
                fresh = end in head_nodes and end not in base_nodes
                touched[end] = ("removed" if gone else "added" if fresh else "updated", "")
    moved = {(e.src, e.type, e.dst) for e in edges}

    # Access every actor gains or loses, to anything.
    reach_before, reach_after = _reach(before), _reach(after)
    access = [
        AccessChange(
            actor=a,
            target=t,
            change="gained",
            grants=_grants(after, a, t),  # type: ignore[arg-type]
            sensitivity=reach_after[(a, t)].sensitivity,
        )
        for (a, t) in sorted(set(reach_after) - set(reach_before))
    ] + [
        AccessChange(
            actor=a,
            target=t,
            change="lost",
            grants=_grants(before, a, t),  # type: ignore[arg-type]
            sensitivity=reach_before[(a, t)].sensitivity,
        )
        for (a, t) in sorted(set(reach_before) - set(reach_after))
    ]

    # The dependencies whose routes run through what changed, or that gain or lose their last route.
    def through(routes: list[PathRecord]) -> set[str]:
        via: set[str] = set()
        for r in routes:
            via |= {n for n in r.route if n in touched}
            via |= {n for s in r.steps if (s.src, s.type, s.dst) in moved for n in (s.src, s.dst)}
        return via

    # A code call and a requirement for the same access are one dependency here; the requirement names it.
    seen: dict[tuple[str, str, str], Dependency] = {}
    for state in (base, head):
        for d in dependencies(state, requirements):
            old = seen.get((d.principal, d.access, d.resource))
            if old is None or d.source == "requirement":
                seen[(d.principal, d.access, d.resource)] = d
    relies: list[Reliance] = []
    for d in seen.values():
        routes_b = routes_for(before.paths.get(d.principal, []), d)
        routes_h = routes_for(after.paths.get(d.principal, []), d)
        state = "lost" if routes_b and not routes_h else "gained" if routes_h and not routes_b else "kept"
        via = through(routes_h or routes_b)
        if state != "kept" or via:
            relies.append(
                Reliance(
                    principal=d.principal,
                    access=d.access,
                    resource=d.resource,
                    source=d.source,
                    state=state,  # type: ignore[arg-type]
                    via=sorted(via),
                )
            )
    relies.sort(
        key=lambda r: ({"lost": 0, "gained": 1, "kept": 2}[r.state], r.principal, r.resource, r.access)
    )

    # Who reaches each touched node, and the services that call a touched service (REQUESTS, transitively).
    reached: dict[str, set[str]] = defaultdict(set)
    for analysis in (before, after):
        for actor, paths in analysis.paths.items():
            for p in paths:
                for n in p.route:
                    if n in touched and n != actor:
                        reached[n].add(actor)
    callers: dict[str, set[str]] = defaultdict(set)
    for s, t, d in head_edges:
        if t == "REQUESTS":
            callers[d].add(s)

    def dependents_of(node: str) -> list[str]:
        out: set[str] = set()
        todo = [node]
        while todo:
            for caller in callers.get(todo.pop(), set()):
                if caller not in out and caller != node:
                    out.add(caller)
                    todo.append(caller)
        return sorted(out)

    relied = {n: sum(1 for r in relies if n in r.via) for n in touched}
    nodes = [
        TouchedNode(
            id=n,
            action=action,  # type: ignore[arg-type]
            address=address,
            reached_by=sorted(reached.get(n, set())),
            relied_on=relied[n],
            dependents=dependents_of(n),
        )
        for n, (action, address) in touched.items()
    ]
    actors_moved = {a.actor for a in access} | {a.target for a in access}
    nodes.sort(
        key=lambda t: (-t.relied_on, -len(t.dependents), -len(t.reached_by), t.id not in actors_moved, t.id)
    )
    before_usd = round(sum(line.monthly_usd for line in cost_before), 2)
    after_usd = round(sum(line.monthly_usd for line in cost_after), 2)
    found = ChangeImpact(
        touched=nodes,
        edges=edges,
        access=access,
        relies=relies,
        dependents=sorted({d for t in nodes for d in t.dependents}),
        most_affected=[t.id for t in nodes[:MOST]],
        monthly_usd_before=before_usd,
        monthly_usd_after=after_usd,
    )
    return found.model_copy(update={"headline": impact_headline(found)})


def _count(n: int, one: str, many: str) -> str:
    return f"1 {one}" if n == 1 else f"{n} {many}"


def _who_moves(impact: ChangeImpact, change: str, verb: str) -> str:
    """ "priya-intern gains access to 4 resources", or "3 people and services lose access to 5 resources"."""
    moves = [a for a in impact.access if a.change == change]
    if not moves:
        return ""
    actors = sorted({a.actor for a in moves})
    targets = _count(len({a.target for a in moves}), "resource", "resources")
    if len(actors) == 1:
        return f"{words.name(actors[0])} {verb} access to {targets}"
    plural = "gain" if verb == "gains" else "lose"
    return f"{len(actors)} people and services {plural} access to {targets}"


def impact_headline(impact: ChangeImpact) -> str:
    """One sentence an SRE can act on: what the change touches, who it affects, what breaks, what it costs."""
    if not impact.touched and not impact.access:
        return "The change touches nothing Theseus models: no access, code call or requirement moves."
    parts = []
    if impact.most_affected:
        top = impact.touched[0]
        who = len(top.reached_by)
        lead = f"Lands on {words.name(top.id)}"
        if who:
            lead += f", which {_count(who, 'person or service reaches', 'people and services reach')}"
        parts.append(lead)
    bits = [_who_moves(impact, "gained", "gains"), _who_moves(impact, "lost", "loses")]
    parts.append(" and ".join(b for b in bits if b) or "no one gains or loses access")
    broken = [r for r in impact.relies if r.state == "lost"]
    through = [r for r in impact.relies if r.state == "kept"]
    if broken:
        parts.append(f"it breaks {_count(len(broken), 'dependency', 'dependencies')}")
    elif through:
        parts.append(f"{_count(len(through), 'dependency runs', 'dependencies run')} through it, all kept")
    else:
        parts.append("no dependency runs through it")
    delta = round(impact.monthly_usd_after - impact.monthly_usd_before, 2)
    if delta:
        parts.append(f"{'+' if delta > 0 else '-'}${abs(delta):,.2f} a month at list price")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:] + "."
