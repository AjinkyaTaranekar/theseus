"""The models, replayed by what they were asked rather than by request hash, for the Try-it page (task S4).

A recording's key hashes the whole request, which holds the graph's vocabulary: C1 added nine resources after
A1 and A2 recorded, so the demo's requests no longer hash to their keys. The recorded answers are still right
for the same PR text and the same resources, so these look them up by that instead. A PR text or a resource
that was never recorded raises ModelError, as a missing recording does. Nothing here touches the network.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from theseus.agent.jev import Jev, JevAnswer
from theseus.agent.llm import LlmReply
from theseus.config import Settings
from theseus.errors import ModelError

log = logging.getLogger(__name__)

RECORDINGS = Path("recordings")
# A2's one recorded sensitivity answer for the demo world, by node ID.
SENSITIVITY = ("jev/sensitivity-38b5f02e4cbd.json", "jev/sensitivity-4f9306d7b906.json")


class ReplayedIntent:
    """A1's recorded intent answer for the same PR text. Stands in for `Llm` in replay."""

    def __init__(self, recordings: Path = RECORDINGS) -> None:
        self.directory = recordings / "llm"

    def call(self, purpose: str, messages: list[dict[str, Any]], *args: Any, **kwargs: Any) -> LlmReply:
        """The recorded reply for this PR text, or ModelError when none was recorded."""
        pr = messages[-1]["content"]
        for path in sorted(self.directory.glob(f"{purpose}-*.json")):
            recording = json.loads(path.read_text(encoding="utf-8"))
            if recording["request"]["messages"][-1]["content"] != pr:
                continue
            (call,) = recording["response"]["tool_calls"]
            return LlmReply(
                tool=call["name"],
                arguments=json.loads(call["arguments"]),
                model=recording["model"],
                ms=recording["ms"],
                key=path.stem,
            )
        raise ModelError(f"{purpose}: no recording for this PR text in {self.directory}")


class ReplayedJev:
    """A2's recorded sensitivity answers by node ID; steering is replayed by Jev itself, keyed by PR text."""

    def __init__(self, settings: Settings, recordings: Path = RECORDINGS) -> None:
        try:
            saved = {
                k: v
                for name in SENSITIVITY
                for k, v in json.loads((recordings / name).read_text(encoding="utf-8"))["answers"].items()
            }
        except (OSError, ValueError, KeyError) as e:
            raise ModelError(f"sensitivity: cannot read the recorded answers in {recordings}: {e}") from e
        self.answers = {k: JevAnswer.model_validate(v) for k, v in saved.items()}
        self.jev = Jev(settings.model_copy(update={"theseus_mode": "replay"}), recordings=recordings / "jev")

    def sensitivity(self, resources: list[tuple[str, str, str]]) -> dict[str, JevAnswer]:
        """The recorded answer for every resource, or ModelError naming those never recorded."""
        missing = sorted(r[0] for r in resources if r[0] not in self.answers)
        if missing:
            raise ModelError(f"sensitivity: no recorded answer for {missing}")
        return {r[0]: self.answers[r[0]] for r in resources}

    def steering(self, pull_request: dict[str, Any]) -> JevAnswer:
        """Jev's recorded steering answer for this PR text."""
        return self.jev.steering(pull_request)
