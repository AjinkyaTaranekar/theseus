"""Rule generation uses graph provenance and approved requirements, never names."""

from __future__ import annotations

from tests.golden.conftest import deps_for, world
from theseus.contracts.engine import Analysis, GraphState, World
from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow, PathRecord, PathStep, Requirement
from theseus.engine.candidates import rule_candidates
from theseus.engine.pipeline import prepare_state


def edge(identifier: str, source: str, target: str, part: str) -> EdgeRow:
    return EdgeRow(
        eid=identifier,
        type="CAN",
        src=source,
        dst=target,
        kind="configured",
        grants=["read"],
        evidence=[Evidence(address="policy.example", part=part, file="main.txt", line=5)],
    )


def graph(edges: list[EdgeRow]) -> GraphState:
    return GraphState(
        name="test-head",
        world=World(root="/fixture", iac="test"),
        rows=GraphRows(edges=edges, nodes=[NodeRow(id="role:reader", name="reader", labels=["Role"])]),
    )


def path(e: EdgeRow, target: str | None = None) -> PathRecord:
    return PathRecord(
        id=e.eid,
        actor=e.src,
        target=target or e.dst,
        grants=["read"],
        steps=[PathStep(src=e.src, type=e.type, dst=e.dst, evidence="proof")],
    )


def test_revert_selects_added_statement_and_keeps_preexisting_evidence() -> None:
    previous = edge("old-id", "role:reader", "data:private", "Existing")
    added = edge("new-id", "role:reader", "data:private", "Added")
    merged = previous.model_copy(update={"evidence": previous.evidence + added.evidence})
    result = rule_candidates(graph([merged]), Analysis(), [path(merged)], None, base=graph([previous]))
    revert = next(fix for fix in result if fix.id == "A")
    assert [ev.part for ev in revert.changes[0].evidence] == ["Added"]


def test_widening_an_existing_statement_is_not_claimed_to_be_a_new_statement() -> None:
    old = edge("old", "role:reader", "data:public", "Existing")
    new = edge("new", "role:reader", "data:private", "Existing")
    assert "A" not in {
        f.id for f in rule_candidates(graph([new]), Analysis(), [path(new)], None, base=graph([old]))
    }


def test_scope_down_needs_an_approved_requirement_and_certain_matching_grant() -> None:
    dangerous = edge("danger", "role:reader", "data:private", "Shared")
    required = edge("needed", "role:reader", "data:public", "Shared")
    state = graph([dangerous, required])
    analysis = Analysis(paths={"role:reader": [path(required)]})
    req = Requirement(id="R", principal="role:reader", resource="data:public", access="read", source="config")
    assert "S" not in {f.id for f in rule_candidates(state, analysis, [path(dangerous)], None)}
    result = rule_candidates(state, analysis, [path(dangerous)], None, requirements=[req])
    assert next(f for f in result if f.id == "S").changes[0].values == ["data:public"]
    analysis.paths["role:reader"][0].unknown = True
    assert "S" not in {
        f.id for f in rule_candidates(state, analysis, [path(dangerous)], None, requirements=[req])
    }


def test_rule_selection_is_stable_under_input_order_and_does_not_mutate() -> None:
    deps = deps_for("intern")
    head, _ = prepare_state(world("intern", "head"), "head", deps)
    base, _ = prepare_state(world("intern", "base"), "base", deps)
    from theseus.engine.analyze import analyze, diff
    from theseus.engine.pipeline import actors, config_requirements
    from theseus.graph.load import load_graph

    for state in (base, head):
        load_graph(deps.store, state)
    who = actors(base, head)
    reqs = config_requirements(head.world)
    after = analyze(deps.store, head, reqs, who)
    opened = diff(analyze(deps.store, base, reqs, who), after).opened
    before = head.model_dump_json()
    fixes = rule_candidates(head, after, opened, None, base=base, requirements=reqs)
    shuffled = head.model_copy(
        update={"rows": head.rows.model_copy(update={"edges": list(reversed(head.rows.edges))})}
    )
    assert fixes == rule_candidates(
        shuffled, after, list(reversed(opened)), None, base=base, requirements=reqs
    )
    assert head.model_dump_json() == before
    assert {fix.id for fix in fixes} == {"A", "C", "D"}


def test_ranking_facts_are_computed_from_the_patched_graph() -> None:
    import pytest
    from pydantic import ValidationError

    from tests.golden.test_intern import analyze as run
    from theseus.contracts.engine import CandidateDraft

    candidates = {c.id: c for c in run("intern").candidates}
    # Membership is not a direct permission fact; removing assumption drops a permission fact.
    assert candidates["A"].ranking_facts.permissions_removed == 0
    assert candidates["D"].ranking_facts.permissions_removed >= 1
    assert candidates["C"].ranking_facts.unknown_steps >= 1
    with pytest.raises(ValidationError):
        CandidateDraft(
            id="B",
            source="llm",
            proposed_by="model",
            title="Guess",
            ranking_facts={"permissions_removed": 0, "adds_broad_wildcard": False},
        )
