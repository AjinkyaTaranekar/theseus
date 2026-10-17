"""Minimum cuts on directed networks, including reverse residual steps."""

from __future__ import annotations

import pytest

from theseus.contracts.engine import FlowResult, FlowRow
from theseus.graph.algos import edmonds_karp, reachable


def rows(edges: list[tuple[str, str, int]]) -> list[FlowRow]:
    return [FlowRow(src=a, dst=b, capacity=c, eids=[str(i)]) for i, (a, b, c) in enumerate(edges)]


@pytest.mark.parametrize(
    "edges,sources,sinks,value",
    [
        ([("s", "a", 1), ("a", "t", 2), ("s", "b", 1), ("b", "t", 2)], ["s"], ["t"], 2),
        ([("s", "t", 1_000_000)], ["s"], ["t"], 1_000_000),
        ([("s", "a", 2), ("a", "t", 1), ("a", "u", 1)], ["s"], ["t", "u"], 2),
        ([("s", "t", 2), ("u", "t", 3)], ["s", "u"], ["t"], 5),
        ([("s", "a", 1), ("a", "s", 2), ("a", "t", 1)], ["s"], ["t"], 1),
        ([("s", "a", 1)], ["s"], ["t"], 0),
    ],
)
def test_flow_equals_capacity_of_residual_cut(
    edges: list[tuple[str, str, int]], sources: list[str], sinks: list[str], value: int
) -> None:
    network = rows(edges)
    flow = edmonds_karp(sources, sinks, network)
    assert flow.value == value
    reached = reachable(sources, network, flow)
    assert not set(sinks) & reached
    assert sum(r.capacity for r in network if r.src in reached and r.dst not in reached) == value
    assert edmonds_karp(sources, sinks, list(reversed(network))) == flow


def test_reverse_steps_can_cancel_an_earlier_augmenting_path() -> None:
    network = rows(
        [
            ("s", "a", 1),
            ("s", "b", 1),
            ("a", "c", 1),
            ("a", "d", 1),
            ("b", "c", 1),
            ("c", "t", 1),
            ("d", "t", 1),
        ]
    )
    assert edmonds_karp(["s"], ["t"], network).value == 2


def test_parallel_grants_are_summed_and_all_cut_edges_keep_evidence() -> None:
    from theseus.contracts.engine import GraphState, World
    from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow
    from theseus.engine.analyze import analyze
    from theseus.engine.mincut import min_cut
    from theseus.graph.store import MemoryStore

    graph = GraphRows(
        nodes=[
            NodeRow(id="s", name="source", labels=["Node", "User"]),
            NodeRow(id="t", name="target", labels=["Node", "Resource"], sensitive=True),
        ],
        edges=[
            EdgeRow(
                eid=eid,
                src="s",
                dst="t",
                type="CAN",
                kind="configured",
                grants=[access],
                evidence=[Evidence(file="policy.tf", line=line, address="policy")],
            )
            for eid, access, line in [("read", "read", 1), ("write", "write", 2)]
        ],
    )
    state = GraphState(name="tiny", world=World(root="tiny", iac="test"), rows=graph)
    store = MemoryStore()
    store.load(state.name, graph)
    analysis = analyze(store, state, [], ["s"])
    result = min_cut(store, state, analysis, ["s"], [])
    assert result.value == 2 and result.cuttable
    assert [edge.eid for edge in result.cut] == ["read", "write"]
    assert [edge.evidence for edge in result.cut] == ["policy.tf:1:policy", "policy.tf:2:policy"]


def test_failure_uses_identical_rows_and_logs_the_fallback(caplog: pytest.LogCaptureFixture) -> None:
    from theseus.errors import GraphError
    from theseus.graph.algos import max_flow
    from theseus.graph.store import MemoryStore

    class Unavailable(MemoryStore):
        def max_flow(
            self, graph: str, sources: list[str], sinks: list[str], rows: list[FlowRow]
        ) -> FlowResult:
            raise GraphError("procedure unavailable")

    network = rows([("s", "t", 3)])
    assert max_flow(Unavailable(), "tiny", ["s"], ["t"], network).value == 3
    assert "using Edmonds-Karp" in caplog.text


def test_no_sinks_returns_zero_and_overlapping_terminals_are_removed() -> None:
    from theseus.graph.algos import max_flow
    from theseus.graph.store import MemoryStore

    assert max_flow(MemoryStore(), "unused", ["s"], ["s"], []).value == 0


