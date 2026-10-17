"""A verified fix as GitHub suggestions on the PR's own lines (docs/spec/07-github-and-deploy.md, "Suggested
fixes").

The engine checked the fix on a copy of the graph; the IaC adapter rendered it as text edits. This module
places those edits as ```suggestion blocks on lines inside the PR's diff, where GitHub lets a reviewer commit
them with one click, or edit them first. A new file the fix adds has no line in the diff, so its content goes
into the suggestion that replaces the PR's own lines in the same folder. An edit that falls outside the diff
is left for `/theseus apply <ID>`. Whatever the author commits, Theseus reviews the new head again.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

log = logging.getLogger(__name__)

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
MARKER = "<!-- theseus:suggestion -->"


@dataclass
class Suggestion:
    """One suggestion: replace lines `start`..`end` (1-based, the PR's side) of `path` with `lines`."""

    path: str
    start: int
    end: int
    lines: list[str] = field(default_factory=list)


@dataclass
class Plan:
    """Where a fix's edits go: suggestions on the diff, and edits that have no line there."""

    suggestions: list[Suggestion] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)


def diff_lines(patch: str | None) -> set[int]:
    """The line numbers on the PR's side of a file's patch that a review comment can sit on: every added or
    context line of every hunk."""
    found: set[int] = set()
    line = 0
    for text in (patch or "").splitlines():
        m = HUNK.match(text)
        if m:
            line = int(m[1])
            continue
        if not line or text.startswith("-") or text.startswith("\\"):
            continue
        found.add(line)
        line += 1
    return found


def plan(before: dict[str, str], after: dict[str, str], in_diff: dict[str, set[int]], root: str) -> Plan:
    """The fix's edits (`before` to `after`, paths under the world root) placed on lines in the diff
    (`in_diff`, by repo path). Sorted by path and line."""
    out = Plan()
    for path in sorted(after):
        if path not in before or before[path] == after[path]:
            continue
        repo_path = f"{root}/{path}"
        old, new = before[path].splitlines(), after[path].splitlines()
        lines = in_diff.get(repo_path, set())
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            if i1 == i2:  # an insertion: suggest the line before it, followed by the new lines
                start = end = i1
                replacement = [old[i1 - 1], *new[j1:j2]] if i1 else new[j1:j2]
            else:
                start, end, replacement = i1 + 1, i2, new[j1:j2]
            if start and all(n in lines for n in range(start, end + 1)):
                out.suggestions.append(Suggestion(repo_path, start, end, replacement))
            else:
                out.unplaced.append(f"{repo_path}:{start or 1}")
    for path in sorted(p for p in after if p not in before):
        folder = str(PurePosixPath(f"{root}/{path}").parent)
        host = next((s for s in out.suggestions if str(PurePosixPath(s.path).parent) == folder), None)
        if host is None:
            out.unplaced.append(f"{root}/{path}")
            continue
        body = after[path].rstrip("\n").splitlines()
        host.lines = [*host.lines, *([""] if host.lines and host.lines[-1].strip() else []), *body]
    out.suggestions.sort(key=lambda s: (s.path, s.start))
    return out


def comment_body(title: str, tested: str, suggestion: Suggestion) -> str:
    """One review comment: what the fix is, how it was checked, and the suggestion block."""
    fence = "````" if any(line.startswith("```") for line in suggestion.lines) else "```"
    block = "\n".join(suggestion.lines)
    return (
        f"**Theseus's fix:** {title}. Tested on a copy of the graph: {tested}.\n\n"
        "Commit the suggestion as it is, or edit it first: Theseus reviews whatever you push.\n\n"
        f"{fence}suggestion\n{block}\n{fence}"
    )


def review_body(head_sha: str) -> str:
    """The review's own text, with the marker that says which head it was for."""
    return (
        f"{MARKER}\n<!-- theseus:head:{head_sha} -->\n"
        "Theseus suggests a fix on the lines below. Commit it from there, or reply `/theseus apply` to commit"
        " all of it at once."
    )
