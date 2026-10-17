"""The MCP server over the registry, spoken to by a real MCP client in process (task A6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client

from tests.golden.conftest import FIXTURES, deps_for
from tests.unit.mcp_support import BASE, HEAD, fake_engine, intern_context
from theseus.agent.trace import Recorder
from theseus.graph.store import MemoryStore
from theseus.mcp import server
from theseus.mcp.server import TRACE_URI, build_server, context_for_fixture
from theseus.mcp.tools import ToolContext, build_registry

PRIYA = "user:priya-intern"


def run(check: Any) -> None:
    anyio.run(check)


def test_a_client_lists_the_ten_tools_with_schemas_and_read_only_hints() -> None:
    context, _ = intern_context()

    async def check() -> None:
        with Recorder(build_registry()) as recorder:
            async with Client(build_server(context, recorder)) as client:
                tools = (await client.list_tools()).tools
        assert [t.name for t in tools] == [t.name for t in build_registry().tools]
        for t in tools:
            assert t.input_schema["type"] == "object" and t.description
            assert t.annotations is not None and t.annotations.read_only_hint == (t.name != "simulate_fix")

    run(check)


def test_a_client_calls_every_tool_and_every_call_is_in_the_trace() -> None:
    context, _ = intern_context()
    calls = {
        "diff_paths": {"base": BASE, "head": HEAD},
        "blast_radius": {"graph": HEAD, "sources": [PRIYA]},
        "check_requirements": {"graph": HEAD},
        "choke_points": {"graph": HEAD},
        "explain_path": {"graph": HEAD, "actor": PRIYA, "target": "db:customer-db"},
        "min_cut": {"graph": HEAD, "sources": [PRIYA]},
        "shortest_route": {"graph": HEAD, "source": PRIYA, "target": "db:customer-db"},
        "simulate_fix": {
            "graph": HEAD,
            "candidate_id": "B",
            "ops": [{"provider": "aws", "op": "remove_group_member", "args": {}}],
        },
        "unused_grants": {"graph": HEAD},
        "secrets_reachable": {"graph": HEAD, "sources": [PRIYA]},
    }

    async def check() -> None:
        with Recorder(build_registry()) as recorder:
            async with Client(build_server(context, recorder)) as client:
                for name, arguments in calls.items():
                    result = await client.call_tool(name, arguments)
                    assert not result.is_error, (name, result.content)
                    assert result.structured_content is not None
                    assert json.loads(result.content[0].text) == result.structured_content
                trace = await client.read_resource(TRACE_URI)
        assert [c["tool"] for c in json.loads(trace.contents[0].text)] == list(calls)
        assert [c.tool for c in recorder.calls] == list(calls)

    run(check)
    context.cleanup()


def test_a_tool_error_reaches_the_client_as_an_error_result_and_is_traced() -> None:
    context, _ = intern_context()

    async def check() -> None:
        with Recorder(build_registry()) as recorder:
            async with Client(build_server(context, recorder)) as client:
                unknown = await client.call_tool("check_requirements", {"graph": "nope"})
                bad = await client.call_tool("check_requirements", {"graph": HEAD, "x": 1})
                missing = await client.call_tool("post_comment", {})
        for result in (unknown, bad, missing):
            assert result.is_error and result.content[0].text
        # A name that is no tool is not a tool call, so only the two real tools are in the trace.
        assert [(c.tool, c.summary.startswith("error: ")) for c in recorder.calls] == [
            ("check_requirements", True),
            ("check_requirements", True),
        ]

    run(check)


def test_the_context_for_a_fixture_has_both_graphs_the_pr_requirements_and_the_actors_it_opened() -> None:
    deps = deps_for("intern")
    context = context_for_fixture(FIXTURES / "intern", deps, engine=fake_engine()[0])
    assert sorted(context.states) == [BASE, HEAD]
    assert sorted(deps.store.list_graphs()) == [BASE, HEAD]
    assert context.fix_actors == [PRIYA]
    assert {r.id for r in context.requirements} >= {"R1", "I1"}
    assert PRIYA in context.actors


def test_a_fixture_with_one_side_loads_that_side_and_needs_no_fix_actors() -> None:
    deps = deps_for("unused-grant")
    context = context_for_fixture(FIXTURES / "unused-grant", deps, engine=fake_engine()[0])
    assert list(context.states) == ["fx__unused-grant__base"] and context.fix_actors is None


def test_a_folder_with_neither_side_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="no base or head"):
        context_for_fixture(tmp_path, deps_for("intern"), engine=fake_engine()[0])


def test_main_serves_the_intern_on_the_recordings_in_replay_with_no_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh clone has no keys, and the hash-keyed recordings no longer match the demo world, so `main` has
    to use the clients the CLI uses in replay (`tests/unit/test_cli.py` checks the commands the same way)."""
    served: list[ToolContext] = []

    async def serve_once(context: ToolContext) -> None:
        served.append(context)

    monkeypatch.setenv("THESEUS_MODE", "replay")
    monkeypatch.setattr("theseus.graph.client.get_client", lambda settings: None)
    monkeypatch.setattr("theseus.graph.store.FalkorStore", lambda client: MemoryStore())
    monkeypatch.setattr(server, "serve", serve_once)
    assert server.main([str(FIXTURES / "intern")]) == 0
    (context,) = served
    assert sorted(context.states) == [BASE, HEAD]
    assert context.fix_actors == [PRIYA]
    assert {r.id for r in context.requirements} >= {"R1", "I1"}
