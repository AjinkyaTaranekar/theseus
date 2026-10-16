"""Every LLM call goes through `Llm.call`: one wrapper with record, replay and live modes (06-agent.md).

Replay (the default in tests) reads `recordings/llm/<key>.json` and never imports LiteLLM, so tests never
touch the network. Record calls the model and saves what it said; live calls it and saves nothing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import Field

from theseus.config import Settings
from theseus.contracts.result import Contract
from theseus.errors import ModelError

log = logging.getLogger(__name__)

RECORDINGS = Path("recordings/llm")
RETRIES = 3
TIMEOUT_S = 120
# Worth another try: LiteLLM's names for rate limits, timeouts, overload and 5xx. Inspect names and
# status codes without importing LiteLLM, so replay stays offline.
TRANSIENT = {
    "RateLimitError",
    "Timeout",
    "APIConnectionError",
    "ServiceUnavailableError",
    "BadGatewayError",
    "InternalServerError",
}


class LlmReply(Contract):
    """What the model said: the tool it called and its arguments, any text, and where the answer came from."""

    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    content: str = ""
    model: str
    ms: int
    key: str


def canonical(value: Any) -> str:
    """JSON with sorted keys and no spaces, so the same request always gives the same text."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def recording_key(purpose: str, request: dict[str, Any]) -> str:
    """`<purpose>-<12 hex chars of sha256(canonical request)>`; the request holds model, messages, tools."""
    return f"{purpose}-{hashlib.sha256(canonical(request).encode('utf-8')).hexdigest()[:12]}"


def untrusted(tag: str, text: str) -> str:
    """Text from outside, fenced in `<tag>` so the model reads it as data. The text cannot close the fence."""
    clean = re.sub(
        rf"</?\s*{re.escape(tag)}\s*>", lambda m: m.group(0).replace("<", "&lt;"), text, flags=re.I
    )
    return f"<{tag}>\n{clean}\n</{tag}>"


def _is_transient(e: Exception) -> bool:
    name = type(e).__name__
    if name in TRANSIENT:
        return True
    if name != "APIError":
        return False
    status = getattr(e, "status_code", None)
    if isinstance(status, int):
        return status >= 500
    return "no capacity" in str(e).lower()


def _check_finish_reason(reason: Any, purpose: str, key: str) -> None:
    if reason not in ("tool_calls", "stop"):
        raise ModelError(f"{purpose} ({key}): the model returned finish_reason={reason!r}")


def _normalize(response: Any, purpose: str, key: str) -> dict[str, Any]:
    """The parts of a LiteLLM response the wrapper keeps: provider-neutral, and stable to record."""
    choices = getattr(response, "choices", None)
    if not choices:
        raise ModelError(f"{purpose} ({key}): the model returned no choices")
    choice = choices[0]
    reason = getattr(choice, "finish_reason", None)
    _check_finish_reason(reason, purpose, key)
    message = choice.message
    calls = [{"name": c.function.name, "arguments": c.function.arguments} for c in (message.tool_calls or [])]
    usage = getattr(response, "usage", None)
    return {
        "content": message.content or "",
        "tool_calls": calls,
        "finish_reason": reason,
        "usage": {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        },
    }


def _litellm_completion() -> Callable[..., Any]:
    """LiteLLM's completion, imported only for record and live: with a local price list and no banners."""
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    import litellm

    litellm.suppress_debug_info = True
    return litellm.completion


class Llm:
    """The one way to call the LLM. `completion` and `sleep` are for tests."""

    def __init__(
        self,
        settings: Settings,
        recordings: Path = RECORDINGS,
        completion: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.mode = settings.theseus_mode
        self.recordings = recordings
        self._completion = completion
        self._sleep = sleep

    def call(
        self,
        purpose: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | str | None = None,
        fast: bool = False,
    ) -> LlmReply:
        """The model's reply. Raises ModelError with the purpose and key when there is none to give."""
        model = self.settings.llm_fast_model if fast else self.settings.llm_model
        request = {"model": model, "messages": messages, "tools": tools, "tool_choice": tool_choice}
        key = recording_key(purpose, request)
        path = self.recordings / f"{key}.json"

        if self.mode == "replay":
            if not path.is_file():
                raise ModelError(
                    f"{purpose}: no recording {key} in {self.recordings}; record it with THESEUS_MODE=record"
                )
            saved = json.loads(path.read_text(encoding="utf-8"))
            return self._reply(purpose, key, tool_choice, saved["response"], saved["model"], saved["ms"])

        response, ms = self._live(purpose, key, request)
        reply = self._reply(purpose, key, tool_choice, response, model, ms)
        if self.mode == "record":
            self.recordings.mkdir(parents=True, exist_ok=True)
            saved = {"request": request, "response": response, "model": model, "ms": ms}
            path.write_text(
                json.dumps(saved, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
            )
            log.info("recorded %s", path)
        return reply

    def _live(self, purpose: str, key: str, request: dict[str, Any]) -> tuple[dict[str, Any], int]:
        completion = self._completion or _litellm_completion()
        kwargs: dict[str, Any] = {**request, "temperature": 0, "timeout": TIMEOUT_S}
        if self.settings.llm_api_base:
            kwargs["api_base"] = self.settings.llm_api_base
        if self.settings.llm_api_key:
            kwargs["api_key"] = self.settings.llm_api_key.get_secret_value()
        for attempt in range(RETRIES + 1):
            start = time.perf_counter()
            try:
                response = completion(**kwargs)
            except Exception as e:  # noqa: BLE001 - every provider error is classified, then retried or raised
                if not _is_transient(e) or attempt == RETRIES:
                    raise ModelError(f"{purpose} ({key}): {type(e).__name__}: {e}") from e
                wait = float(2**attempt)
                log.warning("%s: %s, retrying in %.0f s", purpose, type(e).__name__, wait)
                self._sleep(wait)
                continue
            return _normalize(response, purpose, key), int((time.perf_counter() - start) * 1000)
        raise AssertionError("unreachable")

    def _reply(
        self,
        purpose: str,
        key: str,
        tool_choice: dict[str, Any] | str | None,
        response: dict[str, Any],
        model: str,
        ms: int,
    ) -> LlmReply:
        _check_finish_reason(response.get("finish_reason"), purpose, key)
        calls = response.get("tool_calls") or []
        forced = tool_choice.get("function", {}).get("name") if isinstance(tool_choice, dict) else None
        if forced and not any(c["name"] == forced for c in calls):
            raise ModelError(f"{purpose} ({key}): the model did not call {forced}")
        call = next((c for c in calls if c["name"] == forced), calls[0] if calls else None)
        arguments: dict[str, Any] = {}
        if call is not None:
            try:
                parsed = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError as e:
                raise ModelError(f"{purpose} ({key}): the tool arguments are not JSON: {e}") from e
            if not isinstance(parsed, dict):
                raise ModelError(f"{purpose} ({key}): the tool arguments are not an object")
            arguments = parsed
        return LlmReply(
            tool=call["name"] if call else None,
            arguments=arguments,
            content=response.get("content", ""),
            model=model,
            ms=ms,
            key=key,
        )
