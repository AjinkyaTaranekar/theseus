"""The MCP server over the tool registry: `python -m theseus.mcp.server fixtures/intern` (stdio).

It loads a fixture's graphs into FalkorDB, then serves the ten tools of `tools.py` to any MCP client, Claude
Code through `.mcp.json` among them. With `--repo .` instead of a fixture, it loads the working tree's change
against `main` (what `python -m theseus check` reviews) and adds `check_change`, which plans the working tree
again, reloads both graphs and returns the check; the Claude Code plugin in `plugins/theseus` serves it so.
Every call goes through the recorder (`agent/trace.py`); the calls so far
can be read as the resource `theseus://tool-trace`. This module is also a composition root: `main` picks the
adapters and the models (recordings in replay, the real clients otherwise), as `cli.py` does.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import mcp_types as types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from theseus import __version__
from theseus.agent.intent import to_requirements
from theseus.agent.render import check_text, verdict
from theseus.agent.trace import Recorder
from theseus.contracts.engine import Deps, GraphState
from theseus.contracts.result import AnalysisResult
from theseus.engine.analyze import analyze, diff
from theseus.engine.intent_effect import approved
from theseus.engine.pipeline import actors, config_requirements, prepare_state, read_intent
from theseus.errors import TheseusError
from theseus.graph.load import load_graph
from theseus.importer.world import load_world
from theseus.mcp.tools import Engine, ToolContext, build_registry, default_engine

log = logging.getLogger(__name__)

NAME = "theseus"
TRACE_URI = "theseus://tool-trace"
SIDES = ("base", "head")


def context_for_fixture(fixture: Path, deps: Deps, engine: Engine | None = None) -> ToolContext:
    """A fixture's sides loaded as graphs in `deps.store`, ready for the tools.

    The requirements are `theseus.yaml`'s plus the PR's intent that may count (as in a PR run; the intent is
    read only when `deps.llm` is set and the fixture has a `pr.md`). When both sides exist, a simulated fix
    has to close the actors the change opened."""
    plans = {s: fixture / f"{s}.plan.json" for s in SIDES if (fixture / s).is_dir()}
    if not plans:
        raise TheseusError(f"{fixture} has no base or head folder")
    states: dict[str, GraphState] = {}
    for side, plan in plans.items():
        world = load_world(fixture / side, json.loads(plan.read_text(encoding="utf-8")), deps.adapters)
        state, _ = prepare_state(world, side, deps)
        load_graph(deps.store, state)
        states[side] = state
    last = states[list(plans)[-1]]
    requirements = config_requirements(last.world)
    everyone = actors(*states.values())
    intent_file = fixture / "pr.md"
    if "head" in states and deps.llm is not None and intent_file.is_file():
        title, _, body = intent_file.read_text(encoding="utf-8").partition("\n")
        intent = read_intent(title.removeprefix("# ").strip(), body.strip(), states["head"], deps)
        if intent is not None:
            wanted = [*requirements, *to_requirements(intent)]
            nodes = {n.id: n for n in states["head"].rows.nodes}
            requirements = approved(wanted, intent, nodes)
    fix_actors = None
    if len(states) == 2:
        found = diff(
            analyze(deps.store, states["base"], requirements, everyone),
            analyze(deps.store, states["head"], requirements, everyone),
        )
        fix_actors = sorted({p.actor for p in found.opened})
    return ToolContext(
        store=deps.store,
        states={s.name: s for s in states.values()},
        requirements=requirements,
        actors=everyone,
        adapters=deps.adapters,
        engine=engine or default_engine(),
        fix_actors=fix_actors,
        proposer="mcp-client",
    )


def _text(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


# Repo mode's own tool: it rebuilds the graphs rather than reading one, so it is not in the registry.
CHECK_TOOL = "check_change"
CHECK_DESCRIPTION = (
    "Check the working tree's infrastructure change against main, before a commit or a pull request: "
    "plans it again, reloads both graphs for the other tools, and returns what it opens and closes, where "
    "it lands, each path hop by hop with its file and line, and the fix tested on a graph copy."
)
CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"intent": {"type": "string", "description": "What the change is for, in a sentence."}},
    "additionalProperties": False,
}

Refresh = Callable[[str], tuple[ToolContext, AnalysisResult]]


def build_server(context: ToolContext, recorder: Recorder, refresh: Refresh | None = None) -> Server[Any]:
    """An MCP server whose tools are the recorder's registry, run one at a time in `context`. Given `refresh`
    (repo mode), it also lists `check_change`, which replaces the context with the working tree's new one."""
    registry = recorder.registry
    lock = anyio.Lock()
    current = {"context": context}
    graphs = ", ".join(sorted(context.states))
    instructions = (
        "Theseus reviews infrastructure changes as a graph. Every tool takes the name of a loaded graph "
        f"({graphs}) and node IDs such as user:priya-intern. Every claim a tool returns cites evidence."
    )
    if refresh is not None:
        instructions += f" Call {CHECK_TOOL} after changing the infrastructure, before a commit or a PR."

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        tools = [
            types.Tool(
                name=t.name,
                description=t.description,
                input_schema=t.input_schema,
                annotations=types.ToolAnnotations(
                    read_only_hint=t.read_only, destructive_hint=False, open_world_hint=False
                ),
            )
            for t in registry.tools
        ]
        if refresh is not None:
            tools.append(
                types.Tool(
                    name=CHECK_TOOL,
                    description=CHECK_DESCRIPTION,
                    input_schema=CHECK_SCHEMA,
                    annotations=types.ToolAnnotations(
                        read_only_hint=False, destructive_hint=False, open_world_hint=False
                    ),
                )
            )
        return types.ListToolsResult(tools=tools)

    async def check_change(arguments: dict[str, Any]) -> types.CallToolResult:
        assert refresh is not None
        intent = str(arguments.get("intent", ""))
        new, result = await anyio.to_thread.run_sync(refresh, intent)
        current["context"].cleanup()
        current["context"] = new
        # No model reads the intent here: it comes back as given, for the caller to set against what opened.
        found = verdict(result)
        data = {
            "verdict": found.level,
            "reason": found.title,
            "intent": intent,
            "impact": result.impact.headline if result.impact else "",
            "graphs": result.graphs,
        }
        return types.CallToolResult(
            content=[types.TextContent(text=check_text(result))], structured_content=data
        )

    async def call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        async with lock:
            try:
                if refresh is not None and params.name == CHECK_TOOL:
                    return await check_change(dict(params.arguments or {}))
                result = await anyio.to_thread.run_sync(
                    registry.call, current["context"], params.name, dict(params.arguments or {})
                )
            except TheseusError as e:
                return types.CallToolResult(content=[types.TextContent(text=str(e))], is_error=True)
            except Exception as e:
                log.exception("tool %s failed", params.name)
                text = f"{params.name} failed: {type(e).__name__}: {e}"
                return types.CallToolResult(content=[types.TextContent(text=text)], is_error=True)
        return types.CallToolResult(
            content=[types.TextContent(text=_text(result.data))], structured_content=result.data
        )

    async def list_resources(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        trace = types.Resource(
            name="tool-trace",
            uri=TRACE_URI,
            description="Every tool call so far: tool, input, one-line summary and milliseconds.",
            mime_type="application/json",
        )
        return types.ListResourcesResult(resources=[trace])

    async def read_resource(
        ctx: ServerRequestContext[Any], params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        if params.uri != TRACE_URI:
            raise ValueError(f"no resource {params.uri!r}")
        calls = [c.model_dump(mode="json") for c in recorder.calls]
        contents = types.TextResourceContents(uri=TRACE_URI, mime_type="application/json", text=_text(calls))
        return types.ReadResourceResult(contents=[contents])

    return Server(
        NAME,
        version=__version__,
        instructions=instructions,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_read_resource=read_resource,
    )


async def serve(context: ToolContext, refresh: Refresh | None = None) -> None:
    """Serve the registry on stdin and stdout until the client disconnects."""
    with Recorder(build_registry()) as recorder:
        server = build_server(context, recorder, refresh)
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())


def repo_refresh(root: Path, base: str | None, world_root: str, deps: Deps, folder: Path) -> Refresh:
    """Repo mode: each call plans the working tree's change against the base again, reviews it as
    `python -m theseus check` does, and loads it as the tools' context. Fixtures go under `folder`."""
    from theseus.cli import analyze_fixture, base_ref, planner, prepare_change

    ref = base_ref(root, base)
    plan = planner(root)

    def refresh(intent: str) -> tuple[ToolContext, AnalysisResult]:
        fixture = prepare_change(root, ref, world_root, Path(tempfile.mkdtemp(dir=folder)), plan, intent)
        result = analyze_fixture(fixture, deps.store, deps.jev, deps.settings)
        return context_for_fixture(fixture, deps), result

    return refresh


def main(argv: list[str] | None = None) -> int:
    """Load the fixture, or with `--repo` the working tree's change, into FalkorDB and serve it. Returns 1
    when FalkorDB, the fixture or the change cannot be read."""
    parser = argparse.ArgumentParser(prog="python -m theseus.mcp.server", description=__doc__)
    parser.add_argument("fixture", type=Path, nargs="?", help="a folder under fixtures/")
    parser.add_argument("--repo", type=Path, help="a git checkout: serve its working tree's change instead")
    parser.add_argument("--base", help="with --repo, the commit to compare with: origin/main, else main")
    parser.add_argument("--world", help="with --repo, the world root; THESEUS_WORLD_ROOT by default")
    args = parser.parse_args(argv)
    if (args.fixture is None) == (args.repo is None):
        parser.error("give a fixture folder or --repo, one of the two")
    # stdout carries the protocol; logs go to stderr.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    from theseus.cli import adapters_for, drop_graphs, git, models
    from theseus.config import get_settings
    from theseus.graph.client import get_client
    from theseus.graph.store import FalkorStore

    settings = get_settings()
    work = tempfile.TemporaryDirectory(prefix="theseus-mcp-")
    refresh: Refresh | None = None
    try:
        llm, jev = models(settings)
        store = FalkorStore(get_client(settings))
        if args.repo is not None:
            # Wherever the client starts the server inside the checkout, the repo's root holds the world.
            root = Path(git(args.repo, "rev-parse", "--show-toplevel").decode().strip())
            world_root = args.world or settings.theseus_world_root
            # The plugin's server reads no PR, so the LLM is not needed: the engine and Jev check the change.
            adapters = adapters_for(root / world_root)
            deps = Deps(store=store, adapters=adapters, llm=None, jev=jev, settings=settings)
            refresh = repo_refresh(root, args.base, world_root, deps, Path(work.name))
            context, _ = refresh("")
        else:
            side = "head" if (args.fixture / "head").is_dir() else "base"
            deps = Deps(
                store=store, adapters=adapters_for(args.fixture / side), llm=llm, jev=jev, settings=settings
            )
            context = context_for_fixture(args.fixture, deps)
    except (TheseusError, OSError) as e:
        print(f"theseus mcp: {e}", file=sys.stderr)
        work.cleanup()
        return 1
    try:
        anyio.run(serve, context, refresh)
    finally:
        context.cleanup()
        if refresh is not None:
            drop_graphs(store, next(iter(context.states)))
        work.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
