"""Engine verification of proposed operations on independent candidate graphs."""

from __future__ import annotations

import logging

from theseus.contracts.adapters import Adapters
from theseus.contracts.engine import Analysis, CandidateDraft, GraphState, GraphStore
from theseus.contracts.result import Candidate, EdgeRow, GraphRows, RankingFacts, Requirement
from theseus.contracts.schema import RESOURCE, is_candidate_id
from theseus.engine.analyze import analyze
from theseus.errors import GraphError, PatchError
from theseus.graph.load import apply_delta, copy_graph, delta
from theseus.importer.build import build_rows

log = logging.getLogger(__name__)


def candidate_graph(head: str, identifier: str) -> str:
    """A candidate's graph name, using the store's lowercase grammar and the head's scope."""
    if not is_candidate_id(identifier):
        raise GraphError(f"not a candidate ID: {identifier!r}")
    if head.endswith("__head"):
        prefix = head.removesuffix("__head") + "__"
    elif head.endswith("-head"):
        prefix = head.removesuffix("-head") + "-"
    else:
        prefix = head + "-"
    return prefix + "fix-" + identifier.lower()


def _sensitivity(head: GraphRows, patched: GraphRows) -> GraphRows:
    existing = {n.id: n for n in head.nodes if RESOURCE in n.labels}
    fields = ("sensitivity", "sensitive", "sensitivity_source")
    return patched.model_copy(
        update={
            "nodes": [
                n.model_copy(update={field: getattr(existing[n.id], field) for field in fields})
                if n.id in existing
                else n
                for n in patched.nodes
            ]
        }
    )


def _permissions(rows: GraphRows) -> set[tuple[str, str, str, str]]:
    return {
        (edge.src, edge.type, edge.dst, access)
        for edge in rows.edges
        if edge.type in {"CAN", "CAN_ASSUME", "TRUSTS"} and edge.kind != "unknown"
        for access in (edge.grants if edge.type == "CAN" else ["assume"])
    }


def _call_label(call: EdgeRow, access: str) -> str:
    where = call.evidence[0] if call.evidence else None
    place = f" ({where.file}:{where.line})" if where and where.file != "unknown" and where.line else ""
    return f"{call.src} -> {call.dst} ({access}){place}"


def _lost_calls(head: GraphRows, before: Analysis, after: Analysis) -> tuple[list[str], list[str]]:
    """The code calls that lose their access, and those whose access becomes unknown (04-engine.md section
    14). A call the head's role could not make anyway is not the fix's doing, so it is not counted."""

    def reaches(analysis: Analysis, call: EdgeRow, access: str, unknown: bool) -> bool:
        return any(
            p.target == call.dst and access in p.grants and p.unknown == unknown
            for p in analysis.paths.get(call.src, [])
        )

    broken, unclear = [], []
    for call in sorted((e for e in head.edges if e.type == "CALLS"), key=lambda e: (e.src, e.dst, e.eid)):
        for access in sorted(set(call.grants)):
            if not reaches(before, call, access, unknown=False) or reaches(
                after, call, access, unknown=False
            ):
                continue
            label = _call_label(call, access)
            (unclear if reaches(after, call, access, unknown=True) else broken).append(label)
    return broken, unclear


