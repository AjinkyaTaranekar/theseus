"""One run end to end: worlds into graphs in the store, analysis, and the result (05-contracts.md, `run_pr`).

PR mode reports all requirements, protects approved ones in a combined cut for actors with opened paths,
verifies applicable rule fixes on graph copies, has the fix agent design candidate B, and flags new code
calls to sensitive data no owner approved. Scan mode lists the grants the code never uses and verifies
candidate U, which removes them.
The store is FalkorDB in the product; `MemoryStore` only in offline tests.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from theseus.agent.fixer import AgentFix, design_fix
from theseus.agent.intent import extract_intent, to_requirements, vocabulary
from theseus.agent.sensitivity import apply, classify
from theseus.contracts.adapters import IacResource
from theseus.contracts.engine import Analysis, CandidateDraft, Deps, GraphState, RuleFix, World
from theseus.contracts.posture import PostureReport
from theseus.contracts.result import (
    AnalysisResult,
    Candidate,
    ChangeImpact,
    Coverage,
    Evidence,
    GraphRows,
    Intent,
    MinCut,
    NodeInfo,
    PathRecord,
    Requirement,
    Timings,
)
from theseus.contracts.schema import RESOURCE
from theseus.engine.analyze import analyze, diff, evidence_id, primary_evidence, step_evidence
from theseus.engine.candidates import rank, rule_candidates
from theseus.engine.finding import action_id, containment, match_advisory, secrets_reached, with_finding
from theseus.engine.impact import change_impact
from theseus.engine.intent_effect import approved, changes, headline
from theseus.engine.mincut import min_cut
from theseus.engine.posture import posture
from theseus.engine.simulate import simulate
from theseus.engine.staging import staging_to_prod
from theseus.engine.usage import scan_headline, unused_fix, unused_grants, use_beyond_intent
from theseus.errors import IngestError, ModelError, PatchError
from theseus.graph.algos import choke_points
from theseus.graph.load import load_graph
from theseus.importer.build import build_rows
from theseus.mcp.tools import ToolContext, default_engine

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


def draft_for(
    fix: RuleFix, state: GraphState, deps: Deps, base_resources: list[IacResource] | None = None
) -> CandidateDraft | None:
    """The fix as patch ops from the cloud adapter, or None when it cannot express one of its changes."""
    operations = []
    for change in fix.changes:
        translated = deps.adapters.cloud.ops_for(
            change, state.rows, state.world.resources, base_resources=base_resources
        )
        if not translated:
            return None
        operations.extend(translated)
    unique = {op.model_dump_json(): op for op in operations}
    return CandidateDraft(
        id=fix.id,
        source="rule",
        proposed_by="theseus",
        title=fix.title,
        ops=[unique[k] for k in sorted(unique)],
    )


def breakage_scores(
    candidates: list[Candidate], enforced: list[Requirement], state: GraphState, deps: Deps
) -> tuple[dict[str, float], int]:
    """Jev's chance that each fix breaks something the engine cannot see, and the milliseconds it took. Empty
    without a Jev that scores breakage."""
    start = time.perf_counter()
    scores: dict[str, float] = {}
    if hasattr(deps.jev, "breakage"):
        calls = [
            {"workload": edge.src, "resource": edge.dst, "access": str(edge.props.get("access", ""))}
            for edge in state.rows.edges
            if edge.type == "CALLS"
        ]
        scores = deps.jev.breakage(candidates, enforced, calls)
    return scores, int((time.perf_counter() - start) * 1000)


def run_pr(base: World, head: World, pr_title: str, pr_body: str, deps: Deps) -> AnalysisResult:
    """PR mode: both states loaded into the store and analyzed with the same actors and requirements, the
    config's and the PR's intent, and the code calls head adds; then the headline says what the PR says
    against what the change grants and what its code now reads."""
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
    uses = use_beyond_intent(base_state, head_state, requirements)
    head_rows = {node.id: node for node in head_state.rows.nodes}
    enforced = approved(requirements, intent, head_rows)
    opened_actors = sorted({path.actor for path in found.opened})
    cut = min_cut(deps.store, head_state, after, opened_actors, enforced) if opened_actors else None
    candidates = []
    for fix in rule_candidates(head_state, after, found.opened, cut, base=base_state, requirements=enforced):
        draft = draft_for(fix, head_state, deps, base_resources=base.resources)
        if draft is not None:
            candidates.append(
                simulate(
                    deps.store,
                    head_state,
                    draft,
                    sorted({p.actor for p in found.opened}),
                    enforced,
                    deps.adapters,
                )
            )
    statuses = {status.id: status.status for status in after.requirements}
    fix = agent_fix(base_state, head_state, found.opened, cut, requirements, enforced, who, statuses, deps)
    if fix is not None:
        candidates.append(fix.candidate)
        llm_ms += fix.llm_ms
    scores, risk_ms = breakage_scores(candidates, enforced, head_state, deps)
    candidates = rank(candidates, scores)
    head_evidence, head_nodes = _listed([*found.opened, *found.unchanged], head_state)
    base_evidence, base_nodes = _listed(found.closed, base_state)
    if cut is not None:
        all_evidence = step_evidence(head_state.rows)
        for edge in cut.cut:
            head_evidence[edge.evidence] = all_evidence[edge.evidence]
            for node_id in (edge.src, edge.dst):
                node = head_rows[node_id]
                head_nodes[node_id] = NodeInfo(category=node.category, sensitivity=node.sensitivity)
    for node_id in sorted({n for use in uses for n in (use.workload, use.resource, *use.unlocks)}):
        node = head_rows[node_id]
        head_nodes[node_id] = NodeInfo(category=node.category, sensitivity=node.sensitivity)
    if fix is not None:
        head_evidence.update(fix.evidence)
    info = {n.id: NodeInfo(category=n.category, sensitivity=n.sensitivity) for n in head_state.rows.nodes}
    impact, impact_evidence, impact_nodes = _impact(
        base, head, base_state, head_state, before, after, requirements, deps
    )
    head_evidence.update(impact_evidence)
    head_nodes.update(impact_nodes)
    total_ms = int((time.perf_counter() - start) * 1000)
    jev_ms = base_jev + head_jev + risk_ms
    return AnalysisResult(
        scenario=scenario_of(head),
        mode="pr",
        graphs={"base": base_state.name, "head": head_state.name},
        intent=intent,
        changes=changes(base, head),
        headline=headline(intent, found.opened, uses, info),
        opened=found.opened,
        closed=found.closed,
        unchanged=found.unchanged,
        requirements=after.requirements,
        candidates=candidates,
        unknowns=sorted(set(head_state.rows.unknowns)),
        min_cut=cut,
        use_beyond_intent=uses,
        staging_to_prod=staging_to_prod(Analysis(dangerous=found.opened), head_state),
        choke_points=choke_points(deps.store, head_state),
        evidence=dict(sorted({**base_evidence, **head_evidence}.items())),
        tool_trace=fix.trace if fix is not None else [],
        timings=Timings(
            engine_ms=total_ms - jev_ms - llm_ms, llm_ms=llm_ms, jev_ms=jev_ms, total_ms=total_ms
        ),
        coverage=coverage(head, head_state.rows, deps),
        nodes=dict(sorted({**base_nodes, **head_nodes}.items())),
        impact=impact,
    )


def _impact(
    base: World,
    head: World,
    base_state: GraphState,
    head_state: GraphState,
    before: Analysis,
    after: Analysis,
    requirements: list[Requirement],
    deps: Deps,
) -> tuple[ChangeImpact, dict[str, Evidence], dict[str, NodeInfo]]:
    """The change's impact (engine/impact.py), the evidence of every link it adds or removes, and plain names
    for every node it names."""
    keys: dict[tuple[str, str, str], str] = {}
    evidence: dict[str, Evidence] = {}
    for state in (base_state, head_state):
        nodes = {n.id: n for n in state.rows.nodes}
        for e in state.rows.edges:
            if e.evidence:
                ev = primary_evidence(e, nodes)
                keys[(e.src, e.type, e.dst)] = evidence_id(ev)
                evidence[evidence_id(ev)] = ev
    impact = change_impact(
        base_state,
        head_state,
        before,
        after,
        requirements,
        changes(base, head),
        deps.adapters.cloud.monthly_cost(base.resources),
        deps.adapters.cloud.monthly_cost(head.resources),
        keys,
    )
    used = {e.evidence for e in impact.edges if e.evidence}
    named = {t.id for t in impact.touched} | {
        n for t in impact.touched for n in (*t.reached_by, *t.dependents)
    }
    named |= {n for a in impact.access for n in (a.actor, a.target)}
    named |= {n for r in impact.relies for n in (r.principal, r.resource, *r.via)}
    rows = {n.id: n for state in (base_state, head_state) for n in state.rows.nodes}
    info = {
        n: NodeInfo(category=rows[n].category, sensitivity=rows[n].sensitivity) for n in named if n in rows
    }
    return impact, {k: evidence[k] for k in used if k in evidence}, info


def agent_fix(
    base: GraphState,
    head: GraphState,
    opened: list[PathRecord],
    cut: MinCut | None,
    requirements: list[Requirement],
    enforced: list[Requirement],
    who: list[str],
    statuses: dict[str, str],
    deps: Deps,
) -> AgentFix | None:
    """Candidate B from the fix agent (A7), verified by the engine on its own graph copy, for a PR that opened
    a dangerous path. None without an LLM or an opened path, and when the model gives no fix: the rule fixes
    still stand, and the log says why."""
    if deps.llm is None or not opened:
        return None
    context = ToolContext(
        store=deps.store,
        states={state.name: state for state in (base, head)},
        requirements=enforced,
        actors=who,
        adapters=deps.adapters,
        engine=default_engine(),
        fix_actors=sorted({path.actor for path in opened}),
    )
    try:
        return design_fix(deps.llm, context, head, base, opened, cut, requirements, statuses)
    except ModelError:
        log.warning("the fix agent gave no candidate B; the rule fixes stand alone", exc_info=True)
        return None


def run_finding(world: World, advisory: dict[str, Any], deps: Deps) -> AnalysisResult:
    """Finding mode: the advisory's workflows assumed compromised, what they reach, the cheapest cut between
    them and it, and the secrets to rotate. Only the advisory's Action and versions are read."""
    start = time.perf_counter()
    state, jev_ms = prepare_state(world, "base", deps)
    workflows = match_advisory(state.rows, advisory)
    state = state.model_copy(update={"rows": with_finding(state.rows, advisory)})
    load_graph(deps.store, state)
    requirements = config_requirements(world)
    found: Analysis = analyze(deps.store, state, requirements, workflows)
    cut = min_cut(deps.store, state, found, workflows, requirements) if found.dangerous else None
    evidence, nodes = _listed(found.dangerous, state)
    if cut is not None:
        all_evidence = step_evidence(state.rows)
        by_id = {n.id: n for n in state.rows.nodes}
        for edge in cut.cut:
            evidence[edge.evidence] = all_evidence[edge.evidence]
            for node_id in (edge.src, edge.dst):
                nodes[node_id] = NodeInfo(
                    category=by_id[node_id].category, sensitivity=by_id[node_id].sensitivity
                )
    candidates = contain(state, cut, requirements, workflows, deps)
    scores, risk_ms = finding_breakage(candidates, requirements, advisory, state, deps)
    candidates = rank(candidates, scores)
    urgency, urgency_ms = finding_urgency(advisory, workflows, found.dangerous, state, deps)
    jev_ms += risk_ms + urgency_ms
    total_ms = int((time.perf_counter() - start) * 1000)
    return AnalysisResult(
        scenario=scenario_of(world),
        mode="finding",
        graphs={"base": state.name},
        headline=finding_headline(advisory, workflows, found.dangerous),
        opened=found.dangerous,
        requirements=found.requirements,
        unknowns=sorted(set(state.rows.unknowns)),
        min_cut=cut,
        candidates=candidates,
        rotate=secrets_reached(found, state),
        staging_to_prod=staging_to_prod(found, state),
        choke_points=choke_points(deps.store, state),
        finding={
            "id": advisory["id"],
            "action": action_id(advisory),
            "affected_versions": sorted(advisory.get("affected_versions") or []),
            "workflows": workflows,
            **urgency,
        },
        evidence=dict(sorted(evidence.items())),
        timings=Timings(engine_ms=total_ms - jev_ms, jev_ms=jev_ms, total_ms=total_ms),
        coverage=coverage(world, state.rows, deps),
        nodes=dict(sorted(nodes.items())),
    )


