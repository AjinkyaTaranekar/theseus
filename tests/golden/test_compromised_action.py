"""FM3: the compromised Action's blast radius and rotate list, against the human-reviewed answer key."""

from __future__ import annotations

import json

import pytest

from tests.golden.conftest import FIXTURES, deps_for, expected, world
from theseus.contracts.engine import Deps, GraphState
from theseus.contracts.result import AnalysisResult, compare, project
from theseus.engine.finding import blast_radius, match_advisory, rotate_list, with_finding
from theseus.engine.pipeline import prepare_state, run_finding
from theseus.graph.load import load_graph

SCENARIO = "compromised-action"
PREVIEW = "workflow:demo-org/docs-site/preview.yml"
LINT = "workflow:demo-org/website/lint.yml"
DB_ROUTE = [
    PREVIEW,
    "role:github-deploy",
    "role:prod-support",
    "secret:prod-db-credentials",
    "db:customer-db",
]


def advisory() -> dict:
    return json.loads((FIXTURES / SCENARIO / "advisory.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def deps() -> Deps:
    return deps_for(SCENARIO)


@pytest.fixture(scope="module")
def state(deps: Deps) -> GraphState:
    base, _ = prepare_state(world(SCENARIO, "base"), "base", deps)
    rows = with_finding(base.rows, advisory())
    base = base.model_copy(update={"rows": rows})
    load_graph(deps.store, base)
    return base


def test_both_workflows_on_v3_match_the_advisory(state: GraphState) -> None:
    assert match_advisory(state.rows, advisory()) == [PREVIEW, LINT]


def test_a_version_the_advisory_does_not_list_matches_nothing(state: GraphState) -> None:
    patched = {**advisory(), "affected_versions": ["v4"]}
    assert match_advisory(state.rows, patched) == []


def test_the_finding_affects_the_action(state: GraphState) -> None:
    nodes = {n.id for n in state.rows.nodes}
    assert "finding:GHSA-demo-0001" in nodes
    affects = [(e.src, e.dst) for e in state.rows.edges if e.type == "AFFECTS"]
    assert affects == [("finding:GHSA-demo-0001", "action:demo-thirdparty/file-diff")]
    assert all(e.evidence for e in state.rows.edges if e.type == "AFFECTS")


def test_blast_radius_reaches_invoices_the_db_secret_and_the_database(deps: Deps, state: GraphState) -> None:
    paths = blast_radius(deps.store, state, [PREVIEW, LINT])
    assert {p.target for p in paths} == {
        "db:customer-db",
        "s3://demo-company-files/invoices/",
        "secret:prod-db-credentials",
    }
    assert {p.actor for p in paths} == {PREVIEW}


def test_the_database_is_five_hops_from_the_action(deps: Deps, state: GraphState) -> None:
    (db,) = [p for p in blast_radius(deps.store, state, [PREVIEW]) if p.target == "db:customer-db"]
    assert db.route == DB_ROUTE
    assert all(s.evidence for s in db.steps)


def test_lint_reaches_nothing_and_the_pinned_role_stays_out_of_reach(deps: Deps, state: GraphState) -> None:
    assert blast_radius(deps.store, state, [LINT]) == []
    reached = {p.target for p in blast_radius(deps.store, state, [PREVIEW, LINT])}
    assert not {t for t in reached if "tfstate" in t or "state" in t or "terraform-apply" in t}


def test_rotate_lists_exactly_the_reachable_secrets(deps: Deps, state: GraphState) -> None:
    assert rotate_list(deps.store, state, [PREVIEW, LINT]) == ["secret:prod-db-credentials"]
    assert rotate_list(deps.store, state, [LINT]) == []


def test_run_finding_matches_the_answer_key(deps: Deps) -> None:
    result = run_finding(world(SCENARIO, "base"), advisory(), deps)
    assert isinstance(result, AnalysisResult)
    assert result.mode == "finding"
    assert result.finding is not None and result.finding["id"] == "GHSA-demo-0001"
    assert result.finding["workflows"] == [PREVIEW, LINT]
    # Candidate K, `recommended` and `staging_to_prod` belong to FM6 and FM4.
    assert compare(project(result), expected(SCENARIO), ["scenario", "mode", "min_cut", "rotate"]) == []


def test_run_finding_lists_the_blast_radius_with_its_evidence(deps: Deps) -> None:
    result = run_finding(world(SCENARIO, "base"), advisory(), deps)
    assert {p.target for p in result.opened} == {
        "db:customer-db",
        "s3://demo-company-files/invoices/",
        "secret:prod-db-credentials",
    }
    assert result.closed == [] and result.unchanged == []
    cited = {s.evidence for p in result.opened for s in p.steps}
    assert cited and cited <= set(result.evidence)
    assert result.min_cut is not None and {e.evidence for e in result.min_cut.cut} <= set(result.evidence)
    assert result.headline == (
        "2 workflows run demo-thirdparty/file-diff at an affected version. "
        "If compromised, they reach 3 sensitive resources."
    )


def test_run_finding_is_deterministic(deps: Deps) -> None:
    first = run_finding(world(SCENARIO, "base"), advisory(), deps)
    second = run_finding(world(SCENARIO, "base"), advisory(), deps)
    drop = {"timings": True}
    assert first.model_dump(exclude=drop) == second.model_dump(exclude=drop)


def test_an_advisory_that_matches_no_workflow_reaches_nothing(deps: Deps) -> None:
    patched = {**advisory(), "affected_versions": ["v4"]}
    result = run_finding(world(SCENARIO, "base"), patched, deps)
    assert result.opened == [] and result.rotate == [] and result.min_cut is None
    assert result.finding is not None and result.finding["workflows"] == []
    assert result.headline == "No workflow uses demo-thirdparty/file-diff at an affected version."


def test_an_advisory_for_an_action_nobody_uses_adds_a_finding_but_no_edge(deps: Deps) -> None:
    other = {**advisory(), "action": "nobody/uses-this"}
    result = run_finding(world(SCENARIO, "base"), other, deps)
    assert result.opened == [] and result.rotate == []
    base, _ = prepare_state(world(SCENARIO, "base"), "base", deps)
    rows = with_finding(base.rows, other)
    assert "finding:GHSA-demo-0001" in {n.id for n in rows.nodes}
    assert not [e for e in rows.edges if e.type == "AFFECTS"]


@pytest.mark.falkordb
def test_falkordb_and_memory_agree_on_the_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    from dataclasses import replace

    from theseus.config import get_settings
    from theseus.engine import pipeline
    from theseus.graph.client import get_client
    from theseus.graph.store import FalkorStore

    name = f"fm3_parity__{os.getpid()}"
    monkeypatch.setattr(pipeline, "graph_name", lambda world, side: f"{name}__{side}")
    base = world(SCENARIO, "base")
    memory = run_finding(base, advisory(), deps_for(SCENARIO))
    falkor = FalkorStore(get_client(get_settings()))
    try:
        result = run_finding(base, advisory(), replace(deps_for(SCENARIO), store=falkor))
        assert compare(project(result), project(memory)) == []
        assert result.rotate == ["secret:prod-db-credentials"]
        assert [p.route for p in result.opened] == [p.route for p in memory.opened]
    finally:
        falkor.delete(f"{name}__base")
