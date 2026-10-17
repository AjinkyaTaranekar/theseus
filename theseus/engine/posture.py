"""The posture of `main` (issues O1 to O3): who reaches what, single points of failure, articulation points,
and what could be removed. Pure: the store answers the path queries, and everything else is read from rows.

- **Reach** is each actor's blast radius: every sensitive target it has a valid path to, whether or not a
  requirement covers it, since a compromised actor reaches both.
- **A single point of failure** is a node on every valid route of a dependency (a code call or a
  `theseus.yaml` requirement), from the engine's own paths, so it means the same as everywhere else.
- **An articulation point** is a node whose removal splits the access graph (Tarjan's algorithm, undirected).
- **Unreached** data is a resource that no actor reaches and no code calls: it may be left over.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from theseus.contracts.engine import GraphState, GraphStore
from theseus.contracts.posture import (
    Articulation,
    CostLine,
    CostSummary,
    Dependency,
    DependencyRoutes,
    OutageMap,
    Posture,
    Reach,
    Saving,
    SinglePoint,
)
from theseus.contracts.result import EdgeRow, NodeInfo, NodeRow, PathRecord, Requirement
from theseus.contracts.schema import PATH_TYPES, RESOURCE
from theseus.engine.analyze import analyze
from theseus.engine.incident import outage_basis
from theseus.engine.intent_effect import RANK

log = logging.getLogger(__name__)

# The access graph an articulation point splits: who can become or reach what, which code calls what, and
# which workflow uses which Action. Requirement and environment nodes are bookkeeping, not access.
LINKS = frozenset({*PATH_TYPES, "CALLS", "REQUESTS", "USES"})
SKIP_LABELS = frozenset({"Requirement", "Environment"})
TOP = 10
NOTE = (
    "Estimated from list prices (on-demand, before tax), counting only what the code declares: sizes, counts "
    "and storage. Anything billed by use (requests, gigabytes stored or sent) counts as 0 here."
)


def dependencies(state: GraphState, requirements: list[Requirement]) -> list[Dependency]:
    """Every code call (by workload, resource and access) and every config requirement, sorted."""
    labels = {n.id: set(n.labels) for n in state.rows.nodes}
    found: set[tuple[str, str, str, str]] = set()
    for edge in state.rows.edges:
        if edge.type != "CALLS" or RESOURCE not in labels.get(edge.dst, set()):
            continue
        for access in edge.grants or [str(edge.props.get("access", "read"))]:
            if access in ("read", "write"):
                found.add((edge.src, access, edge.dst, "code"))
    for r in requirements:
        if r.source == "config":
            found.add((r.principal, r.access, r.resource, "requirement"))
    return [Dependency(principal=p, access=a, resource=r, source=s) for p, a, r, s in sorted(found)]  # type: ignore[arg-type]


def _routes(paths: list[PathRecord], dep: Dependency) -> list[PathRecord]:
    return [p for p in paths if p.target == dep.resource and dep.access in p.grants and not p.unknown]


def single_points(
    deps: list[Dependency], paths: dict[str, list[PathRecord]], top: int = TOP
) -> list[SinglePoint]:
    """The nodes on every route of at least one dependency, with the dependencies each would break; the ones
    the most different actors depend on first, then the most dependencies, then by ID. A dependency with no
    route has nothing to lose."""
    breaks: dict[str, list[Dependency]] = defaultdict(list)
    for dep in deps:
        routes = _routes(paths.get(dep.principal, []), dep)
        if not routes:
            log.info("%s has no route to %s %s; nothing to lose", dep.principal, dep.access, dep.resource)
            continue
        shared = set(routes[0].route[1:-1])
        for route in routes[1:]:
            shared &= set(route.route[1:-1])
        for node in shared:
            breaks[node].append(dep)
    ranked = sorted(breaks.items(), key=lambda kv: (-len({d.principal for d in kv[1]}), -len(kv[1]), kv[0]))
    return [SinglePoint(id=node, breaks=found) for node, found in ranked[:top]]


def _graph(nodes: list[NodeRow], edges: list[EdgeRow]) -> dict[str, set[str]]:
    keep = {n.id for n in nodes if not set(n.labels) & SKIP_LABELS}
    adjacent: dict[str, set[str]] = {n: set() for n in sorted(keep)}
    for e in edges:
        if e.type in LINKS and e.src in keep and e.dst in keep and e.src != e.dst:
            adjacent[e.src].add(e.dst)
            adjacent[e.dst].add(e.src)
    return adjacent


def _cut_vertices(adjacent: dict[str, set[str]]) -> set[str]:
    """Tarjan's articulation points, iteratively, so a deep graph cannot overflow the stack."""
    order: dict[str, int] = {}
    low: dict[str, int] = {}
    found: set[str] = set()
    for root in adjacent:
        if root in order:
            continue
        order[root] = low[root] = len(order)
        children = 0
        stack: list[tuple[str, str | None, list[str]]] = [(root, None, sorted(adjacent[root]))]
        while stack:
            node, parent, todo = stack[-1]
            if todo:
                nxt = todo.pop()
                if nxt == parent:
                    continue
                if nxt in order:
                    low[node] = min(low[node], order[nxt])
                    continue
                order[nxt] = low[nxt] = len(order)
                if node == root:
                    children += 1
                stack.append((nxt, node, sorted(adjacent[nxt])))
                continue
            stack.pop()
            if parent is not None:
                low[parent] = min(low[parent], low[node])
                if parent != root and low[node] >= order[parent]:
                    found.add(parent)
        if children > 1:
            found.add(root)
    return found


