"""An outage's blast radius on `main`, from the basis a posture run keeps. Pure, and no engine call: its
routes were the engine's when the posture ran, so an answer means the same as the posture's single points.

- **Matched** nodes are the ones the service runs or serves, as the cloud and CI adapters tagged them.
- **A dependency breaks** when its principal or its resource is down, or every valid route of it passes
  through something down. It is **degraded** when every route left passes through something degraded.
- **Affected** principals lose a dependency, or call (REQUESTS) a service that is down or impaired.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from theseus.contracts.engine import GraphState
from theseus.contracts.incident import (
    BrokenDependency,
    DependencyRoutes,
    Impact,
    Incident,
    IncidentReport,
    OutageBasis,
    OutageMap,
    RegionTerm,
    ServiceTerm,
    State,
)
from theseus.contracts.posture import CostLine
from theseus.contracts.result import NodeInfo

log = logging.getLogger(__name__)

RANK = {"down": 0, "impaired": 1, "degraded": 2}
# Words in a headline that mean the service is slow or failing in part, not out.
DEGRADED = ("degraded", "degradation", "latency", "slow", "elevated", "increased error", "intermittent")
TITLE_CHARS = 200


def outage_basis(
    state: GraphState, routes: list[DependencyRoutes], maps: list[OutageMap], cost: list[CostLine]
) -> OutageBasis:
    """What a posture run keeps: every adapter's tags and terms, each dependency's routes, the REQUESTS
    calls, the cost by IaC address, and plain names for every node named."""
    nodes = {n.id: n for n in state.rows.nodes}
    tags = sorted(
        {(t.node, t.provider, t.service, t.region or ""): t for m in maps for t in m.tags}.values(),
        key=lambda t: (t.node, t.provider, t.service, t.region or ""),
    )
    terms = sorted(
        {(t.provider, t.service): t for m in maps for t in m.terms}.values(),
        key=lambda t: (t.provider, t.service),
    )
    regions = sorted({r.code: r for m in maps for r in m.regions}.values(), key=lambda r: r.code)
    requests = sorted({(e.src, e.dst) for e in state.rows.edges if e.type == "REQUESTS"})
    named = {t.node for t in tags} | {n for r in routes for route in r.routes for n in route}
    named |= {n for r in routes for n in (r.dependency.principal, r.dependency.resource)}
    named |= {n for pair in requests for n in pair}
    return OutageBasis(
        tags=tags,
        terms=terms,
        regions=regions,
        routes=routes,
        requests=requests,
        cost={line.address: line.monthly_usd for line in cost},
        nodes={
            n: NodeInfo(category=nodes[n].category, sensitivity=nodes[n].sensitivity)
            for n in sorted(named)
            if n in nodes
        },
    )


def _found(text: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(word.lower())}(?![a-z0-9])", text) is not None


def read_incident(text: str, terms: list[ServiceTerm], regions: list[RegionTerm]) -> Incident | None:
    """The incident a headline names: the service whose longest name it contains (a provider named in it
    breaks ties), the region it names if any, and `degraded` when it says slow or degraded. None when it
    names no service. The text is matched against words only; it is never an instruction."""
    lowered = text.lower()
    best: tuple[bool, int, str, str] | None = None
    chosen: ServiceTerm | None = None
    for term in terms:
        for word in [term.name, *term.aliases]:
            if not _found(lowered, word):
                continue
            score = (
                any(_found(lowered, p) for p in term.provider_names),
                len(word),
                term.provider,
                term.service,
            )
            if best is None or score[:2] > best[:2]:
                best, chosen = score, term
    if chosen is None:
        return None
    region = next((r.code for r in regions if _found(lowered, r.code)), None)
    if region is None:
        region = next((r.code for r in regions for w in [r.name, *r.aliases] if _found(lowered, w)), None)
    degraded = any(word in lowered for word in DEGRADED)
    return Incident(
        provider=chosen.provider,
        service=chosen.service,
        region=region,
        severity="degraded" if degraded else "down",
        title=" ".join(text.split())[:TITLE_CHARS],
        source="text",
    )


def _matched(basis: OutageBasis, incident: Incident) -> dict[str, Impact]:
    hit: dict[str, Impact] = {}
    for tag in basis.tags:
        if (tag.provider, tag.service) != (incident.provider, incident.service):
            continue
        if incident.region and tag.region and tag.region != incident.region:
            continue
        state = "degraded" if incident.severity == "degraded" else tag.effect
        old = hit.get(tag.node)
        if old is None or RANK[state] < RANK[old.state]:
            hit[tag.node] = Impact(id=tag.node, state=state, why=tag.why, address=tag.address)
    return hit


def _cut(dep: DependencyRoutes, out: set[str], weak: set[str]) -> BrokenDependency | None:
    d = dep.dependency
    for end in (d.principal, d.resource):
        if end in out:
            return BrokenDependency(dependency=d, state="broken", why=f"{end} is down", via=[end])
    if not dep.routes:
        return None  # it had no route before the outage either: nothing to lose
    alive = [r for r in dep.routes if not set(r[1:-1]) & out]
    if not alive:
        via = sorted({n for r in dep.routes for n in r[1:-1] if n in out})
        return BrokenDependency(
            dependency=d, state="broken", why="every route to it goes through " + ", ".join(via), via=via
        )
    for end in (d.principal, d.resource):
        if end in weak:
            return BrokenDependency(dependency=d, state="degraded", why=f"{end} is degraded", via=[end])
    if all(set(r) & weak for r in alive):
        via = sorted({n for r in alive for n in r if n in weak})
        return BrokenDependency(
            dependency=d, state="degraded", why="every route left goes through " + ", ".join(via), via=via
        )
    return None


def _set(found: dict[str, Impact], node: str, state: State, why: str) -> bool:
    old = found.get(node)
    if old is not None and RANK[old.state] <= RANK[state]:
        return False
    found[node] = Impact(id=node, state=state, why=why)
    return True


def blast(basis: OutageBasis, incident: Incident) -> IncidentReport:
    """What the incident takes down, what loses something it needs, and which dependencies break, sorted
    with the worst first; and a one-line headline in plain words."""
    matched = _matched(basis, incident)
    out = {n for n, i in matched.items() if i.state == "down"}
    weak = {n for n, i in matched.items() if i.state == "degraded"}
    # A code call and a requirement for the same access are one dependency here: it breaks once.
    unique = {(r.dependency.principal, r.dependency.access, r.dependency.resource): r for r in basis.routes}
    broken = [b for r in unique.values() if (b := _cut(r, out, weak)) is not None]
    affected: dict[str, Impact] = {}
    losses: dict[tuple[str, str], list[str]] = defaultdict(list)
    for b in broken:
        d = b.dependency
        if d.principal not in matched:
            losses[(d.principal, b.state)].append(f"{d.access} on {d.resource}")
    for (principal, cut), lost in sorted(losses.items()):
        why = ("loses " if cut == "broken" else "may lose ") + ", ".join(sorted(set(lost)))
        _set(affected, principal, "impaired" if cut == "broken" else "degraded", why)
    callers: dict[str, list[str]] = defaultdict(list)
    for src, dst in basis.requests:
        callers[dst].append(src)
    todo = sorted({**affected, **matched})
    while todo:
        node = todo.pop(0)
        state = (matched.get(node) or affected[node]).state
        for caller in sorted(callers.get(node, [])):
            if caller in matched:
                continue
            word = "is down" if state == "down" else f"is {state}"
            if _set(
                affected,
                caller,
                "degraded" if state == "degraded" else "impaired",
                f"calls {node}, which {word}",
            ):
                todo.append(caller)
    matched_list = sorted(matched.values(), key=lambda i: (RANK[i.state], i.id))
    affected_list = sorted(affected.values(), key=lambda i: (RANK[i.state], i.id))
    broken.sort(key=lambda b: (b.state, b.dependency.principal, b.dependency.resource, b.dependency.access))
    addresses = {i.address for i in matched_list if i.address}
    regions = sorted({t.region for t in basis.tags if t.region})
    named = {i.id for i in [*matched_list, *affected_list]} | {n for b in broken for n in b.via}
    named |= {n for b in broken for n in (b.dependency.principal, b.dependency.resource)}
    return IncidentReport(
        incident=incident,
        headline=headline(
            incident, service_name(basis, incident), matched_list, affected_list, broken, len(unique), regions
        ),
        matched=matched_list,
        affected=affected_list,
        broken=broken,
        dependencies=len(unique),
        monthly_usd=round(sum(basis.cost.get(a, 0.0) for a in addresses), 2),
        regions=regions,
        nodes={n: basis.nodes[n] for n in sorted(named) if n in basis.nodes},
    )


def service_name(basis: OutageBasis, incident: Incident) -> str:
    term = next(
        (t for t in basis.terms if (t.provider, t.service) == (incident.provider, incident.service)), None
    )
    return term.name if term is not None else incident.service


def headline(
    incident: Incident,
    name: str,
    matched: list[Impact],
    affected: list[Impact],
    broken: list[BrokenDependency],
    total: int,
    regions: list[str],
) -> str:
    """One sentence: the outage, then how much of this world it reaches."""
    where = f" in {incident.region}" if incident.region else ""
    if not matched:
        if incident.region and regions and incident.region not in regions:
            return f"Nothing here runs on {name}{where}: this world runs in {', '.join(regions)}."
        return f"Nothing in this world runs on {name}{where}."
    counts: dict[str, int] = defaultdict(int)
    for i in matched:
        counts[i.state] += 1
    parts = [f"{counts[s]} {s}" for s in ("down", "degraded") if counts[s]]
    if affected:
        parts.append(
            "1 more loses something it needs"
            if len(affected) == 1
            else f"{len(affected)} more lose something they need"
        )
    cut = sum(1 for b in broken if b.state == "broken")
    parts.append(f"{cut} of {total} dependencies break")
    verb = "degraded" if incident.severity == "degraded" else "down"
    return f"{name} {verb}{where}: " + ", ".join(parts) + "."
