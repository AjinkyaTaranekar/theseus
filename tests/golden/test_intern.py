"""PR mode against the humans' answer keys: opened, closed and the theseus.yaml requirements (task E3)."""

from __future__ import annotations

import pytest

from tests.golden.conftest import deps_for, expected, pr_text, world
from theseus.contracts.result import compare, project
from theseus.engine.pipeline import run_pr


def run(scenario: str) -> dict:
    title, body = pr_text(scenario)
    return project(run_pr(world(scenario, "base"), world(scenario, "head"), title, body, deps_for(scenario)))


def config_only(want: dict) -> dict:
    """Intent requirements (I1, ...) come from A3; until then compare R1 to R17 only."""
    return {**want, "requirements": {k: v for k, v in want["requirements"].items() if k.startswith("R")}}


def test_intern_opens_exactly_priya_s_three_paths_and_keeps_every_requirement() -> None:
    assert (
        compare(run("intern"), config_only(expected("intern")), keys=["opened", "closed", "requirements"])
        == []
    )


@pytest.mark.parametrize("scenario", ["intern", "public-bucket", "code-pr"])
def test_every_pr_fixture_matches_its_paths_changes_and_requirements(scenario: str) -> None:
    keys = ["opened", "closed", "unchanged", "requirements", "changes"]
    assert compare(run(scenario), config_only(expected(scenario)), keys=keys) == []