def contain(
    state: GraphState,
    cut: MinCut | None,
    requirements: list[Requirement],
    workflows: list[str],
    deps: Deps,
) -> list[Candidate]:
    """Candidate K, verified on a graph copy like any candidate: the compromised workflows must reach nothing
    sensitive and every requirement must still hold. Empty when there is no K to write."""
    nodes = {n.id for n in state.rows.nodes}
    needed = analyze(deps.store, state, requirements, sorted({r.principal for r in requirements} & nodes))
    fix = containment(state, needed, cut, requirements)
    try:
        draft = draft_for(fix, state, deps) if fix is not None else None
    except PatchError as e:
        log.warning("candidate K cannot be written as patch ops: %s", e)
        draft = None
    if draft is None:
        return []
    return [simulate(deps.store, state, draft, workflows, requirements, deps.adapters)]


def run_scan(world: World, deps: Deps) -> AnalysisResult:
    """Scan mode: `main` loaded and analyzed for every actor, the grants its code never uses that lie on a
    dangerous path, their combined minimum cut, and candidate U to remove them, verified on a graph copy."""
    return _scan(world, deps)[0]


def run_posture(world: World, deps: Deps, advisories: list[dict[str, Any]]) -> PostureReport:
    """The posture of `main` (O1 to O3): the scan, then on the same graph who reaches what, single points of
    failure, articulation points and the cost; then finding mode for each advisory that a workflow on `main`
    is affected by. An advisory's text is read only by finding mode, as untrusted data."""
    scan, state = _scan(world, deps)
    requirements = config_requirements(world)
    lines = deps.adapters.cloud.monthly_cost(world.resources)
    outages = [deps.adapters.cloud.outages(world.resources, state.rows), deps.adapters.ci.outages(state.rows)]
    files = world.iac_files

    def locate(address: str) -> Evidence:
        return deps.adapters.iac.locate(files, address, None)

    found = posture(
        deps.store, state, requirements, actors(state), lines, outages, len(world.code_files), locate
    )
    findings = []
    for advisory in sorted(advisories, key=lambda a: str(a.get("id"))):
        if match_advisory(state.rows, advisory):
            findings.append(run_finding(world, advisory, deps))
        else:
            log.info("advisory %s affects no workflow on main", advisory.get("id"))
    scan = scan.model_copy(update={"choke_points": choke_points(deps.store, state)})
    return PostureReport(scan=scan, posture=found, findings=findings)


