"""`main`'s dangerous paths: spec 02's six, and the ones the gaps planted in legacy.tf add (task E3)."""

from __future__ import annotations

from tests.golden.conftest import deps_for, expected, world
from theseus.contracts.result import AnalysisResult, compare, project
from theseus.engine.analyze import analyze, step_evidence
from theseus.engine.pipeline import actors, config_requirements, prepare_state
from theseus.graph.load import load_graph


def test_main_has_exactly_its_dangerous_paths() -> None:
    deps = deps_for("intern")
    state, _ = prepare_state(world("intern", "base"), "base", deps)
    load_graph(deps.store, state)
    found = analyze(deps.store, state, config_requirements(state.world), actors(state))
    # The six of spec 02 and those of the contractor, the backup runner and the deploy workflow through it.
    assert len(found.dangerous) == 23
    assert {p.actor for p in found.dangerous} == {
        "user:casey-contractor",
        "workflow:demo-org/docs-site/preview.yml",
        "workflow:demo-org/infra/deploy.yml",
        "workflow:demo-org/infra/snapshot.yml",
        "workload:invoice-mailer",
        "workload:receipt-renderer",
        "workload:support-portal",
    }
    # In the intern PR these are the unchanged ones; the answer key lists them with every cite.
    result = AnalysisResult(mode="scan", unchanged=found.dangerous, evidence=step_evidence(state.rows))
    want = {"unchanged": expected("intern")["unchanged"]}
    assert compare(project(result), want, keys=["unchanged"]) == []
    assert {r.id: r.status for r in found.requirements} == {f"R{i}": "satisfied" for i in range(1, 22)}
