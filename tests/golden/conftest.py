"""Fixture worlds through the real adapters, and Jev's recorded sensitivity answers, for the golden tests."""

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
from theseus.agent.jev import Jev, JevAnswer
from theseus.agent.llm import LlmReply
from theseus.config import get_settings
from theseus.contracts.adapters import Adapters
from theseus.contracts.engine import Deps, World
from theseus.graph.store import MemoryStore
from theseus.importer.world import load_world

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
# A2 recorded Jev on the demo's resource names; every resource the pipeline asks about is in it.
RECORDED = ROOT / "recordings/jev/sensitivity-38b5f02e4cbd.json"


class RecordedJev:
    """Jev's recorded answers by node ID. A resource it was never asked about fails the test, loudly. Steering
    is replayed by Jev itself: those recordings are keyed by the PR text alone."""

    def __init__(self) -> None:
        answers = json.loads(RECORDED.read_text(encoding="utf-8"))["answers"]
        self.answers = {k: JevAnswer.model_validate(v) for k, v in answers.items()}
        self.jev = Jev(get_settings().model_copy(update={"theseus_mode": "replay"}))

    def sensitivity(self, resources: list[tuple[str, str, str]]) -> dict[str, JevAnswer]:
        missing = sorted(r[0] for r in resources if r[0] not in self.answers)
        assert not missing, f"Jev was never recorded on {missing}"
        return {r[0]: self.answers[r[0]] for r in resources}

    def steering(self, pull_request: dict[str, Any]) -> JevAnswer:
        return self.jev.steering(pull_request)


class RecordedIntent:
    """A1's recorded intent answer for the same PR text. A1 recorded it before C1 added nine resources to the
    vocabulary, so the request no longer hashes to its key; the PR text and the answer are the same. A PR it
    never recorded fails the test, loudly."""

    def call(self, purpose: str, messages: list[dict[str, Any]], *args: Any, **kwargs: Any) -> LlmReply:
        pr = messages[-1]["content"]
        for path in sorted((ROOT / "recordings/llm").glob(f"{purpose}-*.json")):
            recording = json.loads(path.read_text(encoding="utf-8"))
            if recording["request"]["messages"][-1]["content"] == pr:
                (call,) = recording["response"]["tool_calls"]
                return LlmReply(
                    tool=call["name"],
                    arguments=json.loads(call["arguments"]),
                    model=recording["model"],
                    ms=0,
                    key=path.stem,
                )
        raise AssertionError(f"no {purpose} recording for this PR text: {pr[:120]}")


def adapters_for(root: Path) -> Adapters:
    config = yaml.safe_load((root / "theseus.yaml").read_text(encoding="utf-8"))
    return Adapters(
        iac=TerraformAdapter(), cloud=AwsAdapter(config), ci=GithubAdapter(), code=PythonAdapter()
    )


def world(scenario: str, side: str) -> World:
    root = FIXTURES / scenario / side
    plan = json.loads((FIXTURES / scenario / f"{side}.plan.json").read_text(encoding="utf-8"))
    return load_world(root, plan, adapters_for(root))


def deps_for(scenario: str) -> Deps:
    side = "head" if (FIXTURES / scenario / "head").is_dir() else "base"
    return Deps(
        store=MemoryStore(),
        adapters=adapters_for(FIXTURES / scenario / side),
        llm=RecordedIntent(),
        jev=RecordedJev(),
        settings=get_settings(),
    )


def expected(scenario: str) -> dict[str, Any]:
    path = FIXTURES / scenario / "expected.json"
    if not path.is_file():
        pytest.fail(f"{path.relative_to(ROOT)} is missing: F5 writes it (humans review and save it)")
    return json.loads(path.read_text(encoding="utf-8"))


def pr_text(scenario: str) -> tuple[str, str]:
    title, _, body = (FIXTURES / scenario / "pr.md").read_text(encoding="utf-8").partition("\n")
    return title.removeprefix("# ").strip(), body.strip()
