"""The fix agent's loop (docs/spec/06-agent.md, "The fix agent"), on the intern fixture with a scripted LLM.

The script plays the model: each reply is the tool it calls and the arguments. The engine, the tools and the
store are real, so every verdict here is the engine's.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace
from typing import Any

import pytest

from tests.golden.conftest import RecordedIntent, deps_for, pr_text, world
from tests.golden.test_simulate_intern import fix_b
from tests.unit.adapters.aws.test_patch import op
from theseus.agent import fixer
from theseus.agent.fixer import (
    CANDIDATE_ID,
    MAX_TOOL_CALLS,
    SUBMIT,
    SYSTEM_PROMPT,
    TOOLS,
    AgentFix,
    design_fix,
    inline_refs,
    plain_rationale,
    tool_specs,
)
from theseus.agent.intent import to_requirements
from theseus.agent.llm import LlmReply
from theseus.contracts.engine import Deps, GraphState
from theseus.contracts.result import MinCut, PathRecord, Requirement
from theseus.engine import pipeline
from theseus.engine.analyze import analyze, diff, step_evidence
from theseus.engine.intent_effect import approved
from theseus.engine.mincut import min_cut
from theseus.errors import ModelError
from theseus.graph.load import load_graph
from theseus.mcp.tools import ToolContext, build_registry, default_engine

PRIYA = "user:priya-intern"
FORCED = {"type": "function", "function": {"name": SUBMIT}}
# Priya's membership: the step every opened path starts with (terraform/people.tf:83).
MEMBERSHIP = "terraform/people.tf:83:aws_iam_user_group_membership.priya_support"


def b_ops() -> list[dict[str, Any]]:
    return [o.model_dump(mode="json") for o in fix_b().ops]


def revert_ops() -> list[dict[str, Any]]:
    return [op("remove_membership", user="priya-intern", group="support-engineers").model_dump(mode="json")]


class Script:
    """Plays the model: one reply per call, in order, and keeps every request it was sent."""

    def __init__(self, *replies: tuple[str | None, Any]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def call(
        self,
        purpose: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | str | None = None,
        fast: bool = False,
    ) -> LlmReply:
        self.requests.append(
            {
                "purpose": purpose,
                "messages": copy.deepcopy(messages),
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        assert self.replies, "the script ran out of replies"
        tool, payload = self.replies.pop(0)
        key = f"{purpose}-test{len(self.requests)}"
        if tool is None:
            return LlmReply(content=payload, model="test-model", ms=0, key=key)
        return LlmReply(tool=tool, arguments=payload, model="test-model", ms=0, key=key)


@dataclass
class Case:
    deps: Deps
    base: GraphState
    head: GraphState
    opened: list[PathRecord]
    cut: MinCut | None
    requirements: list[Requirement]
    enforced: list[Requirement]
    who: list[str]
    statuses: dict[str, str]

    def context(self) -> ToolContext:
        return ToolContext(
            store=self.deps.store,
            states={s.name: s for s in (self.base, self.head)},
            requirements=self.enforced,
            actors=self.who,
            adapters=self.deps.adapters,
            engine=default_engine(),
            fix_actors=sorted({p.actor for p in self.opened}),
        )

    def run(self, llm: Any) -> AgentFix:
        return design_fix(
            llm,
            self.context(),
            self.head,
            self.base,
            self.opened,
            self.cut,
            self.requirements,
            self.statuses,
        )


@pytest.fixture
def case() -> Case:
    """The intern PR as run_pr sees it just before candidate B: graphs loaded, intent read, paths and cut."""
    deps = deps_for("intern")
    base, _ = pipeline.prepare_state(world("intern", "base"), "base", deps)
    head, _ = pipeline.prepare_state(world("intern", "head"), "head", deps)
    for state in (base, head):
        load_graph(deps.store, state)
    intent = pipeline.read_intent(*pr_text("intern"), head, deps)
    assert intent is not None
    requirements = [*pipeline.config_requirements(head.world), *to_requirements(intent)]
    who = pipeline.actors(base, head)
    after = analyze(deps.store, head, requirements, who)
    found = diff(analyze(deps.store, base, requirements, who), after)
    enforced = approved(requirements, intent, {n.id: n for n in head.rows.nodes})
    actors = sorted({p.actor for p in found.opened})
    cut = min_cut(deps.store, head, after, actors, enforced)
    statuses = {s.id: s.status for s in after.requirements}
    return Case(deps, base, head, found.opened, cut, requirements, enforced, who, statuses)


def alias_of(case: Case, key: str) -> str:
    aliases, _ = fixer.evidence_aliases([case.base, case.head])
    return aliases[key]


def rationale(case: Case) -> str:
    return (
        f"Removing {PRIYA} from group:support-engineers ({alias_of(case, MEMBERSHIP)}) closes every opened"
        " path. The new role reads s3://demo-app-logs/ only."
    )


def tools_in(fix: AgentFix) -> list[str]:
    return [call.tool for call in fix.trace]


def test_the_agent_s_fix_is_verified_by_the_engine_and_becomes_b(case: Case) -> None:
    head = case.head.name
    llm = Script(
        ("explain_path", {"graph": head, "actor": PRIYA, "target": "db:customer-db"}),
        ("simulate_fix", {"graph": head, "ops": b_ops()}),
        (SUBMIT, {"rationale": rationale(case), "ops": b_ops()}),
    )
    fix = case.run(llm)
    b = fix.candidate
    assert (b.id, b.source, b.proposed_by, b.title, b.verdict) == (
        "B",
        "llm",
        "test-model",
        fixer.TITLE,
        "pass",
    )
    assert [o.op for o in b.ops] == ["remove_membership", "add_role", "add_policy"]
    assert b.paths_left == b.new_paths == b.requirements_broken == b.calls_broken == []
    assert tools_in(fix) == ["explain_path", "simulate_fix", SUBMIT, "verify_fix", "check_evidence"]
    # Every fix the agent tries is candidate B, whatever it would have named it.
    assert fix.trace[1].input["candidate_id"] == CANDIDATE_ID
    assert fix.rationale == rationale(case)
    assert fix.cites == {alias_of(case, MEMBERSHIP): MEMBERSHIP}
    assert fix.evidence == {MEMBERSHIP: step_evidence(case.head.rows)[MEMBERSHIP]}
    # The graph left behind as candidate B is the engine's own simulation of the final ops.
    assert f"{head.removesuffix('__head')}__fix-b" in case.deps.store.list_graphs()
    assert [r["tool_choice"] for r in llm.requests] == ["auto", "auto", "auto"]


def test_the_model_sees_the_prompt_the_context_and_aliased_evidence(case: Case) -> None:
    head = case.head.name
    llm = Script(
        ("explain_path", {"graph": head, "actor": PRIYA, "target": "db:customer-db"}),
        (SUBMIT, {"rationale": rationale(case), "ops": b_ops()}),
    )
    case.run(llm)
    system, user = llm.requests[0]["messages"]
    assert system == {"role": "system", "content": SYSTEM_PROMPT}
    context = json.loads(user["content"].removeprefix("Context:\n").split("\n\n")[0])
    assert context["graphs"] == {"base": case.base.name, "head": head}
    assert context["min_cut"]["cuttable"] is False and context["min_cut"]["value"] >= 1_000_000
    assert {p["target"] for p in context["opened"]} == {p.target for p in case.opened}
    assert {r["id"]: r["approved"] for r in context["requirements"]}["I1"] is True
    assert all(r["address"].startswith("aws_iam") for r in context["resources"])
    assert {d["id"] for d in context["data"]} >= {"db:customer-db", "s3://demo-app-logs/"}
    # Evidence IDs the model cites are aliases, the same in the context and in every tool result.
    membership = alias_of(case, MEMBERSHIP)
    assert context["opened"][0]["steps"][0]["evidence"] == membership
    assert context["evidence"][membership]["line"] == 83
    result = llm.requests[1]["messages"][-1]
    assert (
        result["role"] == "tool" and membership in result["content"] and MEMBERSHIP not in result["content"]
    )
    # The model is offered the five registry tools, then submit_fix.
    assert [t["function"]["name"] for t in llm.requests[0]["tools"]] == [*TOOLS, SUBMIT]


def test_the_agent_never_sees_the_pr_text(case: Case) -> None:
    llm = Script((SUBMIT, {"rationale": rationale(case), "ops": b_ops()}))
    case.run(llm)
    title, body = pr_text("intern")
    sent = json.dumps(llm.requests)
    assert title not in sent
    assert not [line for line in body.splitlines() if len(line) > 20 and line in sent]


def test_the_engine_verifies_the_submitted_ops_not_the_model_s_simulation(case: Case) -> None:
    """The model simulates fix B and it passes, then submits the revert: the engine fails what was submitted
    and sends the verdict back once."""
    head = case.head.name
    llm = Script(
        ("simulate_fix", {"graph": head, "ops": b_ops()}),
        (SUBMIT, {"rationale": rationale(case), "ops": revert_ops()}),
        (SUBMIT, {"rationale": rationale(case), "ops": b_ops()}),
    )
    fix = case.run(llm)
    assert fix.candidate.verdict == "pass" and len(fix.candidate.ops) == 3
    feedback = llm.requests[2]["messages"][-1]
    assert feedback["role"] == "tool" and "fail" in feedback["content"] and "I1" in feedback["content"]
    assert [c.summary for c in fix.trace if c.tool == "verify_fix"] == [
        "candidate B: fail",
        "candidate B: pass",
    ]


def test_one_retry_then_b_is_the_last_fix_whatever_its_verdict(case: Case) -> None:
    llm = Script(
        (SUBMIT, {"rationale": rationale(case), "ops": revert_ops()}),
        (SUBMIT, {"rationale": rationale(case), "ops": revert_ops()}),
    )
    fix = case.run(llm)
    assert fix.candidate.verdict == "fail" and fix.candidate.requirements_broken == ["I1"]
    assert len(llm.requests) == 2 and not llm.replies


def test_the_budget_is_eight_tool_calls_then_submit_is_forced(case: Case) -> None:
    calls = [("check_requirements", {"graph": case.head.name})] * MAX_TOOL_CALLS
    llm = Script(*calls, (SUBMIT, {"rationale": rationale(case), "ops": b_ops()}))
    fix = case.run(llm)
    assert tools_in(fix).count("check_requirements") == MAX_TOOL_CALLS
    assert [r["tool_choice"] for r in llm.requests] == ["auto"] * MAX_TOOL_CALLS + [FORCED]


def test_a_model_that_never_submits_gives_no_fix(case: Case) -> None:
    calls = [("check_requirements", {"graph": case.head.name})] * (MAX_TOOL_CALLS + 1)
    with pytest.raises(ModelError, match="did not call submit_fix"):
        case.run(Script(*calls))


def test_tool_errors_go_back_to_the_model_and_count(case: Case) -> None:
    llm = Script(
        ("explain_path", {"graph": case.head.name, "actor": "user:nobody", "target": "db:customer-db"}),
        ("blast_radius", {"graph": case.head.name, "sources": [PRIYA]}),
        (SUBMIT, {"rationale": rationale(case), "ops": b_ops()}),
    )
    fix = case.run(llm)
    assert llm.requests[1]["messages"][-1]["content"].startswith("error: graph")
    assert llm.requests[2]["messages"][-1]["content"].startswith("error: no tool 'blast_radius'")
    assert [c.summary.split(":")[0] for c in fix.trace[:2]] == ["error", "error"]
    assert fix.candidate.verdict == "pass"


def test_a_text_answer_is_followed_by_a_forced_submit(case: Case) -> None:
    llm = Script(
        (None, "I will remove the membership."), (SUBMIT, {"rationale": rationale(case), "ops": b_ops()})
    )
    fix = case.run(llm)
    assert llm.requests[1]["tool_choice"] == FORCED
    assert llm.requests[1]["messages"][-1] == {"role": "user", "content": f"Call {SUBMIT} with your fix now."}
    assert fix.candidate.verdict == "pass"


def test_a_submission_that_does_not_parse_is_sent_back_once(case: Case) -> None:
    llm = Script(
        (SUBMIT, {"rationale": rationale(case)}),
        (SUBMIT, {"rationale": rationale(case), "ops": b_ops()}),
    )
    fix = case.run(llm)
    assert "invalid input" in llm.requests[1]["messages"][-1]["content"]
    assert fix.candidate.verdict == "pass"
    with pytest.raises(ModelError, match="never submitted"):
        case.run(Script((SUBMIT, {"rationale": "x"}), (SUBMIT, {"ops": []})))


def test_a_made_up_reference_is_asked_for_once_more(case: Case) -> None:
    llm = Script(
        (SUBMIT, {"rationale": "Remove E999 and role:intern-readonly.", "ops": b_ops()}),
        (SUBMIT, {"rationale": rationale(case), "ops": revert_ops()}),
    )
    fix = case.run(llm)
    assert llm.requests[1]["tool_choice"] == FORCED
    assert "E999, role:intern-readonly" in llm.requests[1]["messages"][-1]["content"]
    # The retry is for the rationale: the verified ops stand.
    assert fix.rationale == rationale(case) and len(fix.candidate.ops) == 3
    checks = [c for c in fix.trace if c.tool == "check_evidence"]
    assert [c.input["bad"] for c in checks] == [["E999", "role:intern-readonly"], []]


def test_twice_made_up_references_give_a_sentence_built_from_the_ops(case: Case) -> None:
    llm = Script(
        (SUBMIT, {"rationale": "See E999.", "ops": b_ops()}),
        (SUBMIT, {"rationale": "See E998.", "ops": b_ops()}),
    )
    fix = case.run(llm)
    assert fix.rationale == (
        "The agent's fix makes 3 changes (remove_membership, add_role, add_policy); "
        "the engine's verdict is pass."
    )
    assert fix.cites == {} and fix.evidence == {}
    assert fix.trace[-1].input == {"rationale": fix.rationale, "bad": ["E998"]}


def test_the_new_role_the_fix_adds_may_be_named(case: Case) -> None:
    named = rationale(case) + " It adds role:intern-onboarding."
    fix = case.run(Script((SUBMIT, {"rationale": named, "ops": b_ops()})))
    assert fix.rationale == plain_rationale(named) and fix.trace[-1].input["bad"] == []


def test_the_rationale_is_one_line_of_at_most_three_sentences() -> None:
    assert plain_rationale("One.\nTwo!  Three? Four. Five.") == "One. Two! Three?"


def test_schemas_stand_alone_and_simulate_fix_takes_the_catalog(case: Case) -> None:
    schema = case.deps.adapters.cloud.ops_schema()
    specs = {t["function"]["name"]: t["function"]["parameters"] for t in tool_specs(build_registry(), schema)}
    assert "$ref" not in json.dumps(specs) and "$defs" not in json.dumps(specs)
    simulate = specs["simulate_fix"]
    assert "candidate_id" not in simulate["properties"] and "candidate_id" not in simulate["required"]
    assert simulate["properties"]["ops"]["items"] == inline_refs(schema)
    assert specs[SUBMIT]["properties"]["ops"]["items"] == inline_refs(schema)
    nested = {"$defs": {"A": {"type": "string"}}, "properties": {"x": {"$ref": "#/$defs/A", "title": "X"}}}
    assert inline_refs(nested) == {"properties": {"x": {"type": "string", "title": "X"}}}


class Dispatch:
    """The intent from A1's recording; the fix from a script (or an error)."""

    def __init__(self, fix: Any) -> None:
        self.intent = RecordedIntent()
        self.fix = fix

    def call(self, purpose: str, messages: list[dict[str, Any]], *args: Any, **kwargs: Any) -> LlmReply:
        if purpose == "intent":
            return self.intent.call(purpose, messages, *args, **kwargs)
        return self.fix.call(purpose, messages, *args, **kwargs)


