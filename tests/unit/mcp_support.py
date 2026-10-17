"""A tool context on the intern fixture and an engine of fakes, shared by the MCP and trace tests."""

from __future__ import annotations

from typing import Any

from tests.golden.conftest import deps_for, world
from theseus.contracts.engine import Analysis, CandidateDraft, GraphState, GraphStore
from theseus.contracts.result import (
    Candidate,
    ChokePoint,
    CutEdge,
    MinCut,
    PathRecord,
    Requirement,
    UnusedGrant,
)
from theseus.engine.analyze import analyze, diff
from theseus.engine.pipeline import actors, config_requirements, prepare_state
from theseus.graph.load import load_graph
from theseus.mcp.tools import Engine, ToolContext

SCENARIO = "intern"
BASE = f"fx__{SCENARIO}__base"
HEAD = f"fx__{SCENARIO}__head"


class FakeEngine:
    """Engine functions that are not on main yet. Each records its arguments and returns a fixed answer."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def min_cut(
        self,
        store: GraphStore,
        state: GraphState,
        analysis: Analysis,
        sources: list[str],
        requirements: list[Requirement],
    ) -> MinCut:
        self.calls.append(("min_cut", (state.name, analysis, sources, requirements)))
        sinks = sorted({p.target for p in analysis.dangerous if p.actor in sources})
        return MinCut(
            sources=sources,
            sinks=sinks,
            value=1,
            cuttable=True,
            cut=[CutEdge(eid="e1", src="user:priya-intern", type="MEMBER_OF", dst="group:x", evidence="E1")],
        )

    def simulate(
        self,
        store: GraphStore,
        head: GraphState,
        draft: CandidateDraft,
        actors: list[str],
        requirements: list[Requirement],
        adapters: Any,
    ) -> Candidate:
        self.calls.append(("simulate", (head.name, draft, actors)))
        store.copy(head.name, f"{head.name}-fix-{draft.id.lower()}")
        return Candidate(
            **draft.model_dump(),
            verdict="pass",
            reason="Requested dangerous paths are closed.",
            recommended=False,
            seconds=0.0,
        )

    def blast_radius(self, store: GraphStore, state: GraphState, workflows: list[str]) -> list[PathRecord]:
        self.calls.append(("blast_radius", (state.name, workflows)))
        return analyze(store, state, [], workflows).dangerous

    def rotate_list(self, store: GraphStore, state: GraphState, workflows: list[str]) -> list[str]:
        self.calls.append(("rotate_list", (state.name, workflows)))
        return ["secret:payments-api-key", "secret:prod-db-credentials"]

    def choke_points(self, store: GraphStore, state: GraphState, top: int) -> list[ChokePoint]:
        self.calls.append(("choke_points", (state.name, top)))
        return [
            ChokePoint(id="role:prod-support", score=12.5),
            ChokePoint(id="role:github-deploy", score=3.0),
        ][:top]

    def unused_grants(self, store: GraphStore, state: GraphState) -> list[UnusedGrant]:
        self.calls.append(("unused_grants", (state.name,)))
        return [
            UnusedGrant(
                workload="workload:orders-worker",
                resource="db:customer-db",
                access="read",
                eid="e9",
                evidence="E9",
            )
        ]


def fake_engine() -> tuple[Engine, FakeEngine]:
    fake = FakeEngine()
    engine = Engine(
        min_cut=fake.min_cut,
        simulate=fake.simulate,
        blast_radius=fake.blast_radius,
        rotate_list=fake.rotate_list,
        choke_points=fake.choke_points,
        unused_grants=fake.unused_grants,
    )
    return engine, fake


def intern_context(engine: Engine | None = None) -> tuple[ToolContext, FakeEngine | None]:
    """Both intern graphs loaded in a MemoryStore, with the config requirements and every actor."""
    deps = deps_for(SCENARIO)
    states = {}
    for side in ("base", "head"):
        state, _ = prepare_state(world(SCENARIO, side), side, deps)
        load_graph(deps.store, state)
        states[state.name] = state
    fake = None
    if engine is None:
        engine, fake = fake_engine()
    requirements = config_requirements(states[HEAD].world)
    everyone = actors(*states.values())
    opened = diff(
        analyze(deps.store, states[BASE], requirements, everyone),
        analyze(deps.store, states[HEAD], requirements, everyone),
    ).opened
    context = ToolContext(
        store=deps.store,
        states=states,
        requirements=requirements,
        actors=everyone,
        adapters=deps.adapters,
        engine=engine,
        fix_actors=sorted({p.actor for p in opened}),
    )
    return context, fake
