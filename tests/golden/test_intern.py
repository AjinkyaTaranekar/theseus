"""PR mode against the humans' answer keys: paths, intent and every requirement (tasks E3 and A3)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.golden.conftest import deps_for, expected, pr_text, world
from theseus.agent.llm import LlmReply
from theseus.contracts.result import AnalysisResult, compare, project
from theseus.engine.pipeline import run_pr


def analyze(scenario: str, llm: Any = None) -> AnalysisResult:
    title, body = pr_text(scenario)
    deps = deps_for(scenario)
    if llm is not None:
        deps = deps.__class__(**{**deps.__dict__, "llm": llm})
    return run_pr(world(scenario, "base"), world(scenario, "head"), title, body, deps)


def test_intern_opens_priya_s_three_paths_and_says_what_it_grants() -> None:
    result = analyze("intern")
    keys = ["opened", "closed", "requirements", "intent"]
    assert compare(project(result), expected("intern"), keys=keys) == []
    assert "customer-db" in result.headline and result.headline.startswith("Your PR says: ")


@pytest.mark.parametrize("scenario", ["intern", "public-bucket", "code-pr"])
def test_every_pr_fixture_matches_its_paths_intent_changes_and_requirements(scenario: str) -> None:
    keys = ["opened", "closed", "unchanged", "requirements", "changes", "intent"]
    assert compare(project(analyze(scenario)), expected(scenario), keys=keys) == []


class AsksForTheDatabase:
    """A model that reads the intern PR as asking for the customer database itself."""

    def call(self, purpose: str, messages: list[dict[str, Any]], *args: Any, **kwargs: Any) -> LlmReply:
        grants = [{"principal": "user:priya-intern", "access": "read", "resource": "db:customer-db"}]
        arguments = {"purpose": "Give Priya the customer database.", "grants": grants, "suspicious": False}
        return LlmReply(tool="submit_intent", arguments=arguments, model="test", ms=0, key="intent-test")


def test_a_pr_that_asks_for_the_database_still_opens_it_and_needs_an_owner() -> None:
    """Words never approve: the intent requirement is met, yet the path stays dangerous (04 section 10)."""
    result = analyze("intern", llm=AsksForTheDatabase())
    assert ("user:priya-intern", "db:customer-db") in {(p.actor, p.target) for p in result.opened}
    assert {r.id: r.status for r in result.requirements}["I1"] == "satisfied"
    assert result.headline == (
        "Your PR asks for customer-db, a database. "
        "Access to sensitive data needs an owner's approval in theseus.yaml."
    )


def test_rule_fixes_match_the_intern_answer_key() -> None:
    result = project(analyze("intern"))
    wanted = expected("intern")["candidates"]
    assert {k: result["candidates"][k] for k in ("A", "C", "D")} == {k: wanted[k] for k in ("A", "C", "D")}