def simulate(
    store: GraphStore,
    head: GraphState,
    draft: CandidateDraft,
    actors: list[str],
    requirements: list[Requirement],
    adapters: Adapters,
) -> Candidate:
    """The draft's deterministic verdict after rebuilding and analyzing a copy of the head.

    Callers supply config and approved intent requirements (A3 performs the suspicious-intent filter).
    Sensitive intent never constrains a fix. Existing sensitivity and its provenance are kept without a
    model call. A code call that loses its access fails the candidate; `calls_broken` names it, with its
    file and line.
    """
    name = candidate_graph(head.name, draft.id)
    copy_graph(store, head.name, name)
    result = draft.model_dump()
    try:
        patched_world = head.world.model_copy(deep=True)
        patched_world.resources = adapters.cloud.apply_ops(patched_world.resources, draft.ops)
        traits = adapters.cloud.patch_traits(draft.ops)
    except PatchError as exc:
        return Candidate(**result, verdict="invalid", reason=str(exc))
    rebuilt = _sensitivity(head.rows, build_rows(patched_world, {}, adapters))
    state = GraphState(name=name, world=patched_world, rows=rebuilt)
    apply_delta(store, name, delta(head.rows, rebuilt))

    # All users/workloads are checked for newly introduced exposure; only the requested actors must have
    # their existing exposure closed. Unrelated pre-existing dangerous paths do not veto a candidate.
    actor_labels = {"User", "Workflow", "Workload", "Entry"}
    who = sorted(
        set(actors)
        | {
            node.id
            for graph in (head, state)
            for node in graph.rows.nodes
            if actor_labels.intersection(node.labels)
        }
    )
    before = analyze(store, head, requirements, who)
    after = analyze(store, state, requirements, who)
    requested = set(actors)
    remaining = [path for path in after.dangerous if path.actor in requested]
    old_pairs = {(path.actor, path.target) for path in before.dangerous}
    old_certain = {(path.actor, path.target) for path in before.dangerous if not path.unknown}
    opened = [
        path
        for path in after.dangerous
        if (path.actor, path.target) not in (old_pairs if path.unknown else old_certain)
    ]
    paths_left = sorted({path.id for path in remaining})
    new_paths = sorted({path.id for path in opened})
    target_nodes = {node.id: node for node in head.rows.nodes}
    enforced = {
        req.id
        for req in requirements
        if req.source == "config"
        or req.resource not in target_nodes
        or not target_nodes[req.resource].sensitive
    }
    old_status = {req.id: req.status for req in before.requirements}
    broken = sorted(
        req.id
        for req in after.requirements
        if req.id in enforced and req.status == "missing" and old_status[req.id] != "missing"
    )
    calls_broken, calls_unknown = _lost_calls(head.rows, before, after)
    unknown = sorted(
        {
            *(f"call {label}: access is unknown" for label in calls_unknown),
            *(
                f"requirement {req.id}: access is unknown"
                for req in after.requirements
                if req.id in enforced and req.status == "unknown" and old_status[req.id] != "unknown"
            ),
            *(
                f"path {path.id}: {path.actor} -> {path.target} is unknown"
                for path in [*remaining, *opened]
                if path.unknown
            ),
        }
    )
    certain = sorted({path.id for path in [*remaining, *opened] if not path.unknown})
    if certain or broken or calls_broken:
        reasons = []
        if certain:
            reasons.append("Dangerous paths remain or were introduced: " + ", ".join(certain))
        if broken:
            reasons.append("Required access lost: " + ", ".join(broken))
        if calls_broken:
            reasons.append("Code would break, it calls: " + ", ".join(calls_broken))
        verdict, reason = "fail", "; ".join(reasons)
    elif unknown:
        verdict, reason = "unknown", "; ".join(unknown)
    else:
        verdict, reason = (
            "pass",
            "Requested dangerous paths are closed; no new dangerous path or loss of required access.",
        )
    unknown_edges = {(edge.src, edge.type, edge.dst) for edge in rebuilt.edges if edge.kind == "unknown"}
    return Candidate(
        **result,
        verdict=verdict,
        reason=reason,
        paths_left=paths_left,
        new_paths=new_paths,
        requirements_broken=broken,
        calls_broken=calls_broken,
        unknown=unknown,
        ranking_facts=RankingFacts(
            unknown_steps=len(
                {
                    (step.src, step.type, step.dst)
                    for path in [*remaining, *opened]
                    for step in path.steps
                    if (step.src, step.type, step.dst) in unknown_edges
                }
            ),
            permissions_removed=len(_permissions(head.rows) - _permissions(rebuilt)),
            adds_broad_wildcard=traits.adds_broad_wildcard,
        ),
    )
