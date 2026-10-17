"""The tool registry: ten tools over the engine, served by the MCP server and used in process by the fix loop.

Every tool is read-only except `simulate_fix`, which only adds a candidate graph (05-contracts.md).
A handler turns its input into one engine call and the result into plain JSON; it decides nothing itself. The
engine functions that are not part of the always-present core come in through `Engine`, so a caller (the
server, the fix loop, a test) says which ones to use. Posting comments, committing and opening PRs are not
tools: the API does those, only after a person's command.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from theseus.contracts.adapters import Adapters
from theseus.contracts.engine import (
    Analysis,
    BlastRadius,
    CandidateDraft,
    GraphState,
    GraphStore,
    MinCutFn,
    RotateList,
    Simulate,
    UnusedGrants,
)
from theseus.contracts.result import ChokePoint, PatchOp, PathRecord, Requirement
from theseus.contracts.schema import is_candidate_id
from theseus.engine.analyze import analyze, diff, step_evidence
from theseus.errors import TheseusError

log = logging.getLogger(__name__)

DEFAULT_TOP = 5
MAX_TOP = 50


class ToolError(TheseusError):
    """A tool call that cannot be answered: unknown tool or graph or node, input the schema refuses, or an
    engine failure. The message is meant for the model or person that made the call."""


@dataclass(frozen=True)
class ToolResult:
    """What a tool gives back: JSON-ready `data` for the caller and a one-line `summary` for the trace."""

    data: dict[str, Any]
    summary: str


Handler = Callable[["ToolContext", dict[str, Any]], ToolResult]


@dataclass(frozen=True)
class Tool:
    """One tool: its name, what it is for, the JSON Schema of its input, and the handler that runs it.

    The handler takes the raw input object and validates it itself, so a call with a bad input fails inside
    the handler and the recorder (agent/trace.py) sees it."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler
    read_only: bool = True


