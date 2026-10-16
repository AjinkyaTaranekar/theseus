"""Directed max flow and residual reachability over canonical FLOW rows."""

from __future__ import annotations

import logging
from collections import defaultdict, deque

from theseus.contracts.engine import EdgeFlow, FlowResult, FlowRow, GraphState, GraphStore
from theseus.contracts.result import ChokePoint, GraphRows
from theseus.contracts.schema import PATH_TYPES
from theseus.errors import GraphError

log = logging.getLogger(__name__)


def _residual(
    rows: list[FlowRow], flows: dict[tuple[str, ...], float]
) -> dict[str, list[tuple[str, int, int, float]]]:
    result: dict[str, list[tuple[str, int, int, float]]] = defaultdict(list)
    for i, row in enumerate(rows):
        flow = flows.get(tuple(row.eids), 0)
        if row.capacity > flow:
            result[row.src].append((row.dst, i, 1, row.capacity - flow))
        if flow > 0:
            result[row.dst].append((row.src, i, -1, flow))
    return result


def reachable(sources: list[str], rows: list[FlowRow], result: FlowResult) -> set[str]:
    """Nodes reachable from the sources by positive residual capacity."""
    residual = _residual(rows, {tuple(f.eids): f.flow for f in result.flows})
    seen = set(sources)
    queue = deque(sorted(seen))
    while queue:
        for dst, _, _, _ in residual.get(queue.popleft(), []):
            if dst not in seen:
                seen.add(dst)
                queue.append(dst)
    return seen


def edmonds_karp(sources: list[str], sinks: list[str], rows: list[FlowRow]) -> FlowResult:
    """Maximum directed flow, including independent flows on antiparallel edges."""
    if set(sources) & set(sinks):
        raise GraphError("flow sources and sinks must not overlap")
    rows = sorted(rows, key=lambda r: (r.src, r.dst, r.eids))
    flows = {tuple(r.eids): 0.0 for r in rows}
    value = 0.0
    targets = set(sinks)
    while sources and targets:
        residual = _residual(rows, flows)
        seen = set(sources)
        queue = deque(sorted(seen))
        parents: dict[str, tuple[str, int, int, float]] = {}
        end = None
        while queue and end is None:
            src = queue.popleft()
            for dst, index, direction, available in residual.get(src, []):
                if dst in seen:
                    continue
                seen.add(dst)
                parents[dst] = (src, index, direction, available)
                if dst in targets:
                    end = dst
                    break
                queue.append(dst)
        if end is None:
            break
        path = []
        here = end
        while here in parents:
            parent = parents[here]
            path.append(parent)
            here = parent[0]
        amount = min(p[3] for p in path)
        for _, index, direction, _ in path:
            flows[tuple(rows[index].eids)] += direction * amount
        value += amount
    return FlowResult(
        value=value, flows=[EdgeFlow(eids=list(k), flow=v) for k, v in sorted(flows.items()) if v]
    )


def max_flow(
    store: GraphStore, graph: str, sources: list[str], sinks: list[str], caps: list[FlowRow]
) -> FlowResult:
    """The store's flow, or Edmonds-Karp on identical rows when its algorithm fails."""
    sources, sinks = sorted(set(sources)), sorted(set(sinks) - set(sources))
    if not sources or not sinks:
        return FlowResult(value=0)
    try:
        return store.max_flow(graph, sources, sinks, caps)
    except GraphError:
        log.warning("max flow failed for %s; using Edmonds-Karp", graph, exc_info=True)
        return edmonds_karp(sources, sinks, caps)


def brandes(rows: GraphRows) -> list[ChokePoint]:
    """Betweenness of every node over the path-type edges: directed, unweighted, unnormalized, parallel edges
    counted once, as `algo.betweenness` scores them. Highest score first, then by ID."""
    nodes = sorted({n.id for n in rows.nodes})
    out: dict[str, list[str]] = {n: [] for n in nodes}
    for src, dst in sorted({(e.src, e.dst) for e in rows.edges if e.type in PATH_TYPES}):
        if src in out and dst in out:
            out[src].append(dst)
    score = dict.fromkeys(nodes, 0.0)
    for source in nodes:
        order: list[str] = []
        parents: dict[str, list[str]] = defaultdict(list)
        paths = dict.fromkeys(nodes, 0)
        paths[source] = 1
        depth = {source: 0}
        queue = deque([source])
        while queue:
            here = queue.popleft()
            order.append(here)
            for there in out[here]:
                if there not in depth:
                    depth[there] = depth[here] + 1
                    queue.append(there)
                if depth[there] == depth[here] + 1:
                    paths[there] += paths[here]
                    parents[there].append(here)
        credit = dict.fromkeys(nodes, 0.0)
        for there in reversed(order):
            for here in parents[there]:
                credit[here] += paths[here] / paths[there] * (1 + credit[there])
            if there != source:
                score[there] += credit[there]
    return sorted((ChokePoint(id=n, score=score[n]) for n in nodes), key=lambda c: (-c.score, c.id))


def choke_points(store: GraphStore, state: GraphState, top: int = 5) -> list[ChokePoint]:
    """The `top` roles with the highest betweenness, scores rounded to six places, highest first then by ID.

    The scores are exact (Brandes on the state's rows), whichever store holds the graph. FalkorDB's
    `algo.betweenness` is a sampled estimate that differs from run to run and can rank another node first
    (found on the compromised-action graph), and a ranking that changes between runs is not a fact the engine
    can report. `store.betweenness` still returns the store's own scores for anyone who wants them; `store`
    is part of the contract's signature and is not read here."""
    log.debug("choke points of %s computed exactly; %s's own estimate is not used", state.name, type(store))
    roles = {n.id for n in state.rows.nodes if "Role" in n.labels}
    rounded = (ChokePoint(id=c.id, score=round(c.score, 6)) for c in brandes(state.rows) if c.id in roles)
    return sorted(rounded, key=lambda c: (-c.score, c.id))[:top]