def run_intern(llm: Any) -> Any:
    deps = replace(deps_for("intern"), llm=llm)
    return pipeline.run_pr(world("intern", "base"), world("intern", "head"), *pr_text("intern"), deps)


def test_run_pr_adds_b_ranks_it_and_shows_its_trace_and_evidence() -> None:
    result = run_intern(Dispatch(Script((SUBMIT, {"rationale": "Removing it closes them.", "ops": b_ops()}))))
    by_id = {c.id: c for c in result.candidates}
    assert by_id["B"].verdict == "pass" and by_id["B"].recommended
    assert [c.tool for c in result.tool_trace] == [SUBMIT, "verify_fix", "check_evidence"]
    assert result.timings.llm_ms >= 0


def test_run_pr_cites_the_rationale_s_evidence_in_the_result(case: Case) -> None:
    """The aliases come from the graphs alone, so the case's alias is run_pr's too."""
    result = run_intern(Dispatch(Script((SUBMIT, {"rationale": rationale(case), "ops": b_ops()}))))
    assert result.evidence[MEMBERSHIP] == step_evidence(case.head.rows)[MEMBERSHIP]
    [check] = [c for c in result.tool_trace if c.tool == "check_evidence"]
    assert check.input == {"rationale": rationale(case), "bad": []}


def test_a_model_error_leaves_the_rule_fixes_standing() -> None:
    class Down:
        def call(self, *args: Any, **kwargs: Any) -> LlmReply:
            raise ModelError("fix (fix-x): ServiceUnavailableError")

    result = run_intern(Dispatch(Down()))
    assert {c.id for c in result.candidates} == {"A", "C", "D"}
    assert result.tool_trace == []
