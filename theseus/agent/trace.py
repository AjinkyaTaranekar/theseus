"""Record every tool call into `ToolCall`s, the proof that an agent chose its tools (06-agent.md).

`with Recorder(registry) as rec:` gives a registry whose tools behave exactly as the originals and also log
each call. The records go into `AnalysisResult.tool_trace`.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from types import TracebackType
from typing import Any

from theseus.contracts.result import ToolCall
from theseus.mcp.tools import Registry, Tool, ToolContext, ToolError, ToolResult

log = logging.getLogger(__name__)


class Recorder:
    """A registry that logs every call made through it, for as long as the `with` block lasts.

    A call made after the block ends raises ToolError rather than going unrecorded. A call that fails is
    recorded with an `error: ...` summary and the error is raised again. `clock` returns seconds; tests pass
    a fake one."""

    def __init__(self, registry: Registry, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._calls: list[ToolCall] = []
        self._lock = threading.Lock()
        self._open = False
        self.registry: Registry = registry.wrap(self._wrap)

    @property
    def calls(self) -> list[ToolCall]:
        """The calls so far, oldest first. A copy: changing it does not change the record."""
        with self._lock:
            return list(self._calls)

    def __enter__(self) -> Recorder:
        self._open = True
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self._open = False

    def note(self, tool: str, given: dict[str, Any], summary: str, ms: int = 0) -> ToolCall:
        """Add a step that is not a registry tool, such as the fix loop's `submit_fix` or an evidence check,
        so the trace shows it in order with the tool calls. Raises ToolError once the recorder is closed."""
        if not self._open:
            raise ToolError(f"{tool}: the recorder is closed; this step would not be in the trace")
        call = ToolCall(tool=tool, input=copy.deepcopy(given), summary=summary, ms=ms)
        with self._lock:
            self._calls.append(call)
        log.info("step %s: %s", call.tool, call.summary)
        return call

    def _wrap(self, tool: Tool) -> Tool:
        def recorded(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
            if not self._open:
                raise ToolError(f"{tool.name}: the recorder is closed; this call would not be in the trace")
            given = copy.deepcopy(arguments)
            start = self._clock()
            try:
                result = tool.handler(context, arguments)
            except Exception as e:
                self._add(tool.name, given, f"error: {e}", start)
                raise
            self._add(tool.name, given, result.summary, start)
            return result

        return replace(tool, handler=recorded)

    def _add(self, tool: str, given: dict[str, Any], summary: str, start: float) -> None:
        call = ToolCall(tool=tool, input=given, summary=summary, ms=round((self._clock() - start) * 1000))
        with self._lock:
            self._calls.append(call)
        log.info("tool %s: %s (%d ms)", call.tool, call.summary, call.ms)
