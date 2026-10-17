"""Betweenness on tiny graphs, and the choke points the engine reports from it (03-graph.md)."""

from __future__ import annotations

from theseus.contracts.engine import GraphState, World
from theseus.contracts.result import ChokePoint, EdgeRow, Evidence, GraphRows, NodeRow
from theseus.graph.algos import brandes, choke_points
from theseus.graph.store import MemoryStore


def node(nid: str, *labels: str) -> NodeRow:
    return NodeRow(id=nid, name=nid, labels=["Node", *labels])


def edge(n: int, src: str, dst: str, etype: str = "CAN_ASSUME") -> EdgeRow:
    return EdgeRow(
        eid=f"e{n}",
        type=etype,
        src=src,
        dst=dst,
        kind="configured",
        evidence=[Evidence(address="x", file="t.tf", line=n)],
    )  # type: ignore[arg-type]


def rows(names: str, links: list[tuple[str, str]], roles: str = "") -> GraphRows:
    nodes = [node(n, "Role" if n in roles.split() else "Principal") for n in names.split()]
    return GraphRows(nodes=nodes, edges=[edge(i, a, b) for i, (a, b) in enumerate(links, 1)])


def scores(found: list) -> dict[str, float]:
    return {c.id: c.score for c in found}


def test_a_line_scores_the_inner_nodes_by_the_pairs_they_join() -> None:
    found = scores(brandes(rows("a b c d", [("a", "b"), ("b", "c"), ("c", "d")])))
    assert found == {"a": 0, "b": 2, "c": 2, "d": 0}


def test_two_equal_routes_split_the_credit() -> None:
    links = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]
    assert scores(brandes(rows("a b c d", links))) == {"a": 0, "b": 0.5, "c": 0.5, "d": 0}


def test_edges_follow_their_direction_and_other_types_do_not_count() -> None:
    graph = rows("a b c", [("b", "a"), ("b", "c")])
    assert scores(brandes(graph))["b"] == 0
    uses = GraphRows(nodes=graph.nodes, edges=[edge(1, "a", "b", "USES"), edge(2, "b", "c", "USES")])
    assert scores(brandes(uses)) == {"a": 0, "b": 0, "c": 0}


def test_parallel_edges_count_once() -> None:
    links = [("a", "b"), ("a", "b"), ("b", "c")]
    assert scores(brandes(rows("a b c", links)))["b"] == 1


def test_highest_score_first_then_by_id() -> None:
    links = [("a", "b"), ("b", "c"), ("a", "z"), ("z", "c")]
    found = brandes(rows("a b c z", links))
    assert [c.id for c in found] == ["b", "z", "a", "c"]


def state_of(graph: GraphRows) -> tuple[MemoryStore, GraphState]:
    store = MemoryStore()
    store.load("g", graph)
    return store, GraphState(name="g", world=World.model_construct(), rows=graph)


def test_choke_points_report_only_roles_and_only_the_top() -> None:
    links = [("a", "r1"), ("r1", "r2"), ("r2", "r3"), ("r3", "d")]
    store, state = state_of(rows("a r1 r2 r3 d", links, roles="r1 r2 r3"))
    assert [c.id for c in choke_points(store, state)] == ["r2", "r1", "r3"]
    assert [c.id for c in choke_points(store, state, top=1)] == ["r2"]


def test_choke_points_of_a_graph_with_no_paths_are_empty() -> None:
    store, state = state_of(rows("r1 r2", [], roles="r1 r2"))
    assert [c.score for c in choke_points(store, state)] == [0, 0]


def test_choke_points_do_not_depend_on_the_store_algorithm() -> None:
    class Estimating(MemoryStore):
        def betweenness(self, graph: str) -> list:
            return [ChokePoint(id="r1", score=0.0), ChokePoint(id="r2", score=99.0)]

    links = [("a", "r1"), ("r1", "r2"), ("r2", "d")]
    graph = rows("a r1 r2 d", links, roles="r1 r2")
    store = Estimating()
    store.load("g", graph)
    state = GraphState(name="g", world=World.model_construct(), rows=graph)
    assert [(c.id, c.score) for c in choke_points(store, state)] == [("r1", 2), ("r2", 2)]


def test_memory_store_ranks_every_node() -> None:
    store, _ = state_of(rows("a b c", [("a", "b"), ("b", "c")]))
    assert scores(store.betweenness("g")) == {"a": 0, "b": 1, "c": 0}
