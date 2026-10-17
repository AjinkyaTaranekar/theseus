"""PR mode on the code-PR fixture: a typo fix whose new code reads customer-db through its secret, with no IAM
change (C4). The answer key is `fixtures/code-pr/expected.json`, written by humans."""

from __future__ import annotations

from typing import Any

from tests.golden.conftest import FIXTURES, deps_for, expected, pr_text, world
from theseus.agent.llm import LlmReply
from theseus.agent.render import annotations, verdict
from theseus.contracts.engine import GraphState
from theseus.contracts.result import AnalysisResult, NodeInfo, Requirement, compare, project
from theseus.engine.intent_effect import most_sensitive_use, says
from theseus.engine.pipeline import config_requirements, prepare_state, run_pr
from theseus.engine.usage import use_beyond_intent

SCENARIO = "code-pr"
PORTAL = "workload:support-portal"
SECRET = "secret:prod-db-credentials"
DB = "db:customer-db"
EXPORT = "services/support_portal/export.py"


def analyze(llm: Any = None) -> AnalysisResult:
    title, body = pr_text(SCENARIO)
    deps = deps_for(SCENARIO)
    if llm is not None:
        deps = deps.__class__(**{**deps.__dict__, "llm": llm})
    return run_pr(world(SCENARIO, "base"), world(SCENARIO, "head"), title, body, deps)


def states() -> tuple[GraphState, GraphState]:
    deps = deps_for(SCENARIO)
    return (
        prepare_state(world(SCENARIO, "base"), "base", deps)[0],
        prepare_state(world(SCENARIO, "head"), "head", deps)[0],
    )


def with_sensitive(state: GraphState, sensitive: dict[str, bool]) -> GraphState:
    """The state with these nodes' `sensitive` flags changed."""
    nodes = [n.model_copy(update={"sensitive": sensitive.get(n.id, n.sensitive)}) for n in state.rows.nodes]
    return state.model_copy(update={"rows": state.rows.model_copy(update={"nodes": nodes})})


def line_of(file: str, line: int) -> str:
    return (FIXTURES / SCENARIO / "head" / file).read_text(encoding="utf-8").splitlines()[line - 1]


def test_the_code_pr_matches_its_answer_key_apart_from_the_headline_wording() -> None:
    # The answer key shortens the headline; its wording is checked against section 18 below.
    keys = [k for k in expected(SCENARIO) if k != "headline"]
    assert compare(project(analyze()), expected(SCENARIO), keys=keys) == []


def test_two_uses_beyond_intent_cite_the_new_calls_by_file_and_line() -> None:
    uses = analyze().use_beyond_intent
    assert [(u.workload, u.resource, u.access, u.file, u.line, u.unlocks) for u in uses] == [
        (PORTAL, DB, "read", EXPORT, 40, []),
        (PORTAL, SECRET, "read", EXPORT, 33, [DB]),
    ]
    assert "psycopg.connect(" in line_of(EXPORT, 40)
    assert "get_secret_value(SecretId=DB_SECRET)" in line_of(EXPORT, 33)


def test_the_headline_says_the_pr_fixes_a_typo_and_its_code_now_reads_customer_db() -> None:
    result = analyze()
    assert result.intent is not None and not result.intent.grants
    assert says(result.intent.purpose).startswith("fix a typo")
    assert result.headline == (
        f"Your PR says: {says(result.intent.purpose)}. Your code now reads customer-db, a database."
    )


def test_no_iam_change_opens_no_path_and_the_most_sensitive_use_comes_first() -> None:
    result = analyze()
    assert result.opened == [] and result.closed == [] and result.min_cut is None
    assert result.candidates == []
    assert result.use_beyond_intent[0] == most_sensitive_use(result.use_beyond_intent, result.nodes)


def test_the_comment_blocks_the_merge_and_notes_both_code_lines() -> None:
    result = analyze()
    assert {PORTAL, SECRET, DB} <= set(result.nodes)
    assert result.nodes[DB].sensitivity in ("confidential", "regulated")
    check = verdict(result)
    assert (check.level, check.conclusion) == ("blocked", "failure")
    assert "support-portal" in check.title and "customer-db" in check.title
    notes = [(a["path"], a["start_line"]) for a in annotations(result, "demo-infra")]
    assert notes == [(f"demo-infra/{EXPORT}", 33), (f"demo-infra/{EXPORT}", 40)]


def test_calls_main_already_makes_are_not_new() -> None:
    base, head = states()
    assert use_beyond_intent(head, head, config_requirements(world(SCENARIO, "head"))) == []
    # billing-api reads the same secret and database in base and head: neither is listed.
    listed = {u.workload for u in use_beyond_intent(base, head, [])}
    assert listed == {PORTAL}


