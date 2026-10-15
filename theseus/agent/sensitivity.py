"""Sensitivity of every Resource node (04-engine.md section 8): Jev classifies, a person's override wins."""

from __future__ import annotations

import logging
from typing import Protocol

from theseus.agent.jev import JevAnswer
from theseus.contracts.result import GraphRows, NodeRow, Sensitivity
from theseus.contracts.schema import RESOURCE, parse_id

log = logging.getLogger(__name__)

SENSITIVE: frozenset[Sensitivity] = frozenset({"confidential", "regulated"})
# The kind as Jev reads it: a category, never a vendor's name for it.
KIND_WORDS = {
    "object_store": "object store location",
    "secret": "secret",
    "database": "database",
    "table": "database table",
}


class Classifier(Protocol):
    def sensitivity(self, resources: list[tuple[str, str, str]]) -> dict[str, JevAnswer]: ...


def classify(nodes: list[NodeRow], jev: Classifier) -> dict[str, Sensitivity]:
    """Jev's class for every Resource node, keyed by node ID. Logs answers that came from the fallback."""
    resources = sorted(
        (n.id, KIND_WORDS.get(n.category or "", parse_id(n.id)[0]), n.name)
        for n in nodes
        if RESOURCE in n.labels
    )
    if not resources:
        return {}
    answers = jev.sensitivity(resources)
    uncalibrated = sorted(node for node, a in answers.items() if not a.calibrated)
    if uncalibrated:
        log.warning("sensitivity from the fallback model, uncalibrated: %s", ", ".join(uncalibrated))
    return {node: a.choice for node, a in sorted(answers.items()) if a.choice is not None}  # type: ignore[misc]


def apply(rows: GraphRows, labels: dict[str, Sensitivity], overrides: dict[str, Sensitivity]) -> GraphRows:
    """The rows with `sensitivity`, `sensitive` and `sensitivity_source` set on every Resource node: an
    override first (`human`), then Jev's label (`jev`), else `unclassified` and not sensitive."""
    unknown = sorted(set(overrides) - {n.id for n in rows.nodes if RESOURCE in n.labels})
    if unknown:
        log.warning("sensitive_overrides names no resource in this graph: %s", ", ".join(unknown))
    nodes: list[NodeRow] = []
    for n in rows.nodes:
        if RESOURCE not in n.labels:
            nodes.append(n)
            continue
        label, source = (overrides[n.id], "human") if n.id in overrides else (labels.get(n.id), "jev")
        if label is None:
            update = {"sensitivity": None, "sensitive": False, "sensitivity_source": "unclassified"}
        else:
            update = {"sensitivity": label, "sensitive": label in SENSITIVE, "sensitivity_source": source}
        nodes.append(n.model_copy(update=update))
    return rows.model_copy(update={"nodes": nodes})
