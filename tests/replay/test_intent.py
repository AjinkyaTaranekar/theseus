"""Intent extraction replayed from recordings/llm/ on the cases in intents.yaml: never the network.

Record or refresh the recordings with the Crusoe key in .env:

    THESEUS_MODE=record pytest -q tests/replay/test_intent.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from theseus.adapters.aws.adapter import AwsAdapter
from theseus.adapters.github.adapter import GithubAdapter
from theseus.adapters.python.adapter import PythonAdapter
from theseus.adapters.terraform.adapter import TerraformAdapter
from theseus.agent.intent import Vocabulary, extract_intent, vocabulary
from theseus.agent.jev import Jev
from theseus.agent.llm import Llm
from theseus.config import get_settings
from theseus.contracts.adapters import Adapters
from theseus.importer.build import build_rows
from theseus.importer.world import load_world

CASES_FILE = Path(__file__).with_name("intents.yaml")
TEMPLATE = Path(".github/pull_request_template.md").read_text(encoding="utf-8")
DATA = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
VOCAB = Vocabulary.model_validate(DATA["vocabulary"])
CASES: list[dict[str, Any]] = DATA["cases"]


def body_of(case: dict[str, Any]) -> str | None:
    """The case's body, or the repo's PR template with each named section filled in. `padding` repeats a
    sentence up to GitHub's body limit before the rest; `smuggled` is appended in invisible tag characters."""
    if "template_sections" not in case:
        body = case["body"]
        if "padding" in case:
            pad = case["padding"]
            body += "\n\n" + pad["repeat"] * pad["times"] + "\n\n" + pad["then"]
            assert len(body) <= 65_536, f"{case['id']}: longer than GitHub allows"
        if "smuggled" in case:
            body += "".join(chr(0xE0000 + ord(c)) for c in case["smuggled"])
        return body
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


@pytest.fixture(scope="module")
def jev(llm: Llm) -> Jev:
    """Jev's steering check, replayed like the LLM; it can make an intent suspicious, never clear it."""
    return Jev(get_settings(), llm=llm)


def test_the_cases_cover_the_messy_ones() -> None:
    assert len(CASES) == 31
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert sum(1 for c in CASES if c["suspicious"]) == 14
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


def test_the_vocabulary_is_the_one_the_demo_world_sends() -> None:
    """A resource added to the world reaches the cases, so the prompt is measured on the IDs it sees live."""
    root = Path("fixtures/intern/head")
    config = yaml.safe_load((root / "theseus.yaml").read_text(encoding="utf-8"))
    adapters = Adapters(
        iac=TerraformAdapter(), cloud=AwsAdapter(config), ci=GithubAdapter(), code=PythonAdapter()
    )
    plan = json.loads(root.with_name("head.plan.json").read_text(encoding="utf-8"))
    assert vocabulary(build_rows(load_world(root, plan, adapters), {}, adapters)) == VOCAB


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_intent_matches_the_gold_answer(case: dict[str, Any], llm: Llm, jev: Jev) -> None:
    intent = extract_intent(case["title"], body_of(case), VOCAB, llm=llm, jev=jev, template=TEMPLATE)
    got = sorted((g.principal, g.access, g.resource) for g in intent.grants)
    want = sorted(tuple(g) for g in case["grants"])
    assert got == want, f"{case['id']}: purpose was {intent.purpose!r}"
    assert intent.suspicious is case["suspicious"], f"{case['id']}: purpose was {intent.purpose!r}"
    assert intent.stated is case.get("stated", True), f"{case['id']}: purpose was {intent.purpose!r}"
