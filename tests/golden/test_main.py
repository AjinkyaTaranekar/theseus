"""`main` has exactly the six dangerous paths of spec 02, "What main looks like" (task E3)."""

from __future__ import annotations

from tests.golden.conftest import deps_for, expected, world
from theseus.contracts.result import AnalysisResult, compare, project
from theseus.engine.analyze import analyze, step_evidence
from theseus.engine.pipeline import actors, config_requirements, prepare_state
from theseus.graph.load import load_graph


def test_main_has_exactly_the_six_dangerous_paths() -> None:
    deps = deps_for("intern")
    state, _ = prepare_state(world("intern", "base"), "base", deps)
    load_graph(deps.store, state)
    found = analyze(deps.store, state, config_requirements(state.world), actors(state))
    assert len(found.dangerous) == 6
    # In the intern PR these six are the unchanged ones; the answer key lists them with every cite.
    result = AnalysisResult(mode="scan", unchanged=found.dangerous, evidence=step_evidence(state.rows))
    want = {"unchanged": expected("intern")["unchanged"]}
    assert compare(project(result), want, keys=["unchanged"]) == []
    assert {r.id: r.status for r in found.requirements} == {f"R{i}": "satisfied" for i in range(1, 18)}
