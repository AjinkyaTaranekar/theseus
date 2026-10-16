"""MemoryStore answers Q_PATHS exactly as the Cypher in 03-graph.md does, on small graphs."""

from __future__ import annotations

import pytest

from theseus.contracts.engine import GraphDelta
from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow
from theseus.errors import GraphError
from theseus.graph.store import MemoryStore

EV = [Evidence(address="x", file="terraform/x.tf", line=1)]


def node(nid: str, *labels: str, category: str | None = None) -> NodeRow:
    return NodeRow(id=nid, name=nid, labels=["Node", *labels], category=category)  # type: ignore[arg-type]


def edge(eid: str, etype: str, src: str, dst: str, grants: list[str] | None = None) -> EdgeRow:
    return EdgeRow(eid=eid, type=etype, src=src, dst=dst, kind="configured", grants=grants or [], evidence=EV)  # type: ignore[arg-type]


ROWS = GraphRows(
    nodes=[
        node("user:u", "Principal", "User"),
        node("group:g", "Principal", "Group"),
        node("role:a", "Principal", "Role"),
        node("role:b", "Principal", "Role"),
        node("secret:s", "Resource", "Secret", category="Secret"),
        node("db:d", "Resource", "Database", category="Database"),
        node("s3://b/x/", "Resource", "ObjectStorage", category="ObjectStorage"),
        node("workload:w", "Principal", "Workload"),
    ],
    edges=[
        edge("e1", "MEMBER_OF", "user:u", "group:g"),
        edge("e2", "CAN_ASSUME", "group:g", "role:a"),
        edge("e3", "CAN", "role:a", "secret:s", ["read"]),
        edge("e4", "UNLOCKS", "secret:s", "db:d", ["read", "write"]),
        edge("e5", "CAN_ASSUME", "role:a", "role:b"),
        edge("e6", "CAN_ASSUME", "role:b", "role:a"),
        edge("e7", "CAN", "role:b", "s3://b/x/", ["write"]),
        edge("e8", "CALLS", "workload:w", "secret:s", ["read"]),
        edge("e9", "RUNS_AS", "workload:w", "role:b"),
    ],
)


@pytest.fixture
def store() -> MemoryStore:
    s = MemoryStore()
    s.load("g", ROWS)
    return s


def test_q_paths_returns_every_route_to_a_resource_without_repeating_an_edge(store: MemoryStore) -> None:
    got = sorted(store.paths("g", "user:u"))
    assert got == sorted(
        [
            ["e1", "e2", "e3"],
            ["e1", "e2", "e3", "e4"],
            ["e1", "e2", "e5", "e7"],
            # The cycle a -> b -> a is walked once: Cypher never repeats a relationship, but revisits nodes.
            ["e1", "e2", "e5", "e6", "e3"],
            ["e1", "e2", "e5", "e6", "e3", "e4"],
        ]
    )
    # CALLS is not a path type; RUNS_AS is.
    assert sorted(store.paths("g", "workload:w")) == sorted(
        [["e9", "e7"], ["e9", "e6", "e3"], ["e9", "e6", "e3", "e4"], ["e9", "e6", "e5", "e7"]]
    )


def test_q_paths_stops_at_seven_edges() -> None:
    chain = [node(f"role:r{i}", "Principal", "Role") for i in range(9)]
    rows = GraphRows(
        nodes=[*chain, node("db:d", "Resource", category="Database")],
        edges=[edge(f"e{i}", "CAN_ASSUME", f"role:r{i}", f"role:r{i + 1}") for i in range(8)]
        + [edge("c6", "CAN", "role:r6", "db:d", ["read"]), edge("c7", "CAN", "role:r7", "db:d", ["read"])],
    )
    s = MemoryStore()
    s.load("chain", rows)
    assert s.paths("chain", "role:r0") == [["e0", "e1", "e2", "e3", "e4", "e5", "c6"]]


def test_load_copy_delete_and_list(store: MemoryStore) -> None:
    store.copy("g", "g-copy")
    assert store.list_graphs() == ["g", "g-copy"]
    store.apply_delta("g-copy", GraphDelta(remove_edges=[("role:a", "CAN", "secret:s")]))
    assert ["e1", "e2", "e3"] not in store.paths("g-copy", "user:u")
    assert ["e1", "e2", "e3"] in store.paths("g", "user:u")  # the copy is independent
    store.delete("g-copy")
    store.delete("never-there")
    assert store.list_graphs() == ["g"]
    with pytest.raises(GraphError, match="no graph"):
        store.paths("g-copy", "user:u")


def test_a_delta_adds_after_it_removes(store: MemoryStore) -> None:
    store.apply_delta(
        "g",
        GraphDelta(
            remove_nodes=["s3://b/x/"],
            add_nodes=[node("s3://b/y/", "Resource", category="ObjectStorage")],
            add_edges=[edge("n1", "CAN", "role:a", "s3://b/y/", ["read"])],
        ),
    )
    routes = store.paths("g", "user:u")
    assert ["e1", "e2", "n1"] in routes and not [r for r in routes if "e7" in r]


def test_the_usage_queries(store: MemoryStore) -> None:
    sensitive = ROWS.model_copy(
        update={"nodes": [n.model_copy(update={"sensitive": n.id == "secret:s"}) for n in ROWS.nodes]}
    )
    store.load("g", sensitive)
    assert [(c.workload, c.resource, c.access) for c in store.calls("g")] == [
        ("workload:w", "secret:s", "read")
    ]
    # workload:w runs as role:b, which has no CAN to the secret, so nothing is unused.
    assert store.unused_grants("g") == []