def _scan(world: World, deps: Deps) -> tuple[AnalysisResult, GraphState]:
    start = time.perf_counter()
    state, jev_ms = prepare_state(world, "main", deps)
    load_graph(deps.store, state)
    requirements = config_requirements(world)
    analysis = analyze(deps.store, state, requirements, actors(state))
    rows = {node.id: node for node in state.rows.nodes}
    unused = unused_grants(deps.store, state, analysis)
    holders = sorted({grant.workload for grant in unused})
    enforced = approved(requirements, None, rows)
    cut = min_cut(deps.store, state, analysis, holders, enforced) if holders else None
    candidates: list[Candidate] = []
    fix = unused_fix(state, unused)
    try:
        draft = draft_for(fix, state, deps) if fix is not None else None
    except PatchError as e:
        log.warning("candidate U cannot be written as patch ops: %s", e)
        draft = None
    if draft is not None:
        candidates.append(simulate(deps.store, state, draft, holders, enforced, deps.adapters))
    scores, risk_ms = breakage_scores(candidates, enforced, state, deps)
    candidates = rank(candidates, scores)
    all_evidence = step_evidence(state.rows)
    evidence, nodes = _listed(analysis.dangerous, state)
    cited = {grant.evidence for grant in unused} | {edge.evidence for edge in cut.cut if cut is not None}
    evidence.update({key: all_evidence[key] for key in cited})
    named = {grant.workload for grant in unused} | {grant.resource for grant in unused}
    named |= {node for edge in (cut.cut if cut is not None else []) for node in (edge.src, edge.dst)}
    nodes.update({n: NodeInfo(category=rows[n].category, sensitivity=rows[n].sensitivity) for n in named})
    total_ms = int((time.perf_counter() - start) * 1000)
    jev_ms += risk_ms
    result = AnalysisResult(
        scenario=scenario_of(world),
        mode="scan",
        graphs={"main": state.name},
        headline=scan_headline(unused, nodes),
        unchanged=analysis.dangerous,
        requirements=analysis.requirements,
        unknowns=sorted(set(state.rows.unknowns)),
        min_cut=cut,
        candidates=candidates,
        unused_grants=unused,
        evidence=dict(sorted(evidence.items())),
        timings=Timings(engine_ms=total_ms - jev_ms, jev_ms=jev_ms, total_ms=total_ms),
        coverage=coverage(world, state.rows, deps),
        nodes=dict(sorted(nodes.items())),
    )
    return result, state


