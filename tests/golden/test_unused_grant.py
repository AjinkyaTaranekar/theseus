"""Scan mode on the unused-grant fixture: the cut lands on the grant no code calls, and removing it breaks
nobody (C3). The answer key is `fixtures/unused-grant/expected.json`, written by humans."""

from __future__ import annotations

from tests.golden.conftest import deps_for, expected, world
from tests.unit.adapters.aws.test_patch import op
from theseus.contracts.engine import CandidateDraft, Deps, GraphState
from theseus.contracts.result import AnalysisResult, compare, project
from theseus.engine.analyze import analyze
from theseus.engine.mincut import min_cut
from theseus.engine.pipeline import actors, config_requirements, prepare_state, run_scan
from theseus.engine.simulate import simulate
from theseus.graph.load import load_graph

SCENARIO = "unused-grant"
PORTAL = "workload:support-portal"


def scan() -> tuple[AnalysisResult, Deps]:
    deps = deps_for(SCENARIO)
    return run_scan(world(SCENARIO, "base"), deps), deps


def loaded() -> tuple[Deps, GraphState]:
    deps = deps_for(SCENARIO)
    state, _ = prepare_state(world(SCENARIO, "base"), "main", deps)
    load_graph(deps.store, state)
    return deps, state


def test_scan_matches_the_answer_key() -> None:
    result, _ = scan()
    assert compare(project(result), expected(SCENARIO)) == []


def test_the_cut_lands_on_the_unused_grant_and_not_on_what_carries_it() -> None:
    result, _ = scan()
    assert result.min_cut is not None
    assert result.min_cut.sources == [PORTAL]
    assert result.min_cut.value == 1 and result.min_cut.cuttable
    assert [(e.src, e.type, e.dst) for e in result.min_cut.cut] == [
        ("role:support-portal", "CAN", "secret:prod-db-credentials")
    ]


def test_exactly_one_grant_is_unused_and_it_cites_the_policy_statement() -> None:
    result, _ = scan()
    (grant,) = result.unused_grants
    assert (grant.workload, grant.resource, grant.access) == (PORTAL, "secret:prod-db-credentials", "read")
    cited = result.evidence[grant.evidence]
    assert (cited.address, cited.part) == ("aws_iam_role_policy.support_portal", "LegacyDbSecret")
    assert cited.file != "unknown" and cited.line is not None


def test_candidate_u_removes_that_statement_and_passes_without_breaking_a_call() -> None:
    result, _ = scan()
    (u,) = result.candidates
    assert u.id == "U" and u.source == "rule" and u.verdict == "pass" and u.recommended
    assert [(o.op, o.args) for o in u.ops] == [
        (
            "remove_statement",
            {"policy_address": "aws_iam_role_policy.support_portal", "sid": "LegacyDbSecret"},
        )
    ]
    assert u.paths_left == u.new_paths == u.requirements_broken == u.calls_broken == u.unknown == []


def test_every_citation_in_the_result_resolves() -> None:
    result, _ = scan()
    assert result.min_cut is not None
    cited = {e.evidence for e in result.min_cut.cut} | {g.evidence for g in result.unused_grants}
    cited |= {s.evidence for p in result.unchanged for s in p.steps}
    assert cited <= set(result.evidence)


def test_scan_reports_the_dangerous_paths_already_in_main_and_names_the_graph() -> None:
    result, _ = scan()
    assert result.mode == "scan" and result.scenario == SCENARIO
    assert result.graphs == {"main": "fx__unused-grant__main"}
    assert not result.opened and not result.closed
    assert (PORTAL, "secret:prod-db-credentials") in {(p.actor, p.target) for p in result.unchanged}
    assert "support-portal" in result.headline and "prod-db-credentials" in result.headline


def test_candidate_u_is_verified_on_a_copy_of_main() -> None:
    result, deps = scan()
    (u,) = result.candidates
    assert u.id == "U"
    assert result.graphs["main"] in deps.store.list_graphs()
    assert any(name.endswith("fix-u") for name in deps.store.list_graphs())


def test_a_grant_the_code_calls_carries_the_used_capacity_and_is_not_the_cheapest_cut() -> None:
    deps, state = loaded()
    analysis = analyze(deps.store, state, [], actors(state))
    # billing-api reads the database secret through a call (spec 02: R6). Without requirements the cut still
    # lands on that grant, but it costs USED, not 1.
    cut = min_cut(deps.store, state, analysis, ["workload:billing-api"], [])
    assert cut.value == 1_000 and cut.cuttable
    assert [(e.src, e.type, e.dst) for e in cut.cut] == [
        ("role:billing-api", "CAN", "secret:prod-db-credentials")
    ]


def test_removing_a_grant_the_code_calls_fails_with_the_file_and_line() -> None:
    deps, state = loaded()
    draft = CandidateDraft(
        id="H1",
        source="human",
        proposed_by="someone",
        title="Drop billing-api's secret grant",
        ops=[op("remove_statement", policy_address="aws_iam_role_policy.billing_api", sid="ReadDbSecret")],
    )
    broken = simulate(deps.store, state, draft, ["workload:billing-api"], [], deps.adapters)
    assert broken.verdict == "fail"
    assert broken.requirements_broken == []
    assert broken.calls_broken, broken.reason
    assert all("workload:billing-api" in c and "services/billing_api/" in c for c in broken.calls_broken)
    assert all(c in broken.reason for c in broken.calls_broken)


def test_the_config_requirements_still_hold_after_candidate_u() -> None:
    result, _ = scan()
    assert {r.id: r.status for r in result.requirements} == {f"R{i}": "satisfied" for i in range(1, 18)}
    assert config_requirements(world(SCENARIO, "base"))
