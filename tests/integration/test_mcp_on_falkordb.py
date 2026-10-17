"""Every MCP tool against FalkorDB, on the intern fixture (task A6): the same answers as MemoryStore."""

from __future__ import annotations

from typing import Any

import anyio
import pytest
from mcp import Client

from tests.golden.conftest import FIXTURES, RecordedIntent, RecordedJev, adapters_for, expected
from theseus.agent.trace import Recorder
from theseus.config import get_settings
from theseus.contracts.engine import Deps
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
BASE, HEAD = "fx__intern__base", "fx__intern__head"


def test_a_client_calls_all_ten_tools_on_a_falkordb_graph() -> None:
    settings = get_settings()
    deps = Deps(
        store=FalkorStore(get_client(settings)),
        adapters=adapters_for(FIXTURES / "intern" / "head"),
        llm=RecordedIntent(),
        jev=RecordedJev(),
        settings=settings,
    )
    context = context_for_fixture(FIXTURES / "intern", deps, engine=ENGINE)
    remove = {
        "provider": "aws",
        "op": "remove_membership",
        "args": {"user": "priya-intern", "group": "support-engineers"},
    }
    calls: dict[str, dict[str, Any]] = {
        "diff_paths": {"base": BASE, "head": HEAD},
        "blast_radius": {"graph": HEAD, "sources": [PRIYA]},
        "check_requirements": {"graph": HEAD},
        "choke_points": {"graph": HEAD, "top": 3},
        "explain_path": {"graph": HEAD, "actor": PRIYA, "target": "db:customer-db"},
        "min_cut": {"graph": HEAD, "sources": [PRIYA]},
        "shortest_route": {"graph": HEAD, "source": PRIYA, "target": "db:customer-db"},
        "simulate_fix": {"graph": HEAD, "candidate_id": "A", "ops": [remove]},
        "unused_grants": {"graph": HEAD},
        "secrets_reachable": {"graph": HEAD, "sources": [PRIYA]},
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
        answers = anyio.run(check)
        want = expected("intern")
        assert [(p["actor"], p["target"]) for p in answers["diff_paths"]["opened"]] == [
            (p["actor"], p["target"]) for p in want["opened"]
        ]
        assert answers["min_cut"]["cuttable"] is False
        assert answers["simulate_fix"]["verdict"] == want["candidates"]["A"]
    finally:
        context.cleanup()
        assert context.created == []
