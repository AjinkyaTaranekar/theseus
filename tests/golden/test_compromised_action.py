"""FM3: the compromised Action's blast radius and rotate list, against the human-reviewed answer key."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from tests.golden.conftest import FIXTURES, ROOT, RecordedJev, deps_for, expected, world
from theseus.agent.jev import JevAnswer
from theseus.contracts.engine import Deps, GraphState
from theseus.contracts.result import AnalysisResult, compare, project
from theseus.engine.finding import blast_radius, match_advisory, rotate_list, with_finding
from theseus.engine.pipeline import prepare_state, run_finding
from theseus.errors import ModelError
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
    keys = ["scenario", "mode", "min_cut", "candidates", "rotate", "staging_to_prod"]
    assert compare(project(result), expected(SCENARIO), keys) == []


def test_k_pins_the_deploy_role_to_the_workflow_that_needs_it_and_breaks_nothing(deps: Deps) -> None:
    """FM6: the cut is preview.yml's trust in github-deploy. K keeps only deploy.yml's subjects, as
    terraform-apply is already pinned; R4, R5 and R17 (deploy.yml's own access) still hold."""
    result = run_finding(world(SCENARIO, "base"), advisory(), deps)
    [k] = result.candidates
    assert (k.id, k.verdict, k.source, k.proposed_by) == ("K", "pass", "rule", "theseus")
    assert [(op.op, op.args) for op in k.ops] == [
        (
            "set_oidc_sub",
            {
                "role": "github-deploy",
                "patterns": [
                    "repo:demo-org/infra:environment:production",
                    "repo:demo-org/infra:ref:refs/heads/main",
                ],
            },
        )
    ]
    assert k.paths_left == [] and k.new_paths == [] and k.requirements_broken == []
    required = {r.id: r.status for r in result.requirements}
    assert {required[r] for r in ("R4", "R5", "R17")} == {"satisfied"}


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


URGENCY = ROOT / "recordings/jev/urgency-58e6109bdaba.json"


class UrgentJev(RecordedJev):
    """Jev's urgency as A2 recorded it on this advisory (0.89). The pipeline words its blast summary from
    the engine's facts, so the request no longer hashes to the recording's key; the answer is the same."""

    def urgency(self, finding_summary: str, blast_summary: str) -> JevAnswer:
        assert "customer-db" in blast_summary
        recording = json.loads(URGENCY.read_text(encoding="utf-8"))
        return JevAnswer.model_validate(recording["answers"]["urgent"])


class BrokenJev(RecordedJev):
    def urgency(self, finding_summary: str, blast_summary: str) -> JevAnswer:
        raise ModelError("urgency: Jev is down")


class ReplayingJev(RecordedJev):
    """The real Jev in replay mode: urgency for a request nobody recorded is an error, as in the product."""

    def urgency(self, finding_summary: str, blast_summary: str) -> JevAnswer:
        return self.jev.urgency(finding_summary, blast_summary)


def finding_with(deps: Deps, jev: object) -> AnalysisResult:
    return run_finding(world(SCENARIO, "base"), advisory(), replace(deps, jev=jev))


def test_prod_support_is_the_choke_point_every_route_to_the_database_crosses(deps: Deps) -> None:
    result = run_finding(world(SCENARIO, "base"), advisory(), deps)
    ids = [c.id for c in result.choke_points]
    assert ids[0] == "role:prod-support"
    assert ids and all(i.startswith("role:") for i in ids) and len(ids) <= 5
    scores = [c.score for c in result.choke_points]
    assert scores == sorted(scores, reverse=True) and scores[0] > scores[1]


def test_the_docs_site_preview_reaches_prod_data_from_staging(deps: Deps) -> None:
    result = run_finding(world(SCENARIO, "base"), advisory(), deps)
    assert {(s.actor, s.target) for s in result.staging_to_prod} == {
        (PREVIEW, "db:customer-db"),
        (PREVIEW, "s3://demo-company-files/invoices/"),
        (PREVIEW, "secret:prod-db-credentials"),
    }
    by_id = {p.id: p for p in result.opened}
    assert all(s.path_id in by_id for s in result.staging_to_prod)
    assert all(by_id[s.path_id].target == s.target for s in result.staging_to_prod)


def test_jevs_urgency_shows_with_its_probability_and_source(deps: Deps) -> None:
    result = finding_with(deps, UrgentJev())
    assert result.finding is not None and result.finding["urgency"] == {"p": 0.89, "source": "jev"}


def test_a_jev_without_urgency_and_a_failing_jev_leave_it_out_and_change_nothing_else(deps: Deps) -> None:
    plain = finding_with(deps, RecordedJev())
    broken = finding_with(deps, BrokenJev())
    urgent = finding_with(deps, UrgentJev())
    assert plain.finding is not None and "urgency" not in plain.finding
    assert broken.finding is not None and "urgency" not in broken.finding
    assert urgent.finding is not None
    drop = {"timings": True, "finding": True}
    assert (
        plain.model_dump(exclude=drop) == broken.model_dump(exclude=drop) == urgent.model_dump(exclude=drop)
    )


def test_an_unrecorded_urgency_is_left_out_in_replay_mode(
    deps: Deps, caplog: pytest.LogCaptureFixture
) -> None:
    result = finding_with(deps, ReplayingJev())
    assert result.finding is not None and "urgency" not in result.finding
    assert "urgency unavailable" in caplog.text and [p.target for p in result.opened]


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
        # The finding also leaves a graph per candidate fix (`<name>__base-fix-k`), so delete by prefix.
        for graph in falkor.list_graphs():
            if graph.startswith(f"{name}__"):
                falkor.delete(graph)


@pytest.mark.falkordb
def test_the_ranking_is_exact_where_falkordbs_own_algorithm_is_a_sampled_estimate() -> None:
    """Found with FM4: `algo.betweenness` samples source nodes, so its scores change between runs and
    `role:prod-support` is not always first. `choke_points` must not depend on it."""
    import os

    from theseus.config import get_settings
    from theseus.graph.algos import choke_points
    from theseus.graph.client import get_client
    from theseus.graph.store import FalkorStore

    name = f"fm4_parity__{os.getpid()}"
    store = FalkorStore(get_client(get_settings()))
    base, _ = prepare_state(world(SCENARIO, "base"), "base", deps_for(SCENARIO))
    state = base.model_copy(update={"name": name})
    try:
        store.load(name, state.rows)
        own = store.betweenness(name)
        assert {c.id for c in own} == {n.id for n in state.rows.nodes}
        assert all(c.score >= 0 for c in own)
        ranked = choke_points(store, state)
        assert ranked[0].id == "role:prod-support" and ranked == choke_points(store, state)
    finally:
        store.delete(name)