def test_required_paths_protect_shared_access_and_unknown_paths_do_not() -> None:
    from tests.golden.conftest import deps_for, world
    from theseus.contracts.schema import BIG
    from theseus.engine.analyze import analyze
    from theseus.engine.mincut import capacities
    from theseus.engine.pipeline import actors, config_requirements, prepare_state

    deps = deps_for("intern")
    state, _ = prepare_state(world("intern", "head"), "head", deps)
    deps.store.load(state.name, state.rows)
    reqs = config_requirements(state.world)
    analysis = analyze(deps.store, state, reqs, actors(state))
    caps = capacities(state.rows, analysis, reqs)
    protected = {
        (s.src, s.dst)
        for req in reqs
        for p in analysis.paths[req.principal]
        if p.target == req.resource and req.access in p.grants and not p.unknown
        for s in p.steps
    }
    assert protected
    assert all(r.capacity >= BIG for r in caps if (r.src, r.dst) in protected)
    assert all(
        e.type not in {"CALLS", "USES", "REQUESTS", "HAS_ENV"}
        for r in caps
        for eid in r.eids
        for e in state.rows.edges
        if e.eid == eid
    )
    unknown = analysis.model_copy(
        update={
            "paths": {
                actor: [p.model_copy(update={"unknown": True}) for p in paths]
                for actor, paths in analysis.paths.items()
            }
        }
    )
    weak = capacities(state.rows, unknown, reqs)
    assert any(r.capacity < BIG and (r.src, r.dst) in protected for r in weak)


def test_falkor_store_writes_flow_rows_and_decodes_sparse_unordered_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from theseus.graph import queries
    from theseus.graph.store import FalkorStore

    calls: list[tuple[str, object]] = []

    def query(self: FalkorStore, graph: str, cypher: str, params: object = None) -> list:
        calls.append((cypher, params))
        return [[3.0, [["b"], ["a"]], [2.0, 1.0]]] if cypher == queries.Q_MAXFLOW else []

    monkeypatch.setattr(FalkorStore, "_query", query)
    store = FalkorStore(None)  # type: ignore[arg-type]
    network = rows([("s", "t", 3)])
    result = store.max_flow("tiny", ["s"], ["t"], network)
    assert result.value == 3
    assert [f.eids for f in result.flows] == [["a"], ["b"]]
    assert [f.flow for f in result.flows] == [1, 2]
    assert calls == [
        (queries.Q_SET_FLOW, {"rows": [r.model_dump() for r in network]}),
        (queries.Q_MAXFLOW, {"sources": ["s"], "sinks": ["t"]}),
    ]


def test_intent_words_cannot_protect_sensitive_access() -> None:
    from tests.golden.test_mincut_fixtures import setup
    from theseus.contracts.result import Requirement
    from theseus.engine.analyze import analyze
    from theseus.engine.mincut import capacities
    from theseus.engine.pipeline import actors
    from theseus.graph.store import MemoryStore

    state, reqs, _ = setup("compromised-action")
    store = MemoryStore()
    store.load(state.name, state.rows)
    injected = Requirement(
        id="I1",
        principal="workflow:demo-org/docs-site/preview.yml",
        resource="db:customer-db",
        access="read",
        source="intent",
    )
    analysis = analyze(store, state, reqs + [injected], actors(state))
    assert capacities(state.rows, analysis, reqs + [injected]) == capacities(state.rows, analysis, reqs)


def test_assume_requirements_protect_traversal_paths_without_a_resource_grant() -> None:
    from theseus.contracts.engine import Analysis
    from theseus.contracts.result import EdgeRow, GraphRows, Requirement
    from theseus.contracts.schema import BIG
    from theseus.engine.mincut import capacities

    graph = GraphRows(
        edges=[
            EdgeRow(eid="membership", src="user:a", dst="group:g", type="MEMBER_OF", kind="configured"),
            EdgeRow(eid="assume", src="group:g", dst="role:r", type="CAN_ASSUME", kind="configured"),
            EdgeRow(eid="unknown", src="user:a", dst="role:r", type="CAN_ASSUME", kind="unknown"),
        ]
    )
    req = Requirement(id="R1", principal="user:a", resource="role:r", access="assume", source="config")
    caps = {r.eids[0]: r.capacity for r in capacities(graph, Analysis(), [req])}
    assert caps == {"membership": BIG, "assume": BIG, "unknown": 1}


def test_role_owned_requirement_is_protected_even_when_role_is_not_an_actor() -> None:
    from theseus.contracts.engine import Analysis
    from theseus.contracts.result import EdgeRow, GraphRows, Requirement
    from theseus.contracts.schema import BIG
    from theseus.engine.mincut import capacities

    graph = GraphRows(
        edges=[
            EdgeRow(
                eid="required",
                src="role:shared",
                dst="data:records",
                type="CAN",
                kind="configured",
                grants=["read"],
            ),
        ]
    )
    requirement = Requirement(
        id="R1", principal="role:shared", resource="data:records", access="read", source="config"
    )
    assert capacities(graph, Analysis(), [requirement])[0].capacity == BIG


