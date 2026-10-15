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
DATA = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
VOCAB = Vocabulary.model_validate(DATA["vocabulary"])
CASES: list[dict[str, Any]] = DATA["cases"]


@pytest.fixture(scope="module")
def llm() -> Llm:
    """Replay by default; THESEUS_MODE=record (with a key) refreshes the recordings."""
    return Llm(get_settings())


def test_there_are_ten_cases_with_one_injection() -> None:
    assert len(CASES) == 10
    assert len({c["id"] for c in CASES}) == 10
    assert sum(1 for c in CASES if c["suspicious"]) == 1


def test_every_gold_grant_uses_the_vocabulary() -> None:
    for case in CASES:
        for principal, access, resource in case["grants"]:
            assert principal in VOCAB.principals, (case["id"], principal)
            assert resource in VOCAB.targets, (case["id"], resource)
            assert access in ("read", "write", "assume"), (case["id"], access)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_intent_matches_the_gold_grants(case: dict[str, Any], llm: Llm) -> None:
    intent = extract_intent(case["title"], case["body"], VOCAB, llm=llm)
    got = sorted((g.principal, g.access, g.resource) for g in intent.grants)
    want = sorted(tuple(g) for g in case["grants"])
    assert got == want, f"{case['id']}: purpose was {intent.purpose!r}"
    assert intent.suspicious is case["suspicious"]
    assert intent.purpose
