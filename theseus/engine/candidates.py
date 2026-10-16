"""Graph-derived rule fixes and deterministic ranking of engine-verified candidates."""

from __future__ import annotations

import math

from theseus.contracts.adapters import Change
from theseus.contracts.engine import Analysis, GraphState, RuleFix
from theseus.contracts.result import Candidate, EdgeRow, MinCut, PathRecord, Requirement
from theseus.errors import ModelError


def _key(edge: EdgeRow) -> tuple[str, str, str]:
    return edge.src, edge.type, edge.dst


def _statements(edge: EdgeRow) -> set[tuple[str, str | None]]:
    return {(ev.address, ev.part) for ev in edge.evidence if ev.address and ev.part}


def rule_candidates(
    state: GraphState,
    analysis: Analysis,
    opened: list[PathRecord],
    cut: MinCut | None,
    *,
    base: GraphState | None = None,
    requirements: list[Requirement] | None = None,
) -> list[RuleFix]:
    """Applicable A/C/D/S fixes, sorted by ID, using base provenance and approved requirements.

    The cut is reserved for containment rules. Missing context omits rules that cannot be proved.
    """
    edges = {_key(edge): edge for edge in state.rows.edges}
    nodes = {node.id: node for node in state.rows.nodes}
    old = {_key(edge) for edge in base.rows.edges} if base else set()
    old_statements = {s for edge in base.rows.edges for s in _statements(edge)} if base else set()
    changes: dict[str, list[Change]] = {identifier: [] for identifier in ("A", "C", "D", "S")}
    denies: dict[str, set[str]] = {}
    narrows: dict[str, set[str]] = {}
    for path in sorted(opened, key=lambda path: path.id):
        for step in path.steps:
            edge = edges.get((step.src, step.type, step.dst))
            if edge is None:
                continue
            if base is not None:
                if edge.type == "MEMBER_OF" and _key(edge) not in old:
                    changes["A"].append(Change(kind="remove_edge", eid=edge.eid))
                elif edge.type in {"CAN", "CAN_ASSUME"}:
                    added = _statements(edge) - old_statements
                    selected = sorted(
                        (ev for ev in edge.evidence if (ev.address, ev.part) in added),
                        key=lambda ev: ev.model_dump_json(),
                    )
                    if selected:
                        changes["A"].append(
                            Change(kind="remove_edge", eid=edge.eid, evidence=selected, added_only=True)
                        )
            source = nodes.get(edge.src)
            if edge.type == "CAN_ASSUME" and source and {"Group", "Role"}.intersection(source.labels):
                changes["D"].append(Change(kind="remove_edge", eid=edge.eid))
            if edge.type != "CAN":
                continue
            if source and "Role" in source.labels:
                denies.setdefault(edge.eid, set()).add(path.actor)
            # Retain only access backed by an approved, currently satisfied requirement, from the
            # same evidenced grant. Unrelated non-dangerous locations are not preservation goals.
            for req in requirements or []:
                for required in analysis.paths.get(req.principal, []):
                    if (
                        required.target != req.resource
                        or req.access not in required.grants
                        or required.unknown
                    ):
                        continue
                    for hop in required.steps:
                        retained = edges.get((hop.src, hop.type, hop.dst))
                        if (
                            retained
                            and retained.type == "CAN"
                            and retained.src == edge.src
                            and retained.dst != edge.dst
                            and _statements(edge).intersection(_statements(retained))
                        ):
                            narrows.setdefault(edge.eid, set()).add(retained.dst)
    changes["C"] = [
        Change(kind="deny_principal", eid=eid, values=sorted(values))
        for eid, values in sorted(denies.items())
    ]
    changes["S"] = [
        Change(kind="narrow_grant", eid=eid, values=sorted(values)) for eid, values in sorted(narrows.items())
    ]
    titles = {
        "A": "Revert the added access",
        "C": "Deny the newly exposed principals",
        "D": "Remove the role assumption grant",
        "S": "Scope grants to required locations",
    }
    result = []
    for identifier, edits in sorted(changes.items()):
        unique = {change.model_dump_json(): change for change in edits}
        if unique:
            result.append(
                RuleFix(
                    id=identifier, title=titles[identifier], changes=[unique[key] for key in sorted(unique)]
                )
            )
    return result


def rank(candidates: list[Candidate], break_scores: dict[str, float]) -> list[Candidate]:
    """A fresh ranked list; the first pass is recommended unless an advisory score vetoes it."""
    if len({candidate.id for candidate in candidates}) != len(candidates):
        raise ModelError("candidate IDs must be unique for ranking")
    for score in break_scores.values():
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ModelError("break scores must be finite probabilities")
    verdicts = {"pass": 0, "unknown": 1, "fail": 2, "invalid": 3}
    sources = {"human": 0, "rule": 1, "llm": 2}
    ordered = sorted(
        candidates,
        key=lambda c: (
            verdicts[c.verdict],
            c.ranking_facts.unknown_steps if c.ranking_facts else len(c.unknown),
            len(c.ops),
            c.ranking_facts.permissions_removed if c.ranking_facts else math.inf,
            c.ranking_facts.adds_broad_wildcard if c.ranking_facts else True,
            sources[c.source],
            c.id,
        ),
    )
    first = next((c.id for c in ordered if c.verdict == "pass"), None)
    return [
        c.model_copy(
            update={
                "needs_closer_look": c.needs_closer_look or break_scores.get(c.id, 0) > 0.5,
                "recommended": c.id == first
                and c.ranking_facts is not None
                and not c.needs_closer_look
                and break_scores.get(c.id, 0) <= 0.5,
            }
        )
        for c in ordered
    ]
