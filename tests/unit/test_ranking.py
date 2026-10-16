"""Fixed ranking order and the advisory veto."""

from __future__ import annotations

import pytest

from theseus.contracts.result import Candidate, PatchOp, RankingFacts
from theseus.engine.candidates import rank
from theseus.errors import ModelError


def candidate(identifier: str, **updates: object) -> Candidate:
    data = dict(
        id=identifier,
        source="rule",
        proposed_by="theseus",
        title="Fix",
        verdict="pass",
        ranking_facts=RankingFacts(permissions_removed=0, adds_broad_wildcard=False),
    )
    data.update(updates)
    return Candidate(**data)


def test_verdict_precedes_every_tie_breaker() -> None:
    items = [
        candidate("A", verdict="invalid"),
        candidate("D", verdict="fail"),
        candidate("C", verdict="unknown"),
        candidate("S"),
    ]
    assert [c.id for c in rank(items, {})] == ["S", "C", "D", "A"]
    assert [c.id for c in rank(items, {}) if c.recommended] == ["S"]


@pytest.mark.parametrize(
    "left,right",
    [
        (
            {},
            {
                "ranking_facts": RankingFacts(
                    unknown_steps=1, permissions_removed=0, adds_broad_wildcard=False
                )
            },
        ),
        ({}, {"ops": [PatchOp(provider="test", op="edit")]}),
        ({}, {"ranking_facts": RankingFacts(permissions_removed=1, adds_broad_wildcard=False)}),
        ({}, {"ranking_facts": RankingFacts(permissions_removed=0, adds_broad_wildcard=True)}),
        ({"source": "human"}, {"source": "rule"}),
        ({"source": "rule"}, {"source": "llm"}),
    ],
)
def test_each_tie_breaker(left: dict, right: dict) -> None:
    assert [c.id for c in rank([candidate("A", **right), candidate("Z", **left)], {})] == ["Z", "A"]


def test_id_breaks_ties_and_inputs_are_unchanged() -> None:
    items = [candidate("Z", recommended=True), candidate("A")]
    assert [c.id for c in rank(items, {})] == ["A", "Z"]
    assert items[0].recommended and not items[1].recommended


def test_veto_marks_first_pass_without_promoting_another() -> None:
    result = rank([candidate("A"), candidate("S")], {"A": 0.50001})
    assert result[0].needs_closer_look
    assert not any(c.recommended for c in result)
    assert rank([candidate("A")], {"A": 0.5})[0].recommended


def test_missing_engine_facts_cannot_be_recommended() -> None:
    assert not rank([candidate("A", ranking_facts=None)], {})[0].recommended


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_advisory_score_is_not_silently_safe(score: float) -> None:
    with pytest.raises(ModelError):
        rank([candidate("A")], {"A": score})


def test_no_pass_means_no_recommendation() -> None:
    assert not any(c.recommended for c in rank([candidate("A", verdict="fail")], {}))
