"""The recorder wraps every tool in a registry and logs each call into ToolCall records (task A6)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.golden.conftest import expected
from tests.unit.mcp_support import HEAD, intern_context
from theseus.agent.trace import Recorder
from theseus.api.stub import result_from_expected
from theseus.contracts.result import AnalysisResult, ToolCall
from theseus.mcp.tools import Registry, Tool, ToolError, ToolResult, build_registry


class Clock:
    """A clock that moves 25 ms each time it is read, so every call takes the same time."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.025
        return self.now


def echo_registry() -> Registry:
    def echo(ctx: Any, args: dict[str, Any]) -> ToolResult:
        if args.get("fail"):
            raise ToolError("no such graph")
        return ToolResult(data={"echo": args}, summary=f"echoed {len(args)} argument(s)")

    return Registry(
        [
            Tool(name=name, description=name, input_schema={"type": "object"}, handler=echo)
            for name in ("alpha", "beta", "gamma")
        ]
    )


def test_three_calls_are_recorded_in_order_with_input_summary_and_milliseconds() -> None:
    with Recorder(echo_registry(), clock=Clock()) as rec:
        rec.registry.call(None, "gamma", {"n": 1})
        rec.registry.call(None, "alpha", {})
        rec.registry.call(None, "beta", {"x": "y", "z": 2})
    assert rec.calls == [
        ToolCall(tool="gamma", input={"n": 1}, summary="echoed 1 argument(s)", ms=25),
        ToolCall(tool="alpha", input={}, summary="echoed 0 argument(s)", ms=25),
        ToolCall(tool="beta", input={"x": "y", "z": 2}, summary="echoed 2 argument(s)", ms=25),
    ]


def test_the_original_registry_is_not_recorded_and_the_wrapped_one_returns_the_same_result() -> None:
    plain = echo_registry()
    with Recorder(plain) as rec:
        wrapped = rec.registry.call(None, "alpha", {"a": 1})
        direct = plain.call(None, "alpha", {"a": 1})
    assert wrapped == direct
    assert len(rec.calls) == 1


def test_a_failed_call_is_recorded_with_its_error_and_still_raises() -> None:
    with Recorder(echo_registry(), clock=Clock()) as rec:
        with pytest.raises(ToolError, match="no such graph"):
            rec.registry.call(None, "alpha", {"fail": True})
        rec.registry.call(None, "beta", {})
    assert [(c.tool, c.summary) for c in rec.calls] == [
        ("alpha", "error: no such graph"),
        ("beta", "echoed 0 argument(s)"),
    ]


def test_a_call_with_input_the_tool_rejects_is_still_recorded() -> None:
    context, _ = intern_context()
    with Recorder(build_registry()) as rec:
        with pytest.raises(ToolError):
            rec.registry.call(context, "check_requirements", {"graph": HEAD, "bogus": 1})
    (call,) = rec.calls
    assert call.tool == "check_requirements" and call.input == {"graph": HEAD, "bogus": 1}
    assert call.summary.startswith("error: ")


def test_the_recorded_input_is_a_copy() -> None:
    args: dict[str, Any] = {"list": [1]}
    with Recorder(echo_registry()) as rec:
        rec.registry.call(None, "alpha", args)
    args["list"].append(2)
    assert rec.calls[0].input == {"list": [1]}


def test_a_step_that_is_not_a_tool_is_noted_in_order_with_the_tool_calls() -> None:
    with Recorder(echo_registry(), clock=Clock()) as rec:
        rec.registry.call(None, "alpha", {})
        rec.note("submit_fix", {"ops": 2}, "submitted 2 op(s)")
        rec.registry.call(None, "beta", {})
    assert [(c.tool, c.summary) for c in rec.calls] == [
        ("alpha", "echoed 0 argument(s)"),
        ("submit_fix", "submitted 2 op(s)"),
        ("beta", "echoed 0 argument(s)"),
    ]
    with pytest.raises(ToolError, match="closed"):
        rec.note("submit_fix", {}, "late")


def test_a_tool_called_after_the_recorder_closes_is_refused_rather_than_left_out() -> None:
    with Recorder(echo_registry()) as rec:
        pass
    with pytest.raises(ToolError, match="closed"):
        rec.registry.call(None, "alpha", {})
    assert rec.calls == []


def test_real_tools_on_the_intern_fixture_land_in_a_results_tool_trace() -> None:
    context, _ = intern_context()
    with Recorder(build_registry()) as rec:
        rec.registry.call(context, "check_requirements", {"graph": HEAD})
        rec.registry.call(
            context,
            "explain_path",
            {"graph": HEAD, "actor": "user:priya-intern", "target": "db:customer-db"},
        )
        rec.registry.call(context, "unused_grants", {"graph": HEAD})
    assert [c.tool for c in rec.calls] == ["check_requirements", "explain_path", "unused_grants"]
    assert all(c.summary and c.ms >= 0 for c in rec.calls)

    result = result_from_expected(expected("intern")).model_copy(update={"tool_trace": rec.calls})
    assert AnalysisResult.model_validate_json(result.model_dump_json(by_alias=True)).tool_trace == rec.calls
