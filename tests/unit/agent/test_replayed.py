"""The Try-it page's replay reads a recording as `Llm` reads it: a reply that calls several tools is valid."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from theseus.agent.replayed import ReplayedIntent
from theseus.errors import ModelError

PR = "Context: the same PR text the review sends"


def record(root: Path, name: str, tool_choice: Any, calls: list[tuple[str, dict[str, Any]]]) -> None:
    (root / "llm").mkdir(exist_ok=True)
    saved = {
        "request": {"messages": [{"role": "user", "content": PR}], "tool_choice": tool_choice},
        "response": {
            "finish_reason": "tool_calls",
            "content": "",
            "tool_calls": [{"name": n, "arguments": json.dumps(a)} for n, a in calls],
        },
        "model": "recorded-model",
        "ms": 7,
    }
    (root / "llm" / f"{name}.json").write_text(json.dumps(saved), encoding="utf-8")


def test_a_reply_with_two_tool_calls_replays_the_first_like_the_live_wrapper(tmp_path: Path) -> None:
    record(tmp_path, "fix-0001", "auto", [("explain_path", {"id": "p1"}), ("check_requirements", {})])
    reply = ReplayedIntent(tmp_path).call("fix", [{"role": "user", "content": PR}])
    assert (reply.tool, reply.arguments, reply.key, reply.ms) == ("explain_path", {"id": "p1"}, "fix-0001", 7)


def test_a_forced_tool_is_the_call_replayed(tmp_path: Path) -> None:
    forced = {"type": "function", "function": {"name": "submit_fix"}}
    record(tmp_path, "fix-0002", forced, [("explain_path", {}), ("submit_fix", {"ops": []})])
    reply = ReplayedIntent(tmp_path).call("fix", [{"role": "user", "content": PR}])
    assert (reply.tool, reply.arguments) == ("submit_fix", {"ops": []})


def test_a_pr_text_never_recorded_is_a_model_error(tmp_path: Path) -> None:
    record(tmp_path, "fix-0003", "auto", [("explain_path", {})])
    with pytest.raises(ModelError, match="no recording for this PR text"):
        ReplayedIntent(tmp_path).call("fix", [{"role": "user", "content": "another PR"}])
