"""Directed max flow and residual reachability over canonical FLOW rows."""

from __future__ import annotations

import logging
from collections import defaultdict, deque

from theseus.contracts.engine import EdgeFlow, FlowResult, FlowRow, GraphStore
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
