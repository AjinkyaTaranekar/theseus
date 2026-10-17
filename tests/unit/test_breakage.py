"""Advisory probabilities can veto passing fixes but never decide engine facts."""

from __future__ import annotations

from typing import Any

import pytest

from tests.golden.conftest import deps_for, pr_text, world
from tests.unit.test_ranking import candidate
from theseus.agent.jev import Jev, JevAnswer, JevReply
from theseus.config import get_settings
from theseus.engine.pipeline import run_pr
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
