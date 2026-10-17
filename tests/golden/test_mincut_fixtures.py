"""E4's cuts on the human-reviewed intern and compromised Action fixtures."""

from __future__ import annotations

import json
import os

import pytest

from tests.golden.conftest import FIXTURES, deps_for, expected, world
from theseus.config import get_settings
from theseus.contracts.engine import GraphState
from theseus.contracts.result import Requirement
from theseus.engine.analyze import analyze
from theseus.engine.mincut import min_cut
from theseus.engine.pipeline import actors, config_requirements, prepare_state
from theseus.graph.client import get_client
from theseus.graph.store import FalkorStore, MemoryStore


def setup(scenario: str) -> tuple[GraphState, list[Requirement], list[str]]:
    deps = deps_for(scenario)
    side = "head" if scenario == "intern" else "base"
    state, _ = prepare_state(world(scenario, side), side, deps)
    state = state.model_copy(update={"name": f"e4_parity__{os.getpid()}__{scenario}"})
    requirements = config_requirements(state.world)
    if scenario == "intern":
        requirements.append(
            Requirement(
                id="I1",
                principal="user:priya-intern",
                access="read",
                resource="s3://demo-app-logs/",
                source="intent",
            )
        )
        sources = ["user:priya-intern"]
    else:
        advisory = json.loads((FIXTURES / scenario / "advisory.json").read_text())
        deps.store.load(state.name, state.rows)
        sources = sorted(
            use.workflow
            for use in deps.store.workflows_using(state.name, "action:" + advisory["action"])
            if use.version in advisory["affected_versions"]
        )
        assert len(sources) == 2
    return state, requirements, sources


@pytest.mark.parametrize("scenario", ["intern", "compromised-action"])
def test_fixture_cut_matches_the_answer_key(scenario: str) -> None:
    state, requirements, sources = setup(scenario)
    store = MemoryStore()
    store.load(state.name, state.rows)
    analysis = analyze(store, state, requirements, actors(state))
    cut = min_cut(store, state, analysis, sources, requirements)
    want = expected(scenario)["min_cut"]
    assert cut.cuttable == want["cuttable"]
    if "value_at_least" in want:
        assert cut.value >= want["value_at_least"]
    else:
        assert cut.value == want["value"]
    if scenario == "compromised-action":
        assert [[e.src, e.type, e.dst] for e in cut.cut] == want["cut"]
    assert all(e.evidence for e in cut.cut)


@pytest.mark.falkordb
@pytest.mark.parametrize("scenario", ["intern", "compromised-action"])
def test_falkordb_and_python_agree_on_fixture_flow(scenario: str) -> None:
    state, requirements, sources = setup(scenario)
    memory = MemoryStore()
    falkor = FalkorStore(get_client(get_settings()))
    memory.load(state.name, state.rows)
    try:
        falkor.load(state.name, state.rows)
        analysis = analyze(memory, state, requirements, actors(state))
        # Call the store directly so fallback cannot hide a failed FalkorDB algorithm.
        from theseus.engine.mincut import capacities

        python_cut = min_cut(memory, state, analysis, sources, requirements)
        actual = falkor.max_flow(
            state.name, sources, python_cut.sinks, capacities(state.rows, analysis, requirements)
        )
        assert actual.value == python_cut.value
        assert min_cut(falkor, state, analysis, sources, requirements) == python_cut
    finally:
        falkor.delete(state.name)


def test_pr_pipeline_returns_the_protected_intern_cut_and_resolves_every_citation() -> None:
    from tests.golden.conftest import pr_text
    from theseus.contracts.result import compare, project
    from theseus.engine.pipeline import run_pr

    result = run_pr(world("intern", "base"), world("intern", "head"), *pr_text("intern"), deps_for("intern"))
    assert compare(project(result), expected("intern"), keys=["min_cut"]) == []
    assert result.min_cut is not None
    assert result.min_cut.value == 1_000_000
    assert result.min_cut.sources == ["user:priya-intern"]
    assert all(edge.evidence in result.evidence for edge in result.min_cut.cut)


def test_pr_pipeline_leaves_cut_absent_when_no_path_opens() -> None:
    from tests.golden.conftest import pr_text
    from theseus.engine.pipeline import run_pr

    base = world("intern", "base")
    result = run_pr(base, base, *pr_text("intern"), deps_for("intern"))
    assert not result.opened
    assert result.min_cut is None


@pytest.mark.parametrize("suspicious,target", [(True, "s3://demo-app-logs/"), (False, "db:customer-db")])
def test_pr_pipeline_excludes_unapproved_intent_from_protected_capacities(
    monkeypatch: pytest.MonkeyPatch, suspicious: bool, target: str
) -> None:
    from tests.golden.conftest import pr_text
    from theseus.contracts.result import Grant, Intent
    from theseus.engine import pipeline

    intent = Intent(
        purpose="Grant access",
        suspicious=suspicious,
        grants=[Grant(principal="user:priya-intern", access="read", resource=target)],
    )
    monkeypatch.setattr(pipeline, "read_intent", lambda *args: intent)
    result = pipeline.run_pr(
        world("intern", "base"), world("intern", "head"), *pr_text("intern"), deps_for("intern")
    )
    assert result.min_cut is not None
    assert result.min_cut.value == 1 and result.min_cut.cuttable
    assert any(r.id == "I1" for r in result.requirements)


@pytest.mark.falkordb
def test_real_pr_pipeline_returns_the_same_cut_from_falkordb_and_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from tests.golden.conftest import pr_text
    from theseus.engine import pipeline

    prefix = f"e4_pipeline__{os.getpid()}__"
    monkeypatch.setattr(pipeline, "graph_name", lambda world, side: prefix + side)
    base, head = world("intern", "base"), world("intern", "head")
    title, body = pr_text("intern")
    memory = pipeline.run_pr(base, head, title, body, deps_for("intern"))
    falkor = FalkorStore(get_client(get_settings()))
    try:
        result = pipeline.run_pr(base, head, title, body, replace(deps_for("intern"), store=falkor))
        assert result.min_cut == memory.min_cut
        assert result.min_cut is not None and result.min_cut.value == 1_000_000
        assert all(edge.evidence in result.evidence for edge in result.min_cut.cut)
    finally:
        # The pipeline also leaves a graph per candidate fix (`<prefix>fix-a`, ...), so delete by prefix.
        for name in falkor.list_graphs():
            if name.startswith(prefix):
                falkor.delete(name)
