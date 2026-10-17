"""The fix agent on the intern PR, replayed from recordings/llm/fix-*.json: never the network.

The run goes through `run_pr`, as the product does, so the recorded requests are the ones a review sends.
Record or refresh them (one live intern run) with the Crusoe key in .env:

    THESEUS_MODE=record pytest -q tests/replay/test_fixer.py
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.golden.conftest import ROOT, RecordedIntent, deps_for, expected, pr_text, world
from theseus.agent.evidence import check
from theseus.agent.fixer import SUBMIT, TOOLS, evidence_aliases
from theseus.agent.llm import Llm, LlmReply
from theseus.config import get_settings
from theseus.contracts.result import AnalysisResult
from theseus.engine.pipeline import prepare_state, run_pr

RECORDINGS = ROOT / "recordings/llm"


class FixFromRecordings:
    """A1's recorded intent, and the fix agent's calls through the real wrapper: replayed by default,
    recorded with THESEUS_MODE=record. Keeps the key of every fix call."""

    def __init__(self) -> None:
        self.intent = RecordedIntent()
        self.llm = Llm(get_settings(), recordings=RECORDINGS)
        self.keys: list[str] = []

    def call(self, purpose: str, messages: list[dict[str, Any]], *args: Any, **kwargs: Any) -> LlmReply:
        if purpose == "intent":
            return self.intent.call(purpose, messages, *args, **kwargs)
        reply = self.llm.call(purpose, messages, *args, **kwargs)
        self.keys.append(reply.key)
        return reply


@pytest.fixture(scope="module")
def run() -> tuple[AnalysisResult, list[dict[str, Any]]]:
    """The intern review, and the recording of every fix call it made, in order."""
    llm = FixFromRecordings()
    deps = replace(deps_for("intern"), llm=llm)
    result = run_pr(world("intern", "base"), world("intern", "head"), *pr_text("intern"), deps)
    assert llm.keys, "the fix agent made no call; is a recording missing? Record with THESEUS_MODE=record"
    recordings = [json.loads((RECORDINGS / f"{k}.json").read_text(encoding="utf-8")) for k in llm.keys]
    return result, recordings


def test_the_recorded_fix_b_passes_with_a_new_narrower_role(
    run: tuple[AnalysisResult, list[dict[str, Any]]],
) -> None:
    """B is the structural fix 02-demo-world.md describes: Priya leaves the group, and a new role trusted only
    by her reads only the app logs. The model names the role; the name is not compared (see the PR)."""
    result, recordings = run
    b = next(c for c in result.candidates if c.id == "B")
    wanted = expected("intern")
    assert b.verdict == wanted["candidates"]["B"] == "pass"
    assert b.recommended and wanted["recommended"] == "B"
    assert (b.source, b.proposed_by) == ("llm", recordings[-1]["model"])
    assert b.paths_left == b.new_paths == b.requirements_broken == b.calls_broken == []
    by_op = {o.op: o.args for o in b.ops}
    assert sorted(by_op) == ["add_policy", "add_role", "remove_membership"]
    assert by_op["remove_membership"] == {"user": "priya-intern", "group": "support-engineers"}
    role = by_op["add_role"]
    assert role["trust_principals"] == ["user:priya-intern"]
    reached = {r for statement in role["statements"] for r in statement["resources"]}
    assert reached == {"arn:aws:s3:::demo-app-logs", "arn:aws:s3:::demo-app-logs/*"}
    assert by_op["add_policy"]["principal"] == "user:priya-intern"


def test_the_trace_lists_the_tools_the_llm_called(run: tuple[AnalysisResult, list[dict[str, Any]]]) -> None:
    result, recordings = run
    called = [call["name"] for r in recordings for call in r["response"]["tool_calls"][:1]]
    assert called[-1] == SUBMIT
    traced = [c.tool for c in result.tool_trace]
    assert [t for t in traced if t in TOOLS] == [name for name in called if name != SUBMIT]
    assert len([t for t in traced if t in TOOLS]) <= 8
    assert {SUBMIT, "verify_fix", "check_evidence"} <= set(traced)
    assert traced[-1] == "check_evidence"


def test_the_rationale_cites_only_what_exists_and_a_made_up_id_is_rejected(
    run: tuple[AnalysisResult, list[dict[str, Any]]],
) -> None:
    result, _ = run
    deps = deps_for("intern")
    states = [prepare_state(world("intern", side), side, deps)[0] for side in ("base", "head")]
    aliases, _ = evidence_aliases(states)
    nodes = {n.id for s in states for n in s.rows.nodes} | {"role:intern-onboarding"}
    b = next(c for c in result.candidates if c.id == "B")
    quoted = {s for o in b.ops for s in json.dumps(o.args).split('"')}
    rationale = result.tool_trace[-1].input["rationale"]
    assert check(rationale, set(aliases.values()), nodes, quoted) == []
    # Every evidence ID it cites is in the result, by the key it stands for.
    by_alias = {a: k for k, a in aliases.items()}
    cited = [a for a in aliases.values() if f"{a} " in f"{rationale} " or f"{a})" in rationale]
    assert all(by_alias[a] in result.evidence for a in cited)
    assert check(rationale + " See E99999.", set(aliases.values()), nodes, quoted) == ["E99999"]


def test_the_recorded_requests_never_hold_the_pr_text(
    run: tuple[AnalysisResult, list[dict[str, Any]]],
) -> None:
    _, recordings = run
    title, body = pr_text("intern")
    for recording in recordings:
        sent = json.dumps(recording["request"])
        assert title not in sent
        assert not [line for line in body.splitlines() if len(line) > 20 and line in sent]


def test_recordings_never_hold_a_key_or_an_endpoint() -> None:
    for path in sorted(Path(RECORDINGS).glob("fix-*.json")):
        text = path.read_text(encoding="utf-8")
        assert "api_key" not in text and "crusoecloud" not in text, path.name
