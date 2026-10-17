"""The server over real stdio, as Claude Code starts it: a subprocess whose stdout is only the protocol."""

from __future__ import annotations

import json
import sys

import anyio
from mcp import Client, StdioServerParameters

from tests.golden.conftest import ROOT
from tests.unit.mcp_support import HEAD

# The server's own entry point needs FalkorDB and the live Jev (like `analyze`); this child serves the same
# `serve` on a MemoryStore with the recorded answers, so the framing of stdin and stdout is what is tested.
CHILD = """
import anyio
from tests.unit.mcp_support import intern_context
from theseus.mcp.server import serve

context, _ = intern_context()
print("a stray print must not reach the client")
anyio.run(serve, context)
"""


def test_a_client_starts_the_server_as_a_subprocess_and_lists_and_calls_tools() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-c", CHILD], cwd=str(ROOT))

    async def check() -> None:
        async with Client(params) as client:
            names = [t.name for t in (await client.list_tools()).tools]
            result = await client.call_tool("check_requirements", {"graph": HEAD})
            trace = await client.read_resource("theseus://tool-trace")
        assert len(names) == 10 and "simulate_fix" in names
        assert not result.is_error and result.structured_content["requirements"]
        assert [c["tool"] for c in json.loads(trace.contents[0].text)] == ["check_requirements"]

    anyio.run(check)