class Registry:
    """Tools by name, in the order of the 05 table."""

    def __init__(self, tools: Iterable[Tool]) -> None:
        self.tools: tuple[Tool, ...] = tuple(tools)
        self._by_name = {t.name: t for t in self.tools}
        if len(self._by_name) != len(self.tools):
            raise ValueError("two tools share a name")

    def get(self, name: str) -> Tool:
        """The tool called `name`, or a ToolError that lists the tools there are."""
        try:
            return self._by_name[name]
        except KeyError:
            raise ToolError(f"no tool {name!r}; the tools are: {', '.join(self._by_name)}") from None

    def call(self, context: ToolContext, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Run the tool on `arguments` in `context`. Raises ToolError (or the engine's own error)."""
        return self.get(name).handler(context, arguments)

    def wrap(self, wrapper: Callable[[Tool], Tool]) -> Registry:
        """A new registry whose tools are `wrapper(tool)`; this one is left as it is."""
        return Registry(wrapper(t) for t in self.tools)


# The engine and the context ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Engine:
    """The engine functions behind the tools that need more than `analyze`. Each has the signature its
    Protocol in `contracts/engine.py` gives (`choke_points` also takes how many to return)."""

    min_cut: MinCutFn
    simulate: Simulate
    blast_radius: BlastRadius
    rotate_list: RotateList
    choke_points: Callable[[GraphStore, GraphState, int], list[ChokePoint]]
    unused_grants: UnusedGrants


def default_engine() -> Engine:
    """The engine's own functions. Imported here, so a registry can be built and listed without them."""
    from theseus.engine.finding import blast_radius, rotate_list
    from theseus.engine.mincut import min_cut
    from theseus.engine.simulate import simulate
    from theseus.engine.usage import unused_grants
    from theseus.graph.algos import choke_points

    return Engine(
        min_cut=min_cut,
        simulate=simulate,
        blast_radius=blast_radius,
        rotate_list=rotate_list,
        choke_points=choke_points,
        unused_grants=unused_grants,
    )


@dataclass
class ToolContext:
    """The current analysis, as the tools see it: the store, every loaded graph by name (each a `GraphState`:
    name, world and rows), the requirements and actors the engine analyzes with, and the engine.

    `fix_actors` are the actors whose exposure a simulated fix has to close (the ones a PR opened); when it is
    None, every actor with a dangerous path in the graph being fixed. `created` lists the candidate graphs
    `simulate_fix` added, for `cleanup`."""

    store: GraphStore
    states: dict[str, GraphState]
    requirements: list[Requirement]
    actors: list[str]
    adapters: Adapters
    engine: Engine
    fix_actors: list[str] | None = None
    proposer: str = "agent"
    created: list[str] = field(default_factory=list)
    _analyses: dict[tuple[str, tuple[str, ...]], Analysis] = field(default_factory=dict, repr=False)

    def state(self, graph: str) -> GraphState:
        """The loaded graph called `graph`, or a ToolError that names the graphs there are."""
        try:
            return self.states[graph]
        except KeyError:
            raise ToolError(f"no graph {graph!r}; the graphs are: {', '.join(sorted(self.states))}") from None

    def nodes(self, graph: str, ids: Iterable[str]) -> list[str]:
        """`ids` after checking each is a node of the graph; a ToolError names the ones that are not."""
        known = {n.id for n in self.state(graph).rows.nodes}
        missing = sorted({i for i in ids if i not in known})
        if missing:
            raise ToolError(f"graph {graph!r} has no node {', '.join(missing)}")
        return list(ids)

    def analysis(self, graph: str, actors: Iterable[str] | None = None) -> Analysis:
        """The graph analyzed for these actors (every actor by default) with the context's requirements."""
        who = tuple(sorted(set(self.actors if actors is None else actors)))
        key = (graph, who)
        if key not in self._analyses:
            self._analyses[key] = analyze(self.store, self.state(graph), self.requirements, list(who))
        return self._analyses[key]

    def cleanup(self) -> None:
        """Delete the candidate graphs `simulate_fix` created."""
        for graph in self.created:
            self.store.delete(graph)
        self.created.clear()


# Inputs ---------------------------------------------------------------------------------------------------


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Graph(_Input):
    graph: str = Field(description="Name of a loaded graph.")


class _DiffPaths(_Input):
    base: str = Field(description="Name of the graph before the change.")
    head: str = Field(description="Name of the graph after the change.")


class _Sources(_Graph):
    sources: list[str] = Field(min_length=1, description="Node IDs to start from.")


class _ChokePoints(_Graph):
    top: int = Field(default=DEFAULT_TOP, ge=1, le=MAX_TOP, description="How many nodes to return.")


class _ExplainPath(_Graph):
    actor: str = Field(description="Node ID the path starts at.")
    target: str = Field(description="Node ID the path ends at.")


class _MinCut(_Sources):
    sinks: list[str] | None = Field(
        default=None, description="Targets to cut off. Default: every dangerous target of the sources."
    )


class _ShortestRoute(_Graph):
    source: str = Field(description="Node ID the route starts at.")
    target: str = Field(description="Node ID the route ends at.")


class _SimulateFix(_Graph):
    candidate_id: str = Field(description="A letter such as A, or a name for your own fix.")
    ops: list[PatchOp] = Field(min_length=1, description="The patch operations, from the cloud's op catalog.")


def _tool(
    name: str, description: str, model: type[_Input], *, read_only: bool = True
) -> Callable[[Callable[[ToolContext, Any], ToolResult]], Tool]:
    def build(run: Callable[[ToolContext, Any], ToolResult]) -> Tool:
        def handler(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
            try:
                parsed = model.model_validate(arguments)
            except ValidationError as e:
                problems = "; ".join(
                    f"{'.'.join(str(p) for p in err['loc']) or 'input'}: {err['msg']}" for err in e.errors()
                )
                raise ToolError(f"{name}: invalid input: {problems}") from e
            return run(context, parsed)

        return Tool(name, description, model.model_json_schema(), handler, read_only)

    return build


# Views ------------------------------------------------------------------------------------------------------


def _path_view(p: PathRecord) -> dict[str, Any]:
    return {
        "key": f"{p.actor} -> {p.target}",
        "id": p.id,
        "actor": p.actor,
        "target": p.target,
        "route": p.route,
        "grants": sorted(p.grants),
        "unknown": p.unknown,
        "inferred": p.inferred,
        "sensitivity": p.sensitivity,
    }


def _best(paths: list[PathRecord], target: str) -> PathRecord | None:
    """The path to `target` the engine reports: a certain one before an unknown one, then the fewest steps."""
    options = [p for p in paths if p.target == target]
    return min(options, key=lambda p: (p.unknown, len(p.steps), p.route), default=None)


# The tools, in the order of the 05 table ---------------------------------------------------------------


@_tool(
    "diff_paths",
    "Compare two graphs. Returns the dangerous paths (an actor reaching sensitive data that nothing "
    "requires) the head graph opens, closes or leaves unchanged against the base, each with its route.",
    _DiffPaths,
)
def diff_paths(context: ToolContext, args: _DiffPaths) -> ToolResult:
    found = diff(context.analysis(args.base), context.analysis(args.head))
    data = {side: [_path_view(p) for p in getattr(found, side)] for side in ("opened", "closed", "unchanged")}
    summary = f"{len(found.opened)} opened, {len(found.closed)} closed, {len(found.unchanged)} unchanged"
    return ToolResult(data, summary)


@_tool(
    "blast_radius",
    "What these nodes can reach if they are compromised: the dangerous paths from each source to sensitive "
    "targets, with routes.",
    _Sources,
)
def blast_radius(context: ToolContext, args: _Sources) -> ToolResult:
    state = context.state(args.graph)
    sources = context.nodes(args.graph, sorted(set(args.sources)))
    paths = context.engine.blast_radius(context.store, state, sources)
    targets = sorted({p.target for p in paths})
    return ToolResult(
        {"paths": [_path_view(p) for p in paths]},
        f"{len(targets)} sensitive target(s) reachable from {len(sources)} source(s)",
    )


@_tool(
    "check_requirements",
    "Each requirement (an access the infrastructure must keep granting) and whether it is satisfied, missing "
    "or unknown in this graph.",
    _Graph,
)
def check_requirements(context: ToolContext, args: _Graph) -> ToolResult:
    status = {s.id: s.status for s in context.analysis(args.graph, []).requirements}
    rows = [
        {
            "id": r.id,
            "status": status[r.id],
            "principal": r.principal,
            "access": r.access,
            "resource": r.resource,
            "source": r.source,
        }
        for r in sorted(context.requirements, key=lambda r: r.id)
    ]
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("satisfied", "missing", "unknown")}
    return ToolResult(
        {"requirements": rows}, ", ".join(f"{n} {s}" for s, n in counts.items()) + f" of {len(rows)}"
    )


@_tool(
    "choke_points",
    "The roles most paths go through, by betweenness score, highest first.",
    _ChokePoints,
)
def choke_points(context: ToolContext, args: _ChokePoints) -> ToolResult:
    found = context.engine.choke_points(context.store, context.state(args.graph), args.top)[: args.top]
    rows = [{"id": c.id, "score": c.score} for c in found]
    top = f"; highest {rows[0]['id']} ({rows[0]['score']})" if rows else ""
    return ToolResult({"choke_points": rows}, f"{len(rows)} choke point(s){top}")


@_tool(
    "explain_path",
    "The path the engine reports from an actor to a target, one step per edge, each step with the evidence "
    "(file, line, the piece of the resource) that makes it exist. Found false when there is no path.",
    _ExplainPath,
)
def explain_path(context: ToolContext, args: _ExplainPath) -> ToolResult:
    state = context.state(args.graph)
    context.nodes(args.graph, [args.actor, args.target])
    path = _best(context.analysis(args.graph, [args.actor]).paths.get(args.actor, []), args.target)
    if path is None:
        data: dict[str, Any] = {
            "found": False,
            "actor": args.actor,
            "target": args.target,
            "route": [],
            "steps": [],
        }
        return ToolResult(data, f"no path from {args.actor} to {args.target}")
    evidence = step_evidence(state.rows)
    steps = [
        {
            "from": s.src,
            "type": s.type,
            "to": s.dst,
            "grants": sorted(s.grants),
            "evidence_id": s.evidence,
            "evidence": evidence[s.evidence].model_dump(mode="json") if s.evidence in evidence else None,
        }
        for s in path.steps
    ]
    data = {**_path_view(path), "found": True, "steps": steps}
    return ToolResult(data, f"{len(steps)} step(s) from {args.actor} to {args.target}")


@_tool(
    "min_cut",
    "The fewest edges to remove so the sources reach none of their dangerous targets without losing an "
    "access a requirement needs: its size (value), whether it can be cut, and the edges with evidence.",
    _MinCut,
)
def min_cut(context: ToolContext, args: _MinCut) -> ToolResult:
    state = context.state(args.graph)
    sources = context.nodes(args.graph, sorted(set(args.sources)))
    analysis = context.analysis(args.graph, [*context.actors, *sources])
    if args.sinks is not None:
        wanted = set(context.nodes(args.graph, args.sinks))
        analysis = analysis.model_copy(
            update={"dangerous": [p for p in analysis.dangerous if p.target in wanted]}
        )
    cut = context.engine.min_cut(context.store, state, analysis, sources, context.requirements)
    return ToolResult(
        cut.model_dump(mode="json"),
        f"value {cut.value}, {'cuttable' if cut.cuttable else 'not cuttable'}, {len(cut.cut)} edge(s) to cut",
    )


@_tool(
    "shortest_route",
    "The shortest valid route from one node to another (a certain route before an unknown one), or null.",
    _ShortestRoute,
)
def shortest_route(context: ToolContext, args: _ShortestRoute) -> ToolResult:
    context.nodes(args.graph, [args.source, args.target])
    path = _best(context.analysis(args.graph, [args.source]).paths.get(args.source, []), args.target)
    if path is None:
        data: dict[str, Any] = {"source": args.source, "target": args.target, "route": None, "length": None}
        return ToolResult(data, f"no route from {args.source} to {args.target}")
    data = {
        "source": args.source,
        "target": args.target,
        "route": path.route,
        "length": len(path.steps),
        "unknown": path.unknown,
    }
    return ToolResult(data, f"{len(path.steps)} hop(s) from {args.source} to {args.target}")


@_tool(
    "simulate_fix",
    "Try a fix on a copy of the head graph: apply the patch operations, re-analyze, and return the "
    "candidate with its verdict (pass, fail, unknown or invalid), the paths left, and what it would break. "
    "The only tool that writes, and it only adds the copy.",
    _SimulateFix,
    read_only=False,
)
def simulate_fix(context: ToolContext, args: _SimulateFix) -> ToolResult:
    head = context.state(args.graph)
    if not is_candidate_id(args.candidate_id):
        raise ToolError(f"{args.candidate_id!r} is not a candidate ID: use a letter such as A, or a name")
    actors = (
        context.fix_actors
        if context.fix_actors is not None
        else sorted({p.actor for p in context.analysis(args.graph).dangerous})
    )
    draft = CandidateDraft(
        id=args.candidate_id,
        source="llm",
        proposed_by=context.proposer,
        title=f"Candidate {args.candidate_id}",
        ops=args.ops,
    )
    before = set(context.store.list_graphs())
    try:
        candidate = context.engine.simulate(
            context.store, head, draft, actors, context.requirements, context.adapters
        )
    finally:
        added = sorted(set(context.store.list_graphs()) - before - set(context.created))
        context.created.extend(added)
    return ToolResult(candidate.model_dump(mode="json"), f"candidate {candidate.id}: {candidate.verdict}")


@_tool(
    "unused_grants",
    "Grants to sensitive data that the code of the workload holding them never calls, so removing them costs "
    "nothing.",
    _Graph,
)
def unused_grants(context: ToolContext, args: _Graph) -> ToolResult:
    found = context.engine.unused_grants(context.store, context.state(args.graph))
    return ToolResult(
        {"unused_grants": [g.model_dump(mode="json") for g in found]}, f"{len(found)} unused grant(s)"
    )


@_tool(
    "secrets_reachable",
    "Every secret these nodes can reach by a valid path: the credentials to rotate if they are compromised.",
    _Sources,
)
def secrets_reachable(context: ToolContext, args: _Sources) -> ToolResult:
    state = context.state(args.graph)
    sources = context.nodes(args.graph, sorted(set(args.sources)))
    secrets = sorted(context.engine.rotate_list(context.store, state, sources))
    return ToolResult({"secrets": secrets}, f"{len(secrets)} secret(s) reachable")


def build_registry() -> Registry:
    """The ten tools, in the order of the 05 table."""
    return Registry(
        [
            diff_paths,
            blast_radius,
            check_requirements,
            choke_points,
            explain_path,
            min_cut,
            shortest_route,
            simulate_fix,
            unused_grants,
            secrets_reachable,
        ]
    )