def _pieces(adjacent: dict[str, set[str]], removed: str) -> list[int]:
    seen = {removed}
    sizes: list[int] = []
    for start in sorted(adjacent[removed]):
        if start in seen:
            continue
        seen.add(start)
        todo, size = [start], 0
        while todo:
            node = todo.pop()
            size += 1
            for nxt in adjacent[node]:
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        sizes.append(size)
    return sorted(sizes, reverse=True)


def articulation_points(nodes: list[NodeRow], edges: list[EdgeRow], top: int = TOP) -> list[Articulation]:
    """The nodes whose removal splits the access graph, each with the pieces left; the most nodes cut off
    from the largest piece first, then by ID."""
    adjacent = _graph(nodes, edges)
    found = []
    for node in _cut_vertices(adjacent):
        pieces = _pieces(adjacent, node)
        found.append(Articulation(id=node, cut_off=sum(pieces[1:]), pieces=pieces))
    return sorted(found, key=lambda a: (-a.cut_off, a.id))[:top]


def reach(
    paths: dict[str, list[PathRecord]],
    actors: list[str],
    nodes: dict[str, NodeRow],
    requirements: list[Requirement],
) -> list[Reach]:
    """Each actor's sensitive targets, and which of them a requirement of that actor names; the actors
    reaching the most regulated, then sensitive, data first."""
    named = {(r.principal, r.resource) for r in requirements}
    found: list[Reach] = []
    for actor in actors:
        routes = [p for p in paths.get(actor, []) if nodes[p.target].sensitive and not p.unknown]
        if not routes:
            continue
        targets = sorted(
            {p.target for p in routes}, key=lambda t: (RANK.get(nodes[t].sensitivity or "", len(RANK)), t)
        )
        found.append(
            Reach(
                actor=actor,
                targets=targets,
                required=[t for t in targets if (actor, t) in named],
                worst=nodes[targets[0]].sensitivity,
                paths=len(routes),
            )
        )
    return sorted(
        found,
        key=lambda r: (
            -sum(1 for t in r.targets if nodes[t].sensitivity == "regulated"),
            -len(r.targets),
            r.actor,
        ),
    )


def unreached(state: GraphState, paths: dict[str, list[PathRecord]]) -> list[str]:
    """Data resources that no actor has a valid path to and no code calls, sorted."""
    reached = {p.target for ps in paths.values() for p in ps}
    called = {e.dst for e in state.rows.edges if e.type == "CALLS"}
    return sorted(
        n.id for n in state.rows.nodes if RESOURCE in n.labels and n.id not in reached and n.id not in called
    )


def cost_summary(lines: list[CostLine], state: GraphState, gone: list[str]) -> CostSummary:
    """The total, the lines by cost, and the savings: each unreached resource with its own line's cost."""
    by_address = {line.address: line for line in lines}
    addresses = {n.id: str(n.props.get("address", "")) for n in state.rows.nodes}
    savings = []
    for node in gone:
        line = by_address.get(addresses.get(node, ""))
        cost = line.monthly_usd if line is not None else 0.0
        savings.append(
            Saving(
                id=node,
                monthly_usd=cost,
                reason="No person, workflow or service can reach it, and no code calls it.",
            )
        )
    savings.sort(key=lambda s: (-s.monthly_usd, s.id))
    return CostSummary(
        monthly_usd=round(sum(line.monthly_usd for line in lines), 2),
        lines=sorted(lines, key=lambda line: (-line.monthly_usd, line.address)),
        savings=savings,
        savings_usd=round(sum(s.monthly_usd for s in savings), 2),
        note=NOTE,
    )


def posture(
    store: GraphStore,
    state: GraphState,
    requirements: list[Requirement],
    actors: list[str],
    cost: list[CostLine],
    outages: list[OutageMap] | None = None,
) -> Posture:
    """The posture of a loaded graph: reach for these actors, single points of failure for every code call
    and config requirement, articulation points, unreached data, the cost with its savings, and the basis an
    outage is answered from (the adapters' `outages` and each dependency's routes)."""
    nodes = {n.id: n for n in state.rows.nodes}
    deps = dependencies(state, requirements)
    principals = sorted(set(actors) | {d.principal for d in deps if d.principal in nodes})
    analysis = analyze(store, state, requirements, principals)
    gone = unreached(state, analysis.paths)
    found = Posture(
        reach=reach(analysis.paths, actors, nodes, requirements),
        dependencies=len(deps),
        single_points=single_points(deps, analysis.paths),
        articulation=articulation_points(state.rows.nodes, state.rows.edges),
        unreached=gone,
        cost=cost_summary(cost, state, gone),
    )
    named = {r.actor for r in found.reach} | {t for r in found.reach for t in r.targets}
    named |= {s.id for s in found.single_points} | {a.id for a in found.articulation} | set(gone)
    named |= {n for s in found.single_points for d in s.breaks for n in (d.principal, d.resource)}
    info = {
        n: NodeInfo(category=nodes[n].category, sensitivity=nodes[n].sensitivity)
        for n in sorted(named)
        if n in nodes
    }
    routes = [
        DependencyRoutes(
            dependency=d, routes=sorted(p.route for p in _routes(analysis.paths.get(d.principal, []), d))
        )
        for d in deps
    ]
    outage = outage_basis(state, routes, outages or [], cost)
    return found.model_copy(update={"nodes": info, "outage": outage})
