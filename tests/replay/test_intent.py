"""Intent extraction replayed from recordings/llm/ on the cases in intents.yaml: never the network.

Record or refresh the recordings with the Crusoe key in .env:

    THESEUS_MODE=record pytest -q tests/replay/test_intent.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from theseus.agent.intent import Vocabulary, extract_intent
from theseus.agent.llm import Llm
from theseus.config import get_settings

CASES_FILE = Path(__file__).with_name("intents.yaml")
TEMPLATE = Path(".github/pull_request_template.md").read_text(encoding="utf-8")
DATA = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
VOCAB = Vocabulary.model_validate(DATA["vocabulary"])
CASES: list[dict[str, Any]] = DATA["cases"]


def body_of(case: dict[str, Any]) -> str | None:
    """The case's body, or the repo's PR template with each named section filled in."""
    if "template_sections" not in case:
        return case["body"]
    body = TEMPLATE
    for heading, text in case["template_sections"].items():
        marker = f"## {heading}\n"
        assert marker in body, f"the PR template has no section {heading!r}"
        body = body.replace(marker, f"{marker}\n{text}\n", 1)
    return body


@pytest.fixture(scope="module")
def llm() -> Llm:
    """Replay by default; THESEUS_MODE=record (with a key) refreshes the recordings."""
    return Llm(get_settings())


def test_the_cases_cover_the_messy_ones() -> None:
    assert len(CASES) == 17
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert sum(1 for c in CASES if c["suspicious"]) == 2
    assert sum(1 for c in CASES if c.get("stated") is False) == 2
    assert sum(1 for c in CASES if "template_sections" in c) == 2


def test_every_gold_grant_uses_the_vocabulary() -> None:
    for case in CASES:
        for principal, access, resource in case["grants"]:
            assert principal in VOCAB.principals, (case["id"], principal)
            assert resource in VOCAB.targets, (case["id"], resource)
            assert access in ("read", "write", "assume"), (case["id"], access)
        if case.get("stated") is False:
            assert case["grants"] == [], f"{case['id']}: a PR that states nothing asks for nothing"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_intent_matches_the_gold_answer(case: dict[str, Any], llm: Llm) -> None:
    intent = extract_intent(case["title"], body_of(case), VOCAB, llm=llm, template=TEMPLATE)
    got = sorted((g.principal, g.access, g.resource) for g in intent.grants)
    want = sorted(tuple(g) for g in case["grants"])
    assert got == want, f"{case['id']}: purpose was {intent.purpose!r}"
    assert intent.suspicious is case["suspicious"], f"{case['id']}: purpose was {intent.purpose!r}"
    assert intent.stated is case.get("stated", True), f"{case['id']}: purpose was {intent.purpose!r}"
