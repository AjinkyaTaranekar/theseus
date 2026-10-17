"""Every MCP tool against FalkorDB, on the intern fixture (task A6): the same answers as MemoryStore."""

from __future__ import annotations

import os
from typing import Any

import anyio
import pytest
from mcp import Client

from tests.golden.conftest import FIXTURES, RecordedIntent, RecordedJev, adapters_for, expected
from theseus.agent.trace import Recorder
from theseus.config import get_settings
from theseus.contracts.engine import Deps
from theseus.engine import pipeline
from theseus.graph.client import get_client
from theseus.graph.store import FalkorStore
from theseus.mcp.server import build_server, context_for_fixture
from theseus.mcp.tools import build_registry, default_engine

pytestmark = pytest.mark.falkordb

try:
    ENGINE = default_engine()
except ImportError as e:
    pytest.skip(f"the engine functions the tools call are not merged yet: {e}", allow_module_level=True)

PRIYA = "user:priya-intern"


def test_a_client_calls_all_ten_tools_on_a_falkordb_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    # Not `fx__intern__*`: `python -m theseus.mcp.server fixtures/intern` serves those names from the same
    # instance, and this test deletes the graphs it loads.
    prefix = f"a6_mcp__{os.getpid()}__"
    monkeypatch.setattr(pipeline, "graph_name", lambda world, side: prefix + side)
    base, head = prefix + "base", prefix + "head"
    settings = get_settings()
    store = FalkorStore(get_client(settings))
    deps = Deps(
        store=store,
        adapters=adapters_for(FIXTURES / "intern" / "head"),
        llm=RecordedIntent(),
        jev=RecordedJev(),
        settings=settings,
    )
    remove = {
        "provider": "aws",
        "op": "remove_membership",
        "args": {"user": "priya-intern", "group": "support-engineers"},
    }
    calls: dict[str, dict[str, Any]] = {
        "diff_paths": {"base": base, "head": head},
        "blast_radius": {"graph": head, "sources": [PRIYA]},
        "check_requirements": {"graph": head},
        "choke_points": {"graph": head, "top": 3},
        "explain_path": {"graph": head, "actor": PRIYA, "target": "db:customer-db"},
        "min_cut": {"graph": head, "sources": [PRIYA]},
        "shortest_route": {"graph": head, "source": PRIYA, "target": "db:customer-db"},
        "simulate_fix": {"graph": head, "candidate_id": "A", "ops": [remove]},
        "unused_grants": {"graph": head},
        "secrets_reachable": {"graph": head, "sources": [PRIYA]},
    }

    async def check() -> dict[str, Any]:
        answers: dict[str, Any] = {}
        with Recorder(build_registry()) as recorder:
            async with Client(build_server(context, recorder)) as client:
                for name, arguments in calls.items():
                    result = await client.call_tool(name, arguments)
                    assert not result.is_error, (name, result.content)
                    answers[name] = result.structured_content
        assert [c.tool for c in recorder.calls] == list(calls)
        return answers

    try:
        context = context_for_fixture(FIXTURES / "intern", deps, engine=ENGINE)
        answers = anyio.run(check)
        want = expected("intern")
        assert [(p["actor"], p["target"]) for p in answers["diff_paths"]["opened"]] == [
            (p["actor"], p["target"]) for p in want["opened"]
        ]
        assert answers["min_cut"]["cuttable"] is False
        assert answers["simulate_fix"]["verdict"] == want["candidates"]["A"]
        context.cleanup()
        assert context.created == []
        assert not [name for name in store.list_graphs() if name.startswith(prefix + "fix-")]
    finally:
        # `cleanup` deletes the candidate graphs only; the two sides it loaded are the test's to delete.
        for name in store.list_graphs():
            if name.startswith(prefix):
                store.delete(name)