def test_read_requirement_does_not_protect_a_parallel_write_only_grant() -> None:
    from theseus.contracts.engine import Analysis
    from theseus.contracts.result import EdgeRow, GraphRows, Requirement
    from theseus.contracts.schema import BIG
    from theseus.engine.mincut import capacities

    graph = GraphRows(
        edges=[
            EdgeRow(
                eid="read",
                src="role:shared",
                dst="data:records",
                type="CAN",
                kind="configured",
                grants=["read"],
            ),
            EdgeRow(
                eid="write",
                src="role:shared",
                dst="data:records",
                type="CAN",
                kind="configured",
                grants=["write"],
            ),
        ]
    )
    requirement = Requirement(
        id="R1", principal="role:shared", resource="data:records", access="read", source="config"
    )
    assert capacities(graph, Analysis(), [requirement])[0].capacity == BIG + 1


def test_every_four_node_unit_network_matches_an_independent_cut_oracle() -> None:
    from itertools import product

    nodes = ["s", "a", "b", "t"]
    pairs = [(src, dst) for src in nodes for dst in nodes if src != dst]
    partitions = [{"s"}, {"s", "a"}, {"s", "b"}, {"s", "a", "b"}]
    for enabled in product((False, True), repeat=len(pairs)):
        edges = [(src, dst, 1) for (src, dst), keep in zip(pairs, enabled, strict=True) if keep]
        network = rows(edges)
        expected = min(
            sum(c for src, dst, c in edges if src in part and dst not in part) for part in partitions
        )
        actual = edmonds_karp(["s"], ["t"], network)
        assert actual.value == expected, edges
        reached = reachable(["s"], network, actual)
        assert "t" not in reached
        assert sum(r.capacity for r in network if r.src in reached and r.dst not in reached) == expected


def test_a_cut_without_source_evidence_is_refused_with_a_graph_error() -> None:
    from theseus.contracts.engine import Analysis, GraphState, World
    from theseus.contracts.result import EdgeRow, GraphRows, PathRecord
    from theseus.engine.mincut import min_cut
    from theseus.errors import GraphError
    from theseus.graph.store import MemoryStore

    graph = GraphRows(edges=[EdgeRow(eid="grant", src="s", dst="t", type="CAN", kind="configured")])
    state = GraphState(name="tiny", world=World(root="tiny", iac="test"), rows=graph)
    analysis = Analysis(dangerous=[PathRecord(id="path", actor="s", target="t", grants=["read"], steps=[])])
    store = MemoryStore()
    store.load(state.name, graph)
    with pytest.raises(GraphError, match="evidence"):
        min_cut(store, state, analysis, ["s"], [])


@pytest.mark.parametrize("sources", [["user:a"], ["user:a", "user:b"]])
def test_pipeline_combines_opened_actors_and_cites_cut_edges_outside_the_selected_path(
    monkeypatch: pytest.MonkeyPatch, sources: list[str]
) -> None:
    from tests.golden.conftest import deps_for
    from theseus.contracts.engine import GraphState, World
    from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow
    from theseus.engine import pipeline

    nodes = [NodeRow(id=actor, name=actor, labels=["Node", "User"]) for actor in sources]
    nodes.append(NodeRow(id="data:t", name="target", labels=["Node", "Resource"], sensitive=True))
    edges = [
        EdgeRow(
            eid=f"{actor}-{access}",
            src=actor,
            dst="data:t",
            type="CAN",
            kind="configured",
            grants=[access],
            evidence=[Evidence(file="grants.tf", line=i + 1, address=actor, part=access)],
        )
        for i, actor in enumerate(sources)
        for access in ["read", "write"]
    ]
    worlds = {side: World(root=side, iac="test") for side in ["base", "head"]}
    states = {
        side: GraphState(
            name=side, world=worlds[side], rows=GraphRows(nodes=nodes, edges=edges if side == "head" else [])
        )
        for side in worlds
    }
    monkeypatch.setattr(pipeline, "prepare_state", lambda world, side, deps: (states[side], 0))
    monkeypatch.setattr(pipeline, "read_intent", lambda *args: None)
    result = pipeline.run_pr(worlds["base"], worlds["head"], "", "", deps_for("intern"))
    assert result.min_cut is not None
    assert result.min_cut.sources == sorted(sources)
    assert result.min_cut.sinks == ["data:t"]
    assert result.min_cut.value == 2 * len(sources)
    assert len(result.min_cut.cut) == 2 * len(sources)
    assert all(edge.evidence in result.evidence for edge in result.min_cut.cut)