def finding_breakage(
    candidates: list[Candidate],
    requirements: list[Requirement],
    advisory: dict[str, Any],
    state: GraphState,
    deps: Deps,
) -> tuple[dict[str, float], int]:
    """Jev's chance that each containment fix breaks something the engine cannot see, and the milliseconds it
    took, as `breakage_scores` gives them for a PR or a scan.

    Like urgency, it never blocks containment: an incident needs the blast radius and the rotate list more
    than it needs advice. A Jev that fails leaves no scores, so the fix keeps the engine's ranking, and the
    reason is logged. Jev can still veto when it answers, and never approves."""
    start = time.perf_counter()
    try:
        return breakage_scores(candidates, requirements, state, deps)
    except ModelError:
        log.warning(
            "breakage unavailable for %s; its fix is ranked without a veto", advisory["id"], exc_info=True
        )
        return {}, int((time.perf_counter() - start) * 1000)


def finding_urgency(
    advisory: dict[str, Any], workflows: list[str], dangerous: list[PathRecord], state: GraphState, deps: Deps
) -> tuple[dict[str, Any], int]:
    """Jev's urgency for the finding as `{"urgency": {"p", "source"}}`, and the milliseconds Jev took.

    It never blocks containment: with no Jev, no matched workflow, or a Jev (and fallback) that fails, the
    dict is empty and the reason is logged. The advisory's text goes to Jev as untrusted data; the blast
    radius is worded from the engine's facts alone."""
    if not workflows or not hasattr(deps.jev, "urgency"):
        return {}, 0
    start = time.perf_counter()
    summary = blast_summary(workflows, dangerous, state)
    try:
        answer = deps.jev.urgency(advisory.get("text") or advisory["id"], summary)
    except ModelError:
        log.warning("urgency unavailable for %s; left out", advisory["id"], exc_info=True)
        return {}, int((time.perf_counter() - start) * 1000)
    ms = int((time.perf_counter() - start) * 1000)
    if answer.noul is None:
        log.warning("urgency for %s came back without a probability; left out", advisory["id"])
        return {}, ms
    return {"urgency": {"p": answer.noul, "source": answer.source}}, ms


