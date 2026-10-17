"""The ten MCP tools on the intern fixture with MemoryStore (task A6).

The engine functions for min_cut, simulate, blast_radius, rotate_list, choke_points and unused_grants are
not on main yet (E4, E5, FM3, FM4, C3), so those six tools run against fakes that record their arguments;
the other four run the real engine. tests/unit/test_mcp_default_engine.py runs them on the real one.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError, validate

from tests.golden.conftest import expected
from tests.unit.mcp_support import BASE, HEAD, intern_context
from theseus.contracts.engine import CandidateDraft
from theseus.mcp.tools import ToolContext, ToolError, build_registry

PRIYA = "user:priya-intern"
CUSTOMER_DB = "db:customer-db"
SPEC_ORDER = [
    "diff_paths",
    "blast_radius",
    "check_requirements",
    "choke_points",
    "explain_path",
    "min_cut",
    "shortest_route",
    "simulate_fix",
    "unused_grants",
    "secrets_reachable",
]
# One valid input per tool: the 05 table's inputs.
EXAMPLES: dict[str, dict[str, Any]] = {
    "diff_paths": {"base": BASE, "head": HEAD},
    "blast_radius": {"graph": HEAD, "sources": [PRIYA]},
    "check_requirements": {"graph": HEAD},
    "choke_points": {"graph": HEAD, "top": 3},
    "explain_path": {"graph": HEAD, "actor": PRIYA, "target": CUSTOMER_DB},
    "min_cut": {"graph": HEAD, "sources": [PRIYA]},
    "shortest_route": {"graph": HEAD, "source": PRIYA, "target": CUSTOMER_DB},
    "simulate_fix": {
        "graph": HEAD,
        "candidate_id": "B",
        "ops": [{"provider": "aws", "op": "remove_group_member", "args": {"group": "g", "user": "u"}}],
    },
    "unused_grants": {"graph": HEAD},
    "secrets_reachable": {"graph": HEAD, "sources": [PRIYA]},
}


@pytest.fixture
def context() -> ToolContext:
    ctx, _ = intern_context()
    return ctx


def call(ctx: ToolContext, tool: str, **args: Any) -> dict[str, Any]:
    return build_registry().call(ctx, tool, args).data


# The registry --------------------------------------------------------------------------------------------


def test_the_registry_lists_the_ten_tools_of_the_spec_table_in_order() -> None:
    assert [t.name for t in build_registry().tools] == SPEC_ORDER


def test_every_tool_describes_itself_with_a_json_schema_object_that_takes_no_extra_keys() -> None:
    for tool in build_registry().tools:
        Draft202012Validator.check_schema(tool.input_schema)
        assert tool.description.strip(), tool.name
        assert tool.input_schema["type"] == "object", tool.name
        assert tool.input_schema["additionalProperties"] is False, tool.name


def test_each_examples_input_validates_against_the_tools_schema() -> None:
    for tool in build_registry().tools:
        validate(EXAMPLES[tool.name], tool.input_schema)


@pytest.mark.parametrize("name", SPEC_ORDER)
def test_a_missing_or_extra_input_key_is_refused_by_the_schema_and_by_the_tool(
    name: str, context: ToolContext
) -> None:
    tool = build_registry().get(name)
    extra = {**EXAMPLES[name], "bogus": 1}
    with pytest.raises(ValidationError):
        validate(extra, tool.input_schema)
    with pytest.raises(ToolError, match=name):
        build_registry().call(context, name, extra)
    with pytest.raises(ToolError, match=name):
        build_registry().call(context, name, {})


def test_an_unknown_tool_is_refused_and_the_known_ones_are_named(context: ToolContext) -> None:
    with pytest.raises(ToolError, match="diff_paths"):
        build_registry().call(context, "post_comment", {})


def test_only_simulate_fix_is_not_read_only() -> None:
    assert [t.name for t in build_registry().tools if not t.read_only] == ["simulate_fix"]


@pytest.mark.parametrize("name", [n for n in SPEC_ORDER if n != "simulate_fix"])
def test_a_read_only_tool_leaves_the_store_exactly_as_it_found_it(name: str, context: ToolContext) -> None:
    store = context.store
    graphs = store.list_graphs()
    before = {g: store.view(g) for g in graphs}  # type: ignore[attr-defined]
    call(context, name, **EXAMPLES[name])
    assert store.list_graphs() == graphs
    assert {g: store.view(g) for g in graphs} == before  # type: ignore[attr-defined]


@pytest.mark.parametrize("name", SPEC_ORDER)
def test_a_tool_gives_the_same_answer_twice_and_a_summary(name: str, context: ToolContext) -> None:
    first = build_registry().call(context, name, EXAMPLES[name])
    context.cleanup()
    second = build_registry().call(context, name, EXAMPLES[name])
    assert first == second
    assert first.summary and "\n" not in first.summary


# Tools on the real engine ---------------------------------------------------------------------------------


def test_diff_paths_gives_the_opened_closed_and_unchanged_keys_with_routes(context: ToolContext) -> None:
    want = expected("intern")
    got = call(context, "diff_paths", base=BASE, head=HEAD)
    for side in ("opened", "closed", "unchanged"):
        assert [(p["actor"], p["target"], p["route"]) for p in got[side]] == [
            (p["actor"], p["target"], p["route"]) for p in want[side]
        ], side
    assert got["opened"][0]["key"] == f"{PRIYA} -> {CUSTOMER_DB}"


def test_check_requirements_gives_each_requirements_status(context: ToolContext) -> None:
    got = call(context, "check_requirements", graph=HEAD)
    want = {k: v for k, v in expected("intern")["requirements"].items() if k.startswith("R")}
    assert {r["id"]: r["status"] for r in got["requirements"] if r["id"].startswith("R")} == want
    first = got["requirements"][0]
    assert {"id", "status", "principal", "access", "resource"} <= set(first)


def test_explain_path_gives_the_route_with_the_evidence_of_every_step(context: ToolContext) -> None:
    want = next(p for p in expected("intern")["opened"] if p["target"] == CUSTOMER_DB)
    got = call(context, "explain_path", graph=HEAD, actor=PRIYA, target=CUSTOMER_DB)
    assert got["found"] is True and got["route"] == want["route"]
    assert [f"{s['evidence']['file']}:{s['evidence']['line']}" for s in got["steps"]] == want["cites"]
    assert all(s["evidence_id"] and s["evidence"]["address"] for s in got["steps"])


def test_explain_path_says_so_when_there_is_no_route(context: ToolContext) -> None:
    got = call(context, "explain_path", graph=BASE, actor=PRIYA, target=CUSTOMER_DB)
    assert got == {"found": False, "actor": PRIYA, "target": CUSTOMER_DB, "route": [], "steps": []}


def test_shortest_route_gives_the_route_or_none(context: ToolContext) -> None:
    want = next(p for p in expected("intern")["opened"] if p["target"] == CUSTOMER_DB)
    got = call(context, "shortest_route", graph=HEAD, source=PRIYA, target=CUSTOMER_DB)
    assert got["route"] == want["route"] and got["length"] == len(want["route"]) - 1
    assert call(context, "shortest_route", graph=BASE, source=PRIYA, target=CUSTOMER_DB)["route"] is None


def test_an_unknown_graph_or_node_is_an_error_that_names_what_exists(context: ToolContext) -> None:
    with pytest.raises(ToolError, match=BASE):
        call(context, "check_requirements", graph="nope")
    with pytest.raises(ToolError, match="user:nobody"):
        call(context, "explain_path", graph=HEAD, actor="user:nobody", target=CUSTOMER_DB)
    with pytest.raises(ToolError, match="db:nope"):
        call(context, "shortest_route", graph=HEAD, source=PRIYA, target="db:nope")
    with pytest.raises(ToolError, match="user:nobody"):
        call(context, "blast_radius", graph=HEAD, sources=["user:nobody"])


# Tools that call engine functions not on main yet, through the Engine -----------------------------------


def test_min_cut_passes_the_sources_and_every_requirement_and_returns_the_cut() -> None:
    context, fake = intern_context()
    assert fake is not None
    got = call(context, "min_cut", graph=HEAD, sources=[PRIYA])
    ((_, (graph, analysis, sources, requirements)),) = fake.calls
    assert (graph, sources, requirements) == (HEAD, [PRIYA], context.requirements)
    assert PRIYA in analysis.paths and {p.actor for p in analysis.dangerous} >= {PRIYA}
    assert got["value"] == 1 and got["cuttable"] is True and got["cut"][0]["type"] == "MEMBER_OF"
    assert got["sinks"] == sorted({p.target for p in analysis.dangerous if p.actor == PRIYA})


def test_min_cut_with_sinks_looks_only_at_those_targets() -> None:
    context, fake = intern_context()
    assert fake is not None
    got = call(context, "min_cut", graph=HEAD, sources=[PRIYA], sinks=[CUSTOMER_DB])
    ((_, (_, analysis, _, _)),) = fake.calls
    assert {p.target for p in analysis.dangerous} == {CUSTOMER_DB}
    assert got["sinks"] == [CUSTOMER_DB]


def test_blast_radius_and_secrets_reachable_pass_the_sources() -> None:
    context, fake = intern_context()
    assert fake is not None
    radius = call(context, "blast_radius", graph=HEAD, sources=[PRIYA])
    secrets = call(context, "secrets_reachable", graph=HEAD, sources=[PRIYA])
    assert fake.calls == [("blast_radius", (HEAD, [PRIYA])), ("rotate_list", (HEAD, [PRIYA]))]
    assert {p["target"] for p in radius["paths"]} == {CUSTOMER_DB, "s3://demo-company-files/invoices/"} | {
        "secret:prod-db-credentials"
    }
    assert all(p["route"][0] == PRIYA for p in radius["paths"])
    assert secrets == {"secrets": ["secret:payments-api-key", "secret:prod-db-credentials"]}


def test_choke_points_asks_for_the_top_n_and_defaults_to_five() -> None:
    context, fake = intern_context()
    assert fake is not None
    got = call(context, "choke_points", graph=HEAD, top=1)
    assert got == {"choke_points": [{"id": "role:prod-support", "score": 12.5}]}
    call(context, "choke_points", graph=HEAD)
    assert fake.calls == [("choke_points", (HEAD, 1)), ("choke_points", (HEAD, 5))]
    with pytest.raises(ToolError, match="top"):
        call(context, "choke_points", graph=HEAD, top=0)


def test_unused_grants_returns_the_engines_list() -> None:
    context, fake = intern_context()
    assert fake is not None
    got = call(context, "unused_grants", graph=HEAD)
    assert got["unused_grants"][0]["workload"] == "workload:orders-worker"
    assert fake.calls == [("unused_grants", (HEAD,))]


def test_simulate_fix_runs_the_draft_as_a_model_proposal_for_the_actors_the_pr_opened() -> None:
    context, fake = intern_context()
    assert fake is not None
    context.proposer = "test-model"
    got = call(context, "simulate_fix", **EXAMPLES["simulate_fix"])
    ((_, (graph, draft, actors)),) = fake.calls
    assert graph == HEAD and actors == [PRIYA]
    assert isinstance(draft, CandidateDraft)
    assert (draft.id, draft.source, draft.proposed_by) == ("B", "llm", "test-model")
    assert [(o.provider, o.op) for o in draft.ops] == [("aws", "remove_group_member")]
    assert got["verdict"] == "pass" and got["id"] == "B"


def test_simulate_fix_only_adds_a_candidate_graph_and_cleanup_removes_it() -> None:
    context, _ = intern_context()
    before = context.store.list_graphs()
    call(context, "simulate_fix", **EXAMPLES["simulate_fix"])
    assert context.created == [f"{HEAD}-fix-b"]
    assert context.store.list_graphs() == sorted([*before, f"{HEAD}-fix-b"])
    context.cleanup()
    assert context.store.list_graphs() == before and context.created == []


def test_simulate_fix_refuses_a_bad_candidate_id_and_an_unknown_graph(context: ToolContext) -> None:
    with pytest.raises(ToolError, match="candidate"):
        call(context, "simulate_fix", **{**EXAMPLES["simulate_fix"], "candidate_id": "not an id!"})
    with pytest.raises(ToolError, match="nope"):
        call(context, "simulate_fix", **{**EXAMPLES["simulate_fix"], "graph": "nope"})
    assert context.created == []
