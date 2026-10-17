"""Usage capacities and unused grants on tiny hand-built graphs (C3)."""

from __future__ import annotations

from theseus.contracts.engine import Analysis, GraphState, World
from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow, PathRecord, PathStep
from theseus.contracts.schema import BIG, USED
from theseus.engine.mincut import capacities
from theseus.engine.usage import unused_grants
from theseus.graph.store import MemoryStore

EV = [Evidence(address="hand_built", part="Sid", file="main.tf", line=3)]


def node(identifier: str, *labels: str, sensitive: bool = False) -> NodeRow:
    return NodeRow(
        id=identifier,
        name=identifier.split(":")[-1],
        labels=["Node", *labels],
        category="Database" if "Resource" in labels else None,
        sensitive=sensitive,
        sensitivity="regulated" if sensitive else "internal",
    )


def edge(eid: str, kind: str, src: str, dst: str, *grants: str) -> EdgeRow:
    return EdgeRow(
        eid=eid,
        type=kind,  # type: ignore[arg-type]
        src=src,
        dst=dst,
        kind="configured",
        grants=list(grants),
        evidence=EV,
    )


def rows() -> GraphRows:
    """w runs as r. r may read a and read/write b and read c. w calls a (read), b (write) and nothing of c."""
    return GraphRows(
        nodes=[
            node("workload:w", "Principal", "Workload"),
            node("role:r", "Principal", "Role"),
            node("db:a", "Resource", sensitive=True),
            node("db:b", "Resource", sensitive=True),
            node("db:c", "Resource", sensitive=True),
        ],
        edges=[
            edge("e1", "RUNS_AS", "workload:w", "role:r"),
            edge("e2", "CAN", "role:r", "db:a", "read"),
            edge("e3", "CAN", "role:r", "db:b", "read", "write"),
            edge("e4", "CAN", "role:r", "db:c", "read"),
            edge("e5", "CALLS", "workload:w", "db:a", "read"),
            edge("e6", "CALLS", "workload:w", "db:b", "write"),
        ],
    )


def cap(flows: list, src: str, dst: str) -> int:
    (row,) = [f for f in flows if (f.src, f.dst) == (src, dst)]
    return row.capacity


def test_a_grant_backed_by_a_call_that_shares_an_access_has_the_used_capacity() -> None:
    flows = capacities(rows(), Analysis(), [])
    assert cap(flows, "role:r", "db:a") == USED
    assert cap(flows, "role:r", "db:b") == USED  # the call writes, the grant allows read and write


def test_a_grant_no_call_uses_costs_one_and_a_structural_edge_costs_big() -> None:
    flows = capacities(rows(), Analysis(), [])
    assert cap(flows, "role:r", "db:c") == 1
    assert cap(flows, "workload:w", "role:r") == BIG


def test_a_call_for_another_access_does_not_back_the_grant() -> None:
    graph = rows()
    graph.edges = [e for e in graph.edges if e.eid != "e6"] + [
        edge("e7", "CALLS", "workload:w", "db:b", "read")
    ]
    graph.edges[2] = edge("e3", "CAN", "role:r", "db:b", "write")
    assert cap(capacities(graph, Analysis(), []), "role:r", "db:b") == 1


def test_a_call_from_a_workload_that_does_not_run_as_the_role_backs_nothing() -> None:
    graph = rows()
    graph.nodes.append(node("workload:other", "Principal", "Workload"))
    graph.edges.append(edge("e8", "CALLS", "workload:other", "db:c", "read"))
    assert cap(capacities(graph, Analysis(), []), "role:r", "db:c") == 1


def path(actor: str, *steps: tuple[str, str, str]) -> PathRecord:
    return PathRecord(
        id=f"{actor}->{steps[-1][2]}",
        actor=actor,
        target=steps[-1][2],
        grants=["read"],
        steps=[
            PathStep.model_validate({"from": s, "type": t, "to": d, "evidence": "main.tf:3:hand_built:Sid"})
            for s, t, d in steps
        ],
    )


def loaded() -> tuple[MemoryStore, GraphState]:
    store = MemoryStore()
    state = GraphState(name="usage", world=World(root="x", iac="terraform"), rows=rows())
    store.load(state.name, state.rows)
    return store, state


def test_unused_grants_are_the_sensitive_grants_no_call_backs_that_lie_on_a_dangerous_path() -> None:
    store, state = loaded()
    dangerous = [
        path("workload:w", ("workload:w", "RUNS_AS", "role:r"), ("role:r", "CAN", "db:c")),
        path("workload:w", ("workload:w", "RUNS_AS", "role:r"), ("role:r", "CAN", "db:a")),
    ]
    found = unused_grants(store, state, Analysis(dangerous=dangerous))
    assert [(g.workload, g.resource, g.access, g.eid) for g in found] == [
        ("workload:w", "db:c", "read", "e4")
    ]
    assert found[0].evidence == "main.tf:3:hand_built:Sid"


def test_a_grant_outside_every_dangerous_path_is_not_listed() -> None:
    store, state = loaded()
    assert unused_grants(store, state, Analysis()) == []


def test_each_access_of_an_unused_grant_is_listed_and_the_list_is_sorted() -> None:
    store, state = loaded()
    state.rows.edges = [e for e in state.rows.edges if e.type != "CALLS"]
    store.load(state.name, state.rows)
    dangerous = [
        path("workload:w", ("workload:w", "RUNS_AS", "role:r"), ("role:r", "CAN", f"db:{target}"))
        for target in "cba"
    ]
    found = unused_grants(store, state, Analysis(dangerous=dangerous))
    assert [(g.resource, g.access) for g in found] == [
        ("db:a", "read"),
        ("db:b", "read"),
        ("db:b", "write"),
        ("db:c", "read"),
    ]
