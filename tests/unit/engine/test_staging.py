"""Staging to prod: a staging actor's path to sensitive prod data is flagged (04-engine.md 8 and 16)."""

from __future__ import annotations

from theseus.contracts.engine import Analysis, GraphState, World
from theseus.contracts.result import GraphRows, NodeRow, PathRecord, PathStep
from theseus.engine.staging import staging_to_prod


def node(nid: str, env: str = "prod", *, sensitive: bool = False, label: str = "Principal") -> NodeRow:
    return NodeRow(id=nid, name=nid, labels=["Node", label], env=env, sensitive=sensitive)  # type: ignore[arg-type]


def path(pid: str, actor: str, target: str) -> PathRecord:
    step = PathStep.model_validate({"from": actor, "to": target, "type": "CAN", "evidence": "t.tf:1:x"})
    return PathRecord(id=pid, actor=actor, target=target, grants=["read"], steps=[step])


NODES = [
    node("workflow:stg", "staging", label="Workflow"),
    node("workflow:prod", label="Workflow"),
    node("db:prod", sensitive=True, label="Resource"),
    node("db:stage", "staging", sensitive=True, label="Resource"),
    node("bucket:prod", label="Resource"),
]


def flagged(*paths: PathRecord) -> list[tuple[str, str, str]]:
    state = GraphState(name="g", world=World.model_construct(), rows=GraphRows(nodes=NODES, edges=[]))
    found = staging_to_prod(Analysis(dangerous=list(paths)), state)
    return [(s.actor, s.target, s.path_id) for s in found]


def test_a_staging_actor_reaching_sensitive_prod_data_is_flagged_with_its_path() -> None:
    assert flagged(path("p1", "workflow:stg", "db:prod")) == [("workflow:stg", "db:prod", "p1")]


def test_prod_actors_staging_data_and_non_sensitive_targets_are_not() -> None:
    assert (
        flagged(
            path("p1", "workflow:prod", "db:prod"),
            path("p2", "workflow:stg", "db:stage"),
            path("p3", "workflow:stg", "bucket:prod"),
        )
        == []
    )


def test_flags_are_sorted_by_actor_then_target() -> None:
    nodes = [*NODES, node("db:other", sensitive=True, label="Resource")]
    state = GraphState(name="g", world=World.model_construct(), rows=GraphRows(nodes=nodes, edges=[]))
    found = staging_to_prod(
        Analysis(dangerous=[path("p2", "workflow:stg", "db:prod"), path("p1", "workflow:stg", "db:other")]),
        state,
    )
    assert [s.target for s in found] == ["db:other", "db:prod"]
