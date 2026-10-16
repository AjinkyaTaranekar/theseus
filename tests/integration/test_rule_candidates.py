"""Generated rule fixes have the same verdicts and ranking in FalkorDB and memory."""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

from tests.golden.conftest import deps_for, pr_text, world
from theseus.config import get_settings
from theseus.engine.pipeline import run_pr
from theseus.graph.client import get_client
from theseus.graph.store import FalkorStore

pytestmark = pytest.mark.falkordb


@pytest.mark.parametrize("scenario", ["intern", "public-bucket"])
def test_generated_candidates_have_database_parity(scenario: str) -> None:
    prefix = f"e6-{os.getpid()}-{scenario}"
    base = world(scenario, "base").model_copy(update={"root": f"{prefix}/pr1/base"})
    head = world(scenario, "head").model_copy(update={"root": f"{prefix}/pr1/head"})
    title, body = pr_text(scenario)
    memory = deps_for(scenario)
    database = FalkorStore(get_client(get_settings()))
    try:
        expected = run_pr(base, head, title, body, memory)
        actual = run_pr(base, head, title, body, replace(memory, store=database))
        assert actual.model_dump(exclude={"timings"}) == expected.model_dump(exclude={"timings"})
        for candidate in actual.candidates:
            assert candidate.ranking_facts is not None
            assert any(
                name.startswith(prefix) and name.endswith("fix-" + candidate.id.lower())
                for name in database.list_graphs()
            )
    finally:
        for name in database.list_graphs():
            if name.startswith(prefix + "__pr1-"):
                database.delete(name)