def test_a_theseus_yaml_requirement_covers_the_database_and_the_secret_that_unlocks_it() -> None:
    base, head = states()
    owner = Requirement(id="R99", principal=PORTAL, access="read", resource=DB, source="config")
    assert use_beyond_intent(base, head, [owner]) == []
    # A requirement for another principal covers nothing for support-portal.
    other = owner.model_copy(update={"principal": "workload:billing-api"})
    assert [u.resource for u in use_beyond_intent(base, head, [other])] == [DB, SECRET]


def test_a_requirement_on_the_secret_alone_leaves_the_database_listed() -> None:
    base, head = states()
    secret = Requirement(id="R99", principal=PORTAL, access="read", resource=SECRET, source="config")
    assert [u.resource for u in use_beyond_intent(base, head, [secret])] == [DB]


def test_words_never_approve_an_intent_requirement_covers_nothing() -> None:
    base, head = states()
    asked = Requirement(id="I1", principal=PORTAL, access="read", resource=DB, source="intent")
    assert [u.resource for u in use_beyond_intent(base, head, [asked])] == [DB, SECRET]


class AsksForTheDatabase:
    """A model that reads the code PR as asking for support-portal to read the customer database."""

    def call(self, purpose: str, messages: list[dict[str, Any]], *args: Any, **kwargs: Any) -> LlmReply:
        grants = [{"principal": PORTAL, "access": "read", "resource": DB}]
        arguments = {"purpose": "Export customer emails for support.", "grants": grants, "suspicious": False}
        return LlmReply(tool="submit_intent", arguments=arguments, model="test", ms=0, key="intent-test")


def test_a_pr_that_asks_for_the_database_is_still_flagged_and_needs_an_owner() -> None:
    """Section 17: a use the intent names is still listed; the headline says the PR asked for it."""
    result = analyze(llm=AsksForTheDatabase())
    assert [u.resource for u in result.use_beyond_intent] == [DB, SECRET]
    assert result.headline == (
        "Your PR asks for customer-db, a database. "
        "Access to sensitive data needs an owner's approval in theseus.yaml."
    )


def test_a_secret_that_is_not_sensitive_is_listed_for_the_sensitive_database_it_unlocks() -> None:
    base, head = states()
    uses = use_beyond_intent(base, with_sensitive(head, {SECRET: False}), [])
    assert [(u.resource, u.unlocks) for u in uses] == [(DB, []), (SECRET, [DB])]


def test_calls_to_data_that_is_not_sensitive_are_not_listed() -> None:
    base, head = states()
    assert use_beyond_intent(base, with_sensitive(head, {SECRET: False, DB: False}), []) == []


def test_a_new_access_on_a_call_main_already_makes_cites_the_new_line() -> None:
    """main reads the secret at one line; the PR adds a write at another. Only the write is new, and it cites
    the line main does not have."""
    base, head = states()
    (edge,) = [e for e in head.rows.edges if (e.type, e.src, e.dst) == ("CALLS", PORTAL, SECRET)]
    old, new = edge.evidence[0], edge.evidence[0].model_copy(update={"line": 34})
    base_edge = edge.model_copy(update={"eid": "b1", "grants": ["read"], "evidence": [old]})
    head_edge = edge.model_copy(update={"grants": ["read", "write"], "evidence": [old, new]})
    base = base.model_copy(
        update={"rows": base.rows.model_copy(update={"edges": [*base.rows.edges, base_edge]})}
    )
    edges = [head_edge if e.eid == edge.eid else e for e in head.rows.edges]
    head = head.model_copy(update={"rows": head.rows.model_copy(update={"edges": edges})})
    uses = [u for u in use_beyond_intent(base, head, []) if u.resource == SECRET]
    assert [(u.access, u.file, u.line) for u in uses] == [("write", EXPORT, 34)]


def test_every_listed_use_is_a_head_call_and_cites_one_of_its_lines() -> None:
    base, head = states()
    calls = {(e.src, e.dst, g): e for e in head.rows.edges if e.type == "CALLS" for g in e.grants}
    uses = use_beyond_intent(base, head, [])
    assert uses
    for use in uses:
        edge = calls[(use.workload, use.resource, use.access)]
        assert (use.file, use.line) in {(ev.file, ev.line) for ev in edge.evidence}


def test_the_result_names_every_node_a_use_reaches_and_is_the_same_on_every_run() -> None:
    first, second = analyze(), analyze()
    for use in first.use_beyond_intent:
        for node in (use.workload, use.resource, *use.unlocks):
            assert isinstance(first.nodes[node], NodeInfo)
    assert first.use_beyond_intent == second.use_beyond_intent
    assert first.headline == second.headline
