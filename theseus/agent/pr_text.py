"""PR text as intent extraction sees it (06-agent.md, "Intent extraction"): what reviewers see, what is
hidden, what the screen flags, and nothing that is only template boilerplate or a secret."""

from __future__ import annotations

import re

from pydantic import Field

from theseus.agent.screen import injection_flags, mask_secrets, normalize
from theseus.contracts.result import Contract

_COMMENT = re.compile(r"<!--(.*?)(?:-->|\Z)", re.S)
_HEADING = re.compile(r"^#{1,6}\s+\S")
_UNTICKED = re.compile(r"^\s*[-*]\s+\[ \]\s")


class PrText(Contract):
    """A PR's title, the body as reviewers see it, and the hidden text its author added: HTML comments and
    text in invisible characters. `flags` say why the screen finds it suspicious; `masked` names each secret
    masked.

    Nothing is ever cut: GitHub caps a body at 65,536 characters, far inside the model's context, and a cut
    would let padding push a request or an injection out of sight.
    """

    title: str
    visible: str = ""
    hidden: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    masked: list[str] = Field(default_factory=list)

    @property
    def empty(self) -> bool:
        """True when there is nothing at all to read: no title, no visible body, no hidden text."""
        return not (self.title or self.visible or self.hidden)


def _norm(text: str) -> str:
    return " ".join(text.split())


def html_comments(text: str) -> frozenset[str]:
    """The HTML comments in a text, whitespace-normalized; for a PR template, the comments to ignore."""
    return frozenset(c for m in _COMMENT.finditer(text) if (c := _norm(m.group(1))))


def template_lines(template: str) -> frozenset[str]:
    """The non-blank lines of a PR template outside its comments, whitespace-normalized."""
    return frozenset(n for line in _COMMENT.sub("", template).split("\n") if (n := _norm(line)))


def _drop_empty_sections(lines: list[str]) -> list[str]:
    """Headings with nothing under them before the next heading or the end."""
    out: list[str] = []
    for i, line in enumerate(lines):
        if _HEADING.match(line):
            rest = lines[i + 1 :]
            nxt = next((j for j, r in enumerate(rest) if _HEADING.match(r)), len(rest))
            if not any(r.strip() for r in rest[:nxt]):
                continue
        out.append(line)
    return out


def prepare(title: str, body: str | None, template: str = "") -> PrText:
    """The PR text to send, normalized and with secrets masked. Comments and text in invisible characters
    are set apart as hidden, except the repo template's own comments; lines copied verbatim from the
    template, empty sections and unticked checklist lines are dropped; blank runs are collapsed. The screen
    reads all of it."""
    template = normalize(template)[0]
    own_comments, own_lines = html_comments(template), template_lines(template)
    title, title_revealed, title_flags = normalize(title)
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    text, revealed, flags = normalize(text)
    title, masked = mask_secrets(title)
    text, body_masked = mask_secrets(text)
    smuggled = [mask_secrets(r) for r in title_revealed + revealed]
    masked += body_masked + [k for _, kinds in smuggled for k in kinds]
    flags += title_flags + injection_flags(title) + injection_flags(text)
    hidden = [c for m in _COMMENT.finditer(text) if (c := _norm(m.group(1))) and c not in own_comments]
    hidden += [r for r, _ in smuggled]
    flags += [f for h in hidden for f in injection_flags(h)]
    text = _COMMENT.sub("", text)
    lines = [
        line.rstrip()
        for line in text.split("\n")
        if not _UNTICKED.match(line) and not (_norm(line) and _norm(line) in own_lines)
    ]
    visible = re.sub(r"\n{3,}", "\n\n", "\n".join(_drop_empty_sections(lines))).strip()
    return PrText(
        title=title.strip(), visible=visible, hidden=hidden, flags=sorted(set(flags)), masked=masked
    )
