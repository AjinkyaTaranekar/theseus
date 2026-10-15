"""Sensitivity of every Resource node (04-engine.md section 8): Jev classifies, a person's override wins."""

from __future__ import annotations

import logging
from typing import Protocol, cast

from theseus.agent.jev import JevAnswer
from theseus.contracts.result import GraphRows, NodeInfo, NodeRow, Sensitivity, SensitivitySource
from theseus.contracts.schema import RESOURCE
from theseus.engine.words import kind

log = logging.getLogger(__name__)

SENSITIVE: frozenset[Sensitivity] = frozenset({"confidential", "regulated"})


class Classifier(Protocol):
    def sensitivity(self, resources: list[tuple[str, str, str]]) -> dict[str, JevAnswer]: ...


def classify(nodes: list[NodeRow], jev: Classifier) -> dict[str, JevAnswer]:
    """Jev's answer for every Resource node, keyed by node ID: its class, and whether Jev or the fallback gave
    it. Logs answers that came from the fallback. Jev reads each node's category in the comment's plain words
    (`engine/words.py`), never a vendor's name for it."""
    resources = sorted(
        (n.id, kind(n.id, NodeInfo(category=n.category)), n.name) for n in nodes if RESOURCE in n.labels
    )
    if not resources:
        return {}
    answers = jev.sensitivity(resources)
    uncalibrated = sorted(node for node, a in answers.items() if not a.calibrated)
    if uncalibrated:
        log.warning("sensitivity from the fallback model, uncalibrated: %s", ", ".join(uncalibrated))
    return dict(sorted(answers.items()))


def apply(rows: GraphRows, answers: dict[str, JevAnswer], overrides: dict[str, Sensitivity]) -> GraphRows:
    """The rows with `sensitivity`, `sensitive` and `sensitivity_source` set on every Resource node: an
    override first (`human`), then Jev's class (`jev`, or `fallback` when the fast model answered for Jev),
    else `unclassified` and not sensitive."""
    unknown = sorted(set(overrides) - {n.id for n in rows.nodes if RESOURCE in n.labels})
    if unknown:
        log.warning("sensitive_overrides names no resource in this graph: %s", ", ".join(unknown))
    nodes: list[NodeRow] = []
    for n in rows.nodes:
        if RESOURCE not in n.labels:
            nodes.append(n)
            continue
        answer = answers.get(n.id)
        label: Sensitivity | None = None
        source: SensitivitySource = "unclassified"
        if n.id in overrides:
            label, source = overrides[n.id], "human"
        elif answer is not None and answer.choice is not None:
            label, source = cast(Sensitivity, answer.choice), answer.source
        nodes.append(
            n.model_copy(
                update={
                    "sensitivity": label,
                    "sensitive": label in SENSITIVE,
                    "sensitivity_source": source,
                }
            )
        )
    return rows.model_copy(update={"nodes": nodes})
