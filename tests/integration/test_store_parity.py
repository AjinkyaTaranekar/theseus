"""FalkorStore and MemoryStore answer the canonical queries identically on every fixture (task E3).

Against the FalkorDB in .env, or CI's pinned container. Every graph this test makes is deleted afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from tests.golden.conftest import FIXTURES, deps_for, world
from theseus.config import get_settings
from theseus.contracts.engine import GraphState
from theseus.engine.analyze import analyze
from theseus.engine.pipeline import actors, config_requirements, prepare_state
from theseus.graph.client import get_client
from theseus.graph.store import DOCS, FalkorStore, MemoryStore

pytestmark = pytest.mark.falkordb

PREFIX = f"parity__{os.getpid()}__"
SIDES = sorted(
    (scenario.name, side)
    for scenario in FIXTURES.iterdir()
    if scenario.is_dir()
    for side in ("base", "head")
    if (scenario / side).is_dir()
)


@pytest.fixture(scope="module")
def falkor() -> Iterator[FalkorStore]:
    store = FalkorStore(get_client(get_settings()))
    yield store
    for name in store.list_graphs():
        if name.startswith(PREFIX):
            store.delete(name)


@pytest.mark.parametrize("scenario,side", SIDES)
def test_both_stores_find_the_same_routes_and_the_same_analysis(
    falkor: FalkorStore, scenario: str, side: str
) -> None:
    deps = deps_for(scenario)
    prepared, _ = prepare_state(world(scenario, side), side, deps)
    name = f"{PREFIX}{scenario}-{side}"
    state = GraphState(name=name, world=prepared.world, rows=prepared.rows)
    memory = MemoryStore()
    memory.load(name, state.rows)
    falkor.load(name, state.rows)
    who = actors(state)
    for actor in who:
        assert falkor.paths(name, actor) == memory.paths(name, actor), actor
    requirements = config_requirements(state.world)
    assert analyze(falkor, state, requirements, who) == analyze(memory, state, requirements, who)
    assert falkor.calls(name) == memory.calls(name)
    assert falkor.unused_grants(name) == memory.unused_grants(name)
    action = "action:demo-thirdparty/file-diff"
    assert falkor.workflows_using(name, action) == memory.workflows_using(name, action)
    # The review page reads the graph back exactly as the engine reasoned on it.
    assert falkor.view(name) == memory.view(name)


def test_copy_is_independent_and_delete_is_quiet(falkor: FalkorStore) -> None:
    deps = deps_for("intern")
    state, _ = prepare_state(world("intern", "base"), "base", deps)
    src, dst = f"{PREFIX}copy-src", f"{PREFIX}copy-dst"
    falkor.load(src, state.rows)
    falkor.copy(src, dst)
    assert {src, dst} <= set(falkor.list_graphs())
    falkor.delete(dst)
    falkor.delete(dst)
    assert dst not in falkor.list_graphs() and falkor.paths(src, "user:sam-support")


def test_a_document_round_trips_next_to_the_graphs(falkor: FalkorStore) -> None:
    key = f"{PREFIX}doc"
    try:
        assert falkor.get_doc(key) is None
        falkor.put_doc(key, '{"a": 1}')
        falkor.put_doc(key, '{"a": 2}')
        assert falkor.get_doc(key) == '{"a": 2}'
    finally:
        falkor._query(DOCS, "MATCH (d:Doc {key: $key}) DELETE d", {"key": key})


def test_the_view_leaves_out_flow_edges_the_engine_writes(falkor: FalkorStore) -> None:
    deps = deps_for("intern")
    state, _ = prepare_state(world("intern", "head"), "head", deps)
    name = f"{PREFIX}flow"
    memory = MemoryStore()
    memory.load(name, state.rows)
    falkor.load(name, state.rows)
    falkor._query(
        name,
        "MATCH (a:Node {id: 'user:priya-intern'}), (b:Node {id: 'group:support-engineers'}) "
        "CREATE (a)-[:FLOW {eids: ['x'], capacity: 1}]->(b)",
    )
    assert falkor.view(name) == memory.view(name)
