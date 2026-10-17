"""Advisory probabilities can veto passing fixes but never decide engine facts."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.golden.conftest import FIXTURES, deps_for, pr_text, world
from tests.unit.test_ranking import candidate
from theseus.agent.jev import Jev, JevAnswer, JevReply
from theseus.config import get_settings
from theseus.contracts.result import AnalysisResult, project
from theseus.engine.pipeline import run_finding, run_pr
from theseus.errors import ModelError


class StubJev(Jev):
    def __init__(self, score: float | None) -> None:
        super().__init__(get_settings())
        self.score = score
        self.requests: list[tuple[str, Any, dict]] = []

    def ask(self, purpose: str, state: Any, questions: dict) -> JevReply:
        self.requests.append((purpose, state, questions))
        return JevReply(
            answers={key: JevAnswer(type="noul", noul=self.score) for key in questions},
            model="test",
            ms=0,
            key="test",
        )


def test_only_passing_fixes_are_scored_and_context_is_untrusted() -> None:
    jev = StubJev(0.75)
    assert jev.breakage([candidate("A", verdict="fail")], [], []) == {}
    assert jev.requests == []
    assert jev.breakage([candidate("S")], [], []) == {"S": 0.75}
    purpose, state, questions = jev.requests[0]
    assert purpose == "breakage" and set(questions) == {"S"}
    assert "<untrusted_fix_context>" in state and "</untrusted_fix_context>" in state


@pytest.mark.parametrize("score", [None, float("nan"), float("inf"), -1, 2])
def test_invalid_breakage_answer_raises(score: float | None) -> None:
    with pytest.raises(ModelError, match="invalid probability"):
        StubJev(score).breakage([candidate("S")], [], [])


def test_pipeline_applies_the_veto_to_an_engine_pass() -> None:
    deps = deps_for("public-bucket")
    observed = []

    def breakage(candidates: list, requirements: list, calls: list) -> dict[str, float]:
        observed.append((candidates, requirements, calls))
        return {"S": 0.9}

    deps.jev.breakage = breakage
    title, body = pr_text("public-bucket")
    result = run_pr(world("public-bucket", "base"), world("public-bucket", "head"), title, body, deps)
    scoped = next(c for c in result.candidates if c.id == "S")
    assert scoped.verdict == "pass" and scoped.needs_closer_look and not scoped.recommended
    assert not any(c.recommended for c in result.candidates)
    assert observed and any(req.id == "I1" for req in observed[0][1])


def finding_with_breakage(score: float | None) -> tuple[AnalysisResult, list]:
    """Finding mode on the compromised Action, with a Jev that scores every passing fix `score` (None: a Jev
    that cannot score breakage at all, like the offline clients)."""
    deps = deps_for("compromised-action")
    observed: list = []

    def breakage(candidates: list, requirements: list, calls: list) -> dict[str, float]:
        observed.append((candidates, requirements, calls))
        return {c.id: score for c in candidates if c.verdict == "pass"}

    if score is not None:
        deps.jev.breakage = breakage
    advisory = json.loads((FIXTURES / "compromised-action" / "advisory.json").read_text(encoding="utf-8"))
    return run_finding(world("compromised-action", "base"), advisory, deps), observed


def test_a_high_breakage_score_removes_the_containment_recommendation() -> None:
    result, observed = finding_with_breakage(0.9)
    [k] = result.candidates
    assert k.id == "K" and k.verdict == "pass"
    assert k.needs_closer_look and not k.recommended
    assert project(result)["recommended"] is None
    [(scored, requirements, _calls)] = observed
    assert [c.id for c in scored] == ["K"]
    assert {r.id for r in requirements} >= {"R4", "R5", "R17"}


def test_a_low_breakage_score_leaves_containment_recommended() -> None:
    result, observed = finding_with_breakage(0.5)
    [k] = result.candidates
    assert k.verdict == "pass" and k.recommended and not k.needs_closer_look
    assert project(result)["recommended"] == "K" and len(observed) == 1


def test_finding_without_a_breakage_score_recommends_the_engine_pass() -> None:
    result, observed = finding_with_breakage(None)
    [k] = result.candidates
    assert k.verdict == "pass" and k.recommended and not k.needs_closer_look
    assert observed == []


def test_a_veto_never_changes_what_the_engine_decided() -> None:
    vetoed, _ = finding_with_breakage(0.9)
    plain, _ = finding_with_breakage(None)
    drop = {"timings": True, "candidates": True}
    assert vetoed.model_dump(exclude=drop) == plain.model_dump(exclude=drop)
    [a], [b] = vetoed.candidates, plain.candidates
    changed = {"recommended", "needs_closer_look"}
    assert a.model_dump(exclude=changed) == b.model_dump(exclude=changed)


def test_a_failing_breakage_check_does_not_block_containment(caplog: pytest.LogCaptureFixture) -> None:
    """Finding mode never waits on advice: the blast radius and the rotate list matter most while an Action
    is compromised, so a Jev that cannot score leaves K on the engine's ranking and says why in the log."""
    deps = deps_for("compromised-action")

    def broken(candidates: list, requirements: list, calls: list) -> dict[str, float]:
        raise ModelError("breakage: Jev is down")

    deps.jev.breakage = broken
    advisory = json.loads((FIXTURES / "compromised-action" / "advisory.json").read_text(encoding="utf-8"))
    result = run_finding(world("compromised-action", "base"), advisory, deps)
    [k] = result.candidates
    assert k.verdict == "pass" and k.recommended and not k.needs_closer_look
    assert result.rotate == ["secret:prod-db-credentials"] and result.opened
    assert "breakage unavailable" in caplog.text
