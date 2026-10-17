"""Where a PR's change lands (engine/impact.py), whatever the data's class: what it touches, who reaches it,
the dependencies through it, access gained and lost, and the cost. On the demo world's PR fixtures, with the
models replayed."""

from __future__ import annotations

import pytest

from tests.golden.conftest import deps_for, pr_text, world
from theseus.agent.render import render_comment
from theseus.contracts.result import AnalysisResult, ChangeImpact
from theseus.engine.impact import impact_headline
from theseus.engine.pipeline import run_pr


def review(scenario: str, reverse: bool = False) -> AnalysisResult:
    base, head = world(scenario, "base"), world(scenario, "head")
    if reverse:  # the same change undone: what a PR that takes the access away would do
        base, head = head, base
    return run_pr(base, head, *pr_text(scenario), deps_for(scenario))


@pytest.fixture(scope="module")
def intern() -> AnalysisResult:
    return review("intern")


@pytest.fixture(scope="module")
def code_pr() -> AnalysisResult:
    return review("code-pr")


def test_the_intern_change_lands_on_the_group_and_lists_every_access_priya_gains(
    intern: AnalysisResult,
) -> None:
    impact = intern.impact
    assert impact is not None
    assert impact.most_affected[0] == "group:support-engineers"
    # Every class, not only sensitive data: the app logs she asked for are there too.
    assert {(a.target, a.change) for a in impact.access if a.actor == "user:priya-intern"} == {
        ("db:customer-db", "gained"),
        ("s3://demo-app-logs/", "gained"),
        ("s3://demo-company-files/invoices/", "gained"),
        ("secret:prod-db-credentials", "gained"),
    }
    (edge,) = impact.edges
    assert (edge.src, edge.type, edge.dst, edge.action) == (
        "user:priya-intern",
        "MEMBER_OF",
        "group:support-engineers",
        "added",
    )
    cited = intern.evidence[edge.evidence or ""]
    assert (cited.file, cited.line) == ("terraform/people.tf", 83)
    # Sam's three requirements run through the group she joins; none breaks.
    assert {(r.principal, r.resource, r.state) for r in impact.relies} >= {
        ("user:sam-support", "db:customer-db", "kept"),
        ("user:sam-support", "s3://demo-app-logs/", "kept"),
    }
    assert impact.monthly_usd_before == impact.monthly_usd_after > 0
    assert impact.headline == (
        "Lands on support-engineers, which 2 people and services reach; priya-intern gains access to 4"
        " resources; 3 dependencies run through it, all kept."
    )


def test_undoing_the_change_says_who_loses_access(intern: AnalysisResult) -> None:
    undone = review("intern", reverse=True).impact
    assert undone is not None
    assert {a.change for a in undone.access} == {"lost"}
    assert "priya-intern loses access to 4 resources" in undone.headline
    assert [e.action for e in undone.edges] == ["removed"]


def test_a_code_change_that_moves_no_access_still_shows_where_it_lands(code_pr: AnalysisResult) -> None:
    impact = code_pr.impact
    assert impact is not None and not impact.access
    assert {(e.src, e.type, e.dst) for e in impact.edges} >= {
        ("workload:support-portal", "CALLS", "db:customer-db"),
    }
    assert "no one gains or loses access" in impact.headline
    assert impact.touched[0].reached_by  # who else reaches what it now reads
    # A code call and a requirement for the same access count once.
    keys = [(r.principal, r.access, r.resource) for r in impact.relies]
    assert len(keys) == len(set(keys))


def test_nothing_touched_says_so() -> None:
    assert impact_headline(ChangeImpact()) == (
        "The change touches nothing Theseus models: no access, code call or requirement moves."
    )


def test_the_comment_shows_where_the_change_lands(intern: AnalysisResult) -> None:
    text = render_comment(intern, "owner/theseus", "a" * 40)
    assert "**Impact:** Lands on support-engineers" in text
    assert "<b>Where this change lands</b>" in text
    assert "| **priya-intern** | gains | read **demo-app-logs/** |" in text
    assert "linkStyle 0 stroke:#1a7f37" in text  # the added membership, in green
    assert "Where this change lands" not in render_comment(
        intern.model_copy(update={"impact": None}), "owner/theseus", "a" * 40
    )
