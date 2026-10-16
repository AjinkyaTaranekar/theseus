"""Says versus grants (04-engine.md section 18): the headline, which intent counts, and what the change does.

Words explain a change but never approve it: intent never covers sensitive data, and the headline names what
the change grants against what the PR says it is for. Nodes are named as the comment names them
(`engine/words.py`).
"""

from __future__ import annotations

import logging

from theseus.contracts.engine import World
from theseus.contracts.result import (
    BeyondIntent,
    Intent,
    NodeInfo,
    NodeRow,
    PathRecord,
    Requirement,
    ResourceChange,
)
from theseus.engine.words import article, kind, name

log = logging.getLogger(__name__)

RANK = {"regulated": 0, "confidential": 1}
OWNER = "Access to sensitive data needs an owner's approval in theseus.yaml."
VERBS = {"create": "adds", "update": "changes", "delete": "removes"}


def describe(node: str, nodes: dict[str, NodeInfo]) -> str:
    """The node's own name and what it is: `customer-db, a database`."""
    return f"{name(node)}, {article(kind(node, nodes.get(node)))}"


def _class(node: str, nodes: dict[str, NodeInfo], fallback: str | None = None) -> int:
    info = nodes.get(node)
    return RANK.get((info.sensitivity if info else None) or fallback or "", len(RANK))


def most_sensitive(paths: list[PathRecord], nodes: dict[str, NodeInfo]) -> PathRecord | None:
    """`regulated` before `confidential`, then a target reached through what unlocks it (a database before its
    secret), then the shortest path, then by ID."""
    if not paths:
        return None
    return min(
        paths,
        key=lambda p: (
            _class(p.target, nodes, p.sensitivity),
            0 if p.steps and p.steps[-1].type == "UNLOCKS" else 1,
            len(p.steps),
            p.target,
        ),
    )


def most_sensitive_use(uses: list[BeyondIntent], nodes: dict[str, NodeInfo]) -> BeyondIntent | None:
    """The most sensitive use, a database before the secret that unlocks it, then by resource."""
    if not uses:
        return None
    unlocked = {u for use in uses for u in use.unlocks}
    return min(
        uses, key=lambda u: (_class(u.resource, nodes), 0 if u.resource in unlocked else 1, u.resource)
    )


def _says(purpose: str) -> str:
    """The purpose as the middle of a sentence: no full stop, and a first capital lowered unless it starts an
    acronym or a name."""
    text = purpose.strip().rstrip(".").strip()
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        text = text[0].lower() + text[1:]
    return text


def headline(
    intent: Intent | None, opened: list[PathRecord], beyond: list[BeyondIntent], nodes: dict[str, NodeInfo]
) -> str:
    """The comment's first line: what the PR says against what the change grants (04-engine.md section 18)."""
    target = most_sensitive(opened, nodes)
    use = most_sensitive_use(beyond, nodes)
    if intent is None or not intent.stated or not intent.purpose.strip():
        if target is not None:
            return f"This PR doesn't say what it's for. Your change grants {describe(target.target, nodes)}."
        if use is not None:
            return f"This PR doesn't say what it's for. Your code now reads {describe(use.resource, nodes)}."
        return "This PR doesn't say what it's for. It opens no dangerous path."
    asked = {g.resource for g in intent.grants}
    named = target.target if target is not None else use.resource if use is not None else None
    if named is not None and named in asked:
        return f"Your PR asks for {describe(named, nodes)}. {OWNER}"
    if target is not None:
        return f"Your PR says: {_says(intent.purpose)}. Your change grants {describe(target.target, nodes)}."
    if use is not None:
        return f"Your PR says: {_says(intent.purpose)}. Your code now reads {describe(use.resource, nodes)}."
    return "This change matches its stated purpose."


def approved(
    requirements: list[Requirement], intent: Intent | None, nodes: dict[str, NodeRow]
) -> list[Requirement]:
    """The `theseus.yaml` requirements, plus the intent requirements that may count for capacities and
    verdicts: none from a suspicious PR, and none on sensitive data (04-engine.md section 10)."""
    out = []
    for r in requirements:
        if r.source == "config":
            out.append(r)
            continue
        target = nodes.get(r.resource)
        if intent is not None and intent.suspicious:
            continue
        if target is not None and target.sensitive:
            continue
        out.append(r)
    return out


def changes(base: World, head: World) -> list[ResourceChange]:
    """Every resource the change creates, deletes or updates, from the two worlds, by address."""
    b = {r.address: r for r in base.resources}
    h = {r.address: r for r in head.resources}
    out = [ResourceChange(address=a, type=h[a].type, action="create") for a in h.keys() - b.keys()]
    out += [ResourceChange(address=a, type=b[a].type, action="delete") for a in b.keys() - h.keys()]
    out += [
        ResourceChange(address=a, type=h[a].type, action="update")
        for a in b.keys() & h.keys()
        if b[a].values != h[a].values
    ]
    return sorted(out, key=lambda c: (c.address, c.action))


def change_line(found: list[ResourceChange], opened: list[PathRecord], closed: list[PathRecord]) -> str:
    """What the change does, from the plan and never from a model, such as `Adds
    aws_iam_user_group_membership.x. Opens 3 dangerous paths, closes 0.`"""
    parts = []
    for action in ("create", "update", "delete"):
        addresses = [c.address for c in found if c.action == action]
        if addresses:
            parts.append(f"{VERBS[action]} {', '.join(addresses)}")
    did = ", ".join(parts) if parts else "changes no resource"
    paths = "path" if len(opened) == 1 else "paths"
    return f"{did[0].upper()}{did[1:]}. Opens {len(opened)} dangerous {paths}, closes {len(closed)}."
