"""The labels a reviewed PR carries (07-github-and-deploy.md, "Labels"): what the review found, readable at a
glance in the PR list and countable later, decided from the result like the comment. Every label here starts
with `theseus: `; the App adds and removes only these, never `demo` or a person's labels.
"""

from __future__ import annotations

from theseus.agent.render import verdict
from theseus.contracts.result import AnalysisResult, Contract
from theseus.contracts.schema import INTERNET

PREFIX = "theseus: "


class Label(Contract):
    name: str
    color: str  # six hex digits, no #
    description: str  # GitHub allows 100 characters


def _label(name: str, color: str, description: str) -> Label:
    return Label(name=PREFIX + name, color=color, description=description)


# Severity: S0 is the most severe, S6 the least. The first rule that holds decides it. Code that reads data
# beyond intent counts like a path to that data: it is use, not only the chance of it.
SEVERITY = (
    _label("S0 critical", "b60205", "Severity S0: anyone on the internet can reach regulated data"),
    _label(
        "S1 high",
        "d93f0b",
        "Severity S1: an insider reaches regulated data, or the internet confidential data",
    ),
    _label("S2 medium", "e99695", "Severity S2: a new path or code read reaches confidential data"),
    _label("S3 low", "fbca04", "Severity S3: a new path or code read reaches data of unknown sensitivity"),
    _label("S4 unchecked", "fef2c0", "Severity S4: Theseus could not check part of the change"),
    _label(
        "S5 unclear text",
        "c5def5",
        "Severity S5: no new access, but the PR's text is unclear or steers the review",
    ),
    _label("S6 none", "0e8a16", "Severity S6: no new access to sensitive data"),
)
VERDICT = {
    "blocked": _label("blocked", "b60205", "Theseus blocked the merge: a new way to sensitive data"),
    "look": _label("needs a look", "fbca04", "Theseus could not check part of this change"),
    "clear": _label("clear", "0e8a16", "Theseus found no new access to sensitive data"),
}
CLASS = {
    "regulated": _label("regulated data", "d93f0b", "Reaches personal, payment or health data"),
    "confidential": _label("confidential data", "e99695", "Reaches business-sensitive data"),
}
BEYOND = _label(
    "grants more than it says", "5319e7", "The change grants access its description never asks for"
)
STEERING = _label("steering text", "5319e7", "Text in the PR tries to steer the review")

LABELS: tuple[Label, ...] = (*SEVERITY, *VERDICT.values(), *CLASS.values(), BEYOND, STEERING)
# The severity labels' names before they said their level in words: removed from a PR on its next review.
RETIRED: tuple[Label, ...] = tuple(_label(f"S{i}", s.color, s.description) for i, s in enumerate(SEVERITY))
# Every label the App may remove from a PR: the ones it sets, and the ones it used to.
MANAGED: tuple[Label, ...] = (*LABELS, *RETIRED)


def _reached(result: AnalysisResult) -> set[tuple[bool, str | None]]:
    """(from the internet, data class) for every opened path and every code read beyond intent."""
    reached = {(p.actor == INTERNET, p.sensitivity) for p in result.opened}
    for use in result.use_beyond_intent:
        info = result.nodes.get(use.resource)
        reached.add((False, info.sensitivity if info else None))
    return reached


def severity(result: AnalysisResult) -> int:
    """0 (most severe) to 6, from what the review found."""
    reached = _reached(result)
    classes = {c for _, c in reached}
    if (True, "regulated") in reached:
        return 0
    if "regulated" in classes or (True, "confidential") in reached:
        return 1
    if "confidential" in classes:
        return 2
    if reached:
        return 3
    if result.unknowns:
        return 4
    intent = result.intent
    if intent is not None and (not intent.stated or intent.suspicious):
        return 5
    return 6


def labels_for(result: AnalysisResult) -> list[Label]:
    """The labels for this result: one severity, one verdict, the most sensitive class reached, and whether
    the change grants more than the PR says or its text steers the review. Sorted by name."""
    out = [SEVERITY[severity(result)], VERDICT[verdict(result).level]]
    classes = {c for _, c in _reached(result)}
    top = next((c for c in ("regulated", "confidential") if c in classes), None)
    if top is not None:
        out.append(CLASS[top])
    intent = result.intent
    if intent is not None and intent.stated:
        asked = {g.resource for g in intent.grants}
        granted = {p.target for p in result.opened} | {u.resource for u in result.use_beyond_intent}
        if granted - asked:
            out.append(BEYOND)
    if intent is not None and intent.suspicious:
        out.append(STEERING)
    return sorted(out, key=lambda label: label.name)
