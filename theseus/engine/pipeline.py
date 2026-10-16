"""One run end to end: worlds into graphs in the store, analysis, and the result (05-contracts.md, `run_pr`).

PR mode here uses the `theseus.yaml` requirements only; intent (A3) and the rest of the result (E4 onward)
build on it. The store is FalkorDB in the product; `MemoryStore` only in offline tests.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from theseus.agent.intent import extract_intent, to_requirements, vocabulary
from theseus.agent.sensitivity import apply, classify
from theseus.contracts.engine import Analysis, Deps, GraphState, World
from theseus.contracts.result import (
    AnalysisResult,
    Coverage,
    Evidence,
    GraphRows,
    Intent,
    NodeInfo,
    PathRecord,
    Requirement,
    Timings,
)
from theseus.contracts.schema import RESOURCE
from theseus.engine.analyze import analyze, diff, step_evidence
from theseus.engine.intent_effect import changes, headline
from theseus.errors import IngestError
from theseus.graph.load import load_graph
from theseus.importer.build import build_rows

log = logging.getLogger(__name__)

ACTOR_LABELS = frozenset({"User", "Workflow", "Workload", "Entry"})


def graph_name(world: World, side: str) -> str:
    """The graph's name in the store (03-graph.md, "One graph per state"): `fx__<scenario>__<side>` for a
    fixture side, `<world>__pr<N>-<side>` for a PR laid out at `<world>/pr<N>/<side>`, else
    `<world>__<side>`."""
    root = Path(world.root)
    if root.parent.parent.name == "fixtures":
        name = f"fx__{root.parent.name}__{side}"
    elif re.fullmatch(r"pr\d+", root.parent.name):
        name = f"{root.parent.parent.name}__{root.parent.name}-{side}"
    else:
        name = f"{root.name}__{side}"
    return re.sub(r"[^a-z0-9_-]", "-", name.lower())


def scenario_of(world: World) -> str | None:
    root = Path(world.root)
    return root.parent.name if root.parent.parent.name == "fixtures" else None


def prepare_state(world: World, side: str, deps: Deps) -> tuple[GraphState, int]:
    """The world's rows with sensitivity set, named for its side, and the milliseconds Jev took. Jev is asked
    only about resources no person has overridden: an override always wins, so its answer would go unused."""
    rows = build_rows(world, {}, deps.adapters)
    overrides = world.config.get("sensitive_overrides") or {}
    ask = [n for n in rows.nodes if RESOURCE in n.labels and n.id not in overrides]
    start = time.perf_counter()
    answers = classify(ask, deps.jev) if ask and deps.jev is not None else {}
    jev_ms = int((time.perf_counter() - start) * 1000)
    rows = apply(rows, answers, overrides)
    return GraphState(name=graph_name(world, side), world=world, rows=rows), jev_ms


def config_requirements(world: World) -> list[Requirement]:
    raw = world.config.get("requirements") or []
    try:
        return sorted(
            (Requirement.model_validate({**r, "source": "config"}) for r in raw), key=lambda r: r.id
        )
    except (TypeError, ValueError) as e:
        raise IngestError("invalid config requirement") from e


def actors(*states: GraphState) -> list[str]:
    """Users, workflows, workloads and the internet entry (04-engine.md section 9), across every state."""
    return sorted({n.id for s in states for n in s.rows.nodes if set(n.labels) & ACTOR_LABELS})


def coverage(world: World, rows: GraphRows, deps: Deps) -> Coverage:
    skipped = sum(world.skipped_types.values())
    calls_skipped = (
        deps.adapters.code.read(world.code_files, rows, world.resources).calls_skipped
        if world.code_files
        else 0
    )
    return Coverage(
        resources=len(world.resources),
        modeled=len(world.resources) - skipped,
        skipped_types=dict(sorted(world.skipped_types.items())),
        code_calls_skipped=calls_skipped,
        nodes=len(rows.nodes),
        edges=len(rows.edges),
    )


def _listed(paths: list[PathRecord], state: GraphState) -> tuple[dict[str, Evidence], dict[str, NodeInfo]]:
    evidence = step_evidence(state.rows)
    nodes = {n.id: n for n in state.rows.nodes}
    cited = {s.evidence: evidence[s.evidence] for p in paths for s in p.steps if s.evidence in evidence}
    info = {
        nid: NodeInfo(category=nodes[nid].category, sensitivity=nodes[nid].sensitivity)
        for p in paths
        for nid in p.route
        if nid in nodes
    }
    return cited, info


def run_pr(base: World, head: World, pr_title: str, pr_body: str, deps: Deps) -> AnalysisResult:
    """PR mode: both states loaded into the store and analyzed with the same actors and requirements, the
    config's and the PR's intent; then the headline says what the PR says against what the change grants."""
    start = time.perf_counter()
    base_state, base_jev = prepare_state(base, "base", deps)
    head_state, head_jev = prepare_state(head, "head", deps)
    for state in (base_state, head_state):
        load_graph(deps.store, state)
    llm_start = time.perf_counter()
    intent = read_intent(pr_title, pr_body, head_state, deps)
    llm_ms = int((time.perf_counter() - llm_start) * 1000)
    # Every requirement gets a status; only theseus.yaml's cover (analyze), and E4 counts the approved ones.
    requirements = [*config_requirements(head), *(to_requirements(intent) if intent else [])]
    who = actors(base_state, head_state)
    before: Analysis = analyze(deps.store, base_state, requirements, who)
    after: Analysis = analyze(deps.store, head_state, requirements, who)
    found = diff(before, after)
    head_evidence, head_nodes = _listed([*found.opened, *found.unchanged], head_state)
    base_evidence, base_nodes = _listed(found.closed, base_state)
    info = {n.id: NodeInfo(category=n.category, sensitivity=n.sensitivity) for n in head_state.rows.nodes}
    total_ms = int((time.perf_counter() - start) * 1000)
    jev_ms = base_jev + head_jev
    return AnalysisResult(
        scenario=scenario_of(head),
        mode="pr",
        graphs={"base": base_state.name, "head": head_state.name},
        intent=intent,
        changes=changes(base, head),
        headline=headline(intent, found.opened, [], info),
        opened=found.opened,
        closed=found.closed,
        unchanged=found.unchanged,
        requirements=after.requirements,
        unknowns=sorted(set(head_state.rows.unknowns)),
        evidence=dict(sorted({**base_evidence, **head_evidence}.items())),
        timings=Timings(
            engine_ms=total_ms - jev_ms - llm_ms, llm_ms=llm_ms, jev_ms=jev_ms, total_ms=total_ms
        ),
        coverage=coverage(head, head_state.rows, deps),
        nodes=dict(sorted({**base_nodes, **head_nodes}.items())),
    )


def read_intent(pr_title: str, pr_body: str, state: GraphState, deps: Deps) -> Intent | None:
    """What the PR says it needs, on the head graph's IDs, through the LLM wrapper (A1). None without one.
    Jev screens the text for steering when it can."""
    if deps.llm is None:
        log.warning("no LLM in Deps; the PR's intent is not read")
        return None
    steering = deps.jev if hasattr(deps.jev, "steering") else None
    return extract_intent(pr_title, pr_body, vocabulary(state.rows), llm=deps.llm, jev=steering)