def blast_summary(workflows: list[str], dangerous: list[PathRecord], state: GraphState) -> str:
    """The blast radius in words, from the engine's facts only: the matched workflows with their environment,
    and each sensitive target with its class and route."""
    nodes = {n.id: n for n in state.rows.nodes}
    lines = [
        "Matched workflows, assumed compromised: "
        + ", ".join(f"{w} ({nodes[w].env})" for w in workflows if w in nodes)
        + "."
    ]
    for path in sorted(dangerous, key=lambda p: (p.actor, p.target)):
        lines.append(
            f"{path.actor} reaches {path.target} ({nodes[path.target].sensitivity or 'unclassified'}) "
            f"in {len(path.steps)} hops: {' -> '.join(path.route)}."
        )
    if not dangerous:
        lines.append("No sensitive resource is reachable.")
    return "\n".join(lines)


def finding_headline(advisory: dict[str, Any], workflows: list[str], dangerous: list[PathRecord]) -> str:
    """One sentence from the engine's facts: how many workflows run the Action and how many sensitive
    resources they reach. Never from the advisory's text."""
    if not workflows:
        return f"No workflow uses {advisory['action']} at an affected version."
    many = len(workflows) != 1
    reached = len({p.target for p in dangerous})
    return (
        f"{len(workflows)} workflow{'s' if many else ''} run{'' if many else 's'} {advisory['action']} "
        f"at an affected version. If compromised, {'they reach' if many else 'it reaches'} "
        f"{reached} sensitive resource{'s' if reached != 1 else ''}."
    )


def read_intent(pr_title: str, pr_body: str, state: GraphState, deps: Deps) -> Intent | None:
    """What the PR says it needs, on the head graph's IDs, through the LLM wrapper (A1). None without one.
    Jev screens the text for steering when it can."""
    if deps.llm is None:
        log.warning("no LLM in Deps; the PR's intent is not read")
        return None
    steering = deps.jev if hasattr(deps.jev, "steering") else None
    return extract_intent(pr_title, pr_body, vocabulary(state.rows), llm=deps.llm, jev=steering)
