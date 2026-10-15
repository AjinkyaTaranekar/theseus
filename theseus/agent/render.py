"""The PR comment (05-contracts.md, "The PR comment"): an AnalysisResult as GitHub markdown.

The comment is written for someone with no context, at 3 a.m.: a card in plain words on top (the verdict, what
happened, what is at risk, what the PR said it needs, what to do), and everything technical folded below.
Every sentence comes from a template over facts in the result; no model writes prose here.

Every value in a result is text someone else wrote: a PR author, a model, an advisory, a Terraform file. So
the template escapes every value by default. Only fragments built here, marked `Md`, pass through as markdown.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from theseus.contracts.result import AnalysisResult, Candidate, Contract, PathRecord
from theseus.contracts.schema import INTERNET, parse_id
from theseus.engine import words

MARKER = "<!-- theseus:pr-comment -->"
MAX_CHARS = 65_536  # GitHub's limit on a comment body
DIAGRAMS = 3
NAMES_PER_ACTION = 3
RISKS = 5
CAPS = {"opened": 20, "unchanged": 30, "trace": 40, "unknowns": 20}
SENSITIVE_RANK = {"regulated": 0, "confidential": 1}
ACTIONS = (("create", "adds"), ("update", "updates"), ("delete", "deletes"))
MODEL_NAMES = {"llm": "LLM", "jev": "Jev"}
ASKED = {"read": "read", "write": "change", "assume": "switch into"}
DOES = {"read": "reads", "write": "changes", "assume": "switches into"}
TEMPLATES = Path(__file__).with_name("templates")

_PUNCTUATION = re.compile(r"([\\`*_{}\[\]()#+!|~])")
_URL_OR_MENTION = re.compile(r"(?:https?://|www\.)[^\s|<>]+|(?<![\w.])@[A-Za-z0-9][\w-]*")
_BACKTICKS = re.compile(r"`+")
_MERMAID = {'"': "#quot;", "`": "#96;", "<": "#lt;", ">": "#gt;"}
_BREAK = "<br>\n"


class Md(str):
    """Markdown built by this module: the template prints it as it is."""


class Verdict(Contract):
    """The comment's status, which is also the check run's: `level` for the comment, `conclusion` and `title`
    for the check (07-github-and-deploy.md, "Blocking a merge"). The merge box shows the title."""

    level: Literal["blocked", "look", "clear"]
    conclusion: Literal["failure", "neutral", "success"]
    heading: str
    title: str


# Escaping ---------------------------------------------------------------------------------------------------


def escape(text: str) -> str:
    """One line of plain text for markdown: HTML neutralized, markdown punctuation escaped, and links and
    @-mentions shown as code, so they neither link nor notify."""
    line = " ".join(str(text).split())
    out: list[str] = []
    last = 0
    for m in _URL_OR_MENTION.finditer(line):
        out.append(_plain(line[last : m.start()]))
        out.append(code(m.group(0)))
        last = m.end()
    out.append(_plain(line[last:]))
    return "".join(out)


def _plain(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _PUNCTUATION.sub(r"\\\1", text)


def code(text: str) -> Md:
    """`text` as a code span nothing inside can close. Pipes are escaped, so it is safe in a table."""
    text = " ".join(str(text).split()).replace("|", "\\|")
    fence = "`" * (max((len(run) for run in _BACKTICKS.findall(text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return Md(f"{fence}{pad}{text}{pad}{fence}")


def _names(items: list[str], more: int = 0) -> str:
    """`a`; `a` and `b`; `a`, `b` and `c`; or `a`, `b`, `c` and 2 more."""
    if more:
        return f"{', '.join(items)} and {more} more"
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# Plain words for nodes --------------------------------------------------------------------------------------


def _bold(node: str) -> str:
    return f"**{escape(words.name(node))}**"


def _the(node: str, result: AnalysisResult) -> str:
    """A node as it reads in a sentence: "**priya-intern** (a user)", "the **customer-db** database"."""
    if node == INTERNET:
        return _bold(node)
    k = words.kind(node, result.nodes.get(node))
    if parse_id(node)[0] == "user":
        return f"{_bold(node)} ({words.article(k)})"
    return f"the {_bold(node)} {k}"


def _sensitivity(node: str, result: AnalysisResult, path: PathRecord | None = None) -> str | None:
    if path is not None and path.target == node and path.sensitivity:
        return path.sensitivity
    info = result.nodes.get(node)
    return info.sensitivity if info else None


# The verdict ------------------------------------------------------------------------------------------------


def _rank(path: PathRecord) -> tuple[int, bool, int, str]:
    """Most sensitive first; then a target reached through what unlocks it, so a database comes before its
    secret (04-engine.md section 18); then the fewest hops, then the ID."""
    unlocked = bool(path.steps) and path.steps[-1].type == "UNLOCKS"
    return (SENSITIVE_RANK.get(path.sensitivity or "", 2), not unlocked, len(path.steps), path.id)


def verdict(result: AnalysisResult) -> Verdict:
    """Blocked when a dangerous path opened or code reads sensitive data beyond intent; a look when only
    something Theseus could not check remains; clear otherwise."""
    pr = result.mode == "pr"
    if result.opened or result.use_beyond_intent:
        if result.opened:
            top = sorted(result.opened, key=_rank)[0]
            why = f"{words.name(top.actor)} can reach {words.name(top.target)}"
        else:
            use = result.use_beyond_intent[0]
            why = f"{words.name(use.workload)}'s code now reads {words.name(use.resource)}"
        label = "Merge blocked" if pr else "Sensitive data at risk"
        return Verdict(level="blocked", conclusion="failure", heading=f"🔴 {label}", title=f"{label}: {why}")
    if result.unknowns:
        n = _plural(len(result.unknowns), "thing")
        return Verdict(
            level="look",
            conclusion="neutral",
            heading="🟡 Needs a look",
            title=f"Needs a look: Theseus could not check {n}",
        )
    clear = "No new access to sensitive data"
    return Verdict(level="clear", conclusion="success", heading=f"🟢 {clear}", title=clear)


# The card ---------------------------------------------------------------------------------------------------


def changes_words(result: AnalysisResult) -> str:
    """What the PR adds, updates and deletes, by Terraform address: "adds `a`; deletes `b`"."""
    parts: list[str] = []
    for action, verb in ACTIONS:
        addresses = sorted(c.address for c in result.changes if c.action == action)
        if addresses:
            shown = [code(a) for a in addresses[:NAMES_PER_ACTION]]
            parts.append(f"{verb} {_names(shown, len(addresses) - len(shown))}")
    return "; ".join(parts)


def change_line(result: AnalysisResult) -> Md:
    """What the change adds, updates and deletes, then how many dangerous paths it opens and closes."""
    did = changes_words(result)
    counts = f"Opens {_plural(len(result.opened), 'dangerous path')}, closes {len(result.closed)}."
    return Md(f"{did[0].upper()}{did[1:]}. {counts}" if did else counts)


def story(path: PathRecord, result: AnalysisResult) -> Md:
    """The path as one sentence a person can follow, one hop per line."""
    if not path.steps:
        return Md(f"{_the(path.actor, result)} can reach {_the(path.target, result)}.")
    first, *rest = path.steps
    lines = [f"{_the(first.src, result)} {words.verb(first.type, path.grants)} {_the(first.dst, result)}"]
    lines += [f"→ which {words.verb(s.type, path.grants)} {_the(s.dst, result)}" for s in rest]
    return Md(f",{_BREAK}".join(lines) + ".")


def what_happened(result: AnalysisResult, repo: str, head_sha: str, world_root: str) -> list[Md]:
    out: list[Md] = []
    did = changes_words(result)
    if did:
        out.append(Md(f"This PR {did}."))
    if result.opened:
        top = sorted(result.opened, key=_rank)[0]
        n = len(result.opened)
        if n == 1:
            out.append(Md("Because of that, a new way to reach sensitive data opens:"))
        else:
            out.append(Md(f"Because of that, {n} new ways to reach sensitive data open. The most serious:"))
        out.append(story(top, result))
        if n > 1:
            out.append(Md(f"Each of the {n} is under **The path, step by step** below."))
    for use in result.use_beyond_intent[: CAPS["opened"]]:
        link = (
            f"[{escape(f'{use.file}:{use.line}')}]({_blob(repo, head_sha, world_root, use.file, use.line)})"
            if use.file != "unknown"
            else "unknown file"
        )
        out.append(
            Md(
                f"The code of {_the(use.workload, result)} now {DOES[use.access]}"
                f" {_the(use.resource, result)} ({link}), and the PR does not mention it."
            )
        )
    if result.closed:
        out.append(Md(f"It also closes {_plural(len(result.closed), 'way')} in."))
    if not result.opened and not result.use_beyond_intent:
        out.append(Md("It opens no new way to reach sensitive data."))
    return out


def at_risk(result: AnalysisResult) -> tuple[list[Md], int]:
    """Each sensitive thing the change exposes, in plain words, most sensitive first; and how many more."""
    unlocks = {s.src: s.dst for p in result.opened for s in p.steps if s.type == "UNLOCKS"}
    targets: dict[str, str | None] = {}
    for p in sorted(result.opened, key=_rank):
        targets.setdefault(p.target, _sensitivity(p.target, result, p))
    for use in result.use_beyond_intent:
        targets.setdefault(use.resource, _sensitivity(use.resource, result))
    lines: list[Md] = []
    for node, sensitivity in list(targets.items())[:RISKS]:
        what = words.article(words.kind(node, result.nodes.get(node)))
        if node in unlocks and unlocks[node] in targets:
            lines.append(Md(f"{_bold(node)}, {what}: the key that opens {_bold(unlocks[node])}"))
        else:
            lines.append(Md(f"{_bold(node)}, {what}: {words.class_words(sensitivity)}"))
    return lines, max(0, len(targets) - RISKS)


def what_pr_says(result: AnalysisResult) -> list[Md] | None:
    """What the PR said it is for and the access it asked for; None outside PR mode or without intent."""
    intent = result.intent
    if result.mode != "pr" or intent is None:
        return None
    if not intent.stated:
        return [
            Md(
                "The PR doesn't say what it's for, so Theseus can't check the change against a purpose."
                " Ask the author to describe it."
            )
        ]
    out: list[Md] = []
    if intent.purpose:
        out.append(Md(f'"{escape(intent.purpose)}"'))
    if intent.grants:
        asked = [f"{_bold(g.principal)} to {ASKED[g.access]} {_bold(g.resource)}" for g in intent.grants]
        out.append(Md(f"It asks only for: {'; '.join(asked)}."))
    else:
        out.append(Md("It says it changes no access."))
    return out


def what_to_do(result: AnalysisResult, level: str) -> list[Md]:
    if level == "clear":
        return [Md("Nothing. Theseus found no new access to sensitive data.")]
    if level == "look":
        return [Md("Check the items under **What Theseus could not check** before you merge.")]
    passing = [c for c in result.candidates if c.verdict == "pass"]
    recommended = next((c for c in passing if c.recommended), None)
    ask = Md("Or ask the author to change the PR.")
    if recommended is not None:
        return [
            Md(
                f"✅ **Reply {code(f'/theseus apply {recommended.id}')}** to commit fix {recommended.id}:"
                f" {escape(recommended.title)}."
            ),
            Md(
                "Theseus tested it on a copy of the graph: it closes all "
                f"{_plural(len(result.opened), 'way')} in and breaks nothing."
                if result.opened
                else "Theseus tested it on a copy of the graph, and it breaks nothing."
            ),
            ask,
        ]
    if passing:
        ids = _names([code(c.id) for c in passing])
        return [
            Md(
                f"⚠️ {ids} {'passes' if len(passing) == 1 else 'pass'} Theseus's checks but needs a closer"
                f" look first. Then reply {code('/theseus apply <ID>')}."
            ),
            ask,
        ]
    if result.candidates:
        return [
            Md(
                "❗ No fix Theseus tested passes every check. Ask the author to change the PR, or compare the"
                " trade-offs under **All fixes Theseus tested**."
            )
        ]
    return [
        Md(
            "Ask the author why the change needs this access. If it should have it, an owner adds it to"
            f" {code('theseus.yaml')}."
        )
    ]


def checkov_line(checkov: dict[str, Any] | None, opened: bool = False) -> Md:
    """Checkov's JSON summary for the same commit, in a sentence that says why it can pass anyway."""
    if not checkov:
        return Md("Checkov did not run on this commit.")
    version = f" {escape(str(checkov['checkov_version']))}" if checkov.get("checkov_version") else ""
    passed, failed = int(checkov.get("passed", 0)), int(checkov.get("failed", 0))
    if failed:
        return Md(
            f"Checkov{version} found {_plural(failed, 'problem')} on this commit ({passed} checks passed);"
            " see its own report."
        )
    line = f"Checkov{version} passed this commit ({_plural(passed, 'check')})."
    if opened:
        line += " It checks one resource at a time, so it cannot see a path that crosses several."
    return Md(line)


# The folded sections ----------------------------------------------------------------------------------------


def pick_diagrams(paths: list[PathRecord]) -> list[PathRecord]:
    """The paths worth a diagram: at most three, in `_rank` order."""
    return sorted(paths, key=_rank)[:DIAGRAMS]


def _label(node: str) -> str:
    return "".join(_MERMAID.get(c, c) for c in " ".join(node.split()))


def mermaid(path: PathRecord) -> Md:
    """A `flowchart LR` of the path. Node IDs are n1, n2...: IDs with `:` or `/` break Mermaid."""
    ids: dict[str, str] = {}
    for node in path.route:
        ids.setdefault(node, f"n{len(ids) + 1}")
    lines = ["```mermaid", "flowchart LR"]
    lines += [f'  {nid}["{_label(node)}"]' for node, nid in ids.items()]
    lines += [f"  {ids[s.src]} -->|{s.type}| {ids[s.dst]}" for s in path.steps]
    if path.sensitivity in SENSITIVE_RANK:
        lines += [
            "  classDef sensitive fill:#fde2e1,stroke:#c0392b,color:#1f2328",
            f"  class {ids[path.target]} sensitive",
        ]
    lines.append("```")
    return Md("\n".join(lines))


def _blob(repo: str, head_sha: str, world_root: str, file: str, line: int | None) -> str:
    url = f"https://github.com/{quote(repo)}/blob/{quote(head_sha)}/{quote(world_root.strip('/'))}/{quote(file)}"
    return f"{url}#L{line}" if line else url


def evidence_link(result: AnalysisResult, evidence_id: str, repo: str, head_sha: str, world_root: str) -> Md:
    """A link to the file and line behind an edge at the head commit, or why there is none."""
    ev = result.evidence.get(evidence_id)
    if ev is None:
        return Md("unknown: no evidence recorded")
    if ev.file == "unknown":
        return Md(f"unknown: {escape(ev.note or ev.address)}")
    text = f"{ev.file}:{ev.line}" if ev.line else ev.file
    return Md(f"[{escape(text)}]({_blob(repo, head_sha, world_root, ev.file, ev.line)})")


def step_links(
    path: PathRecord, result: AnalysisResult, repo: str, head_sha: str, world_root: str
) -> list[Md]:
    """One numbered line per step, linked to its evidence: GitHub does not run links inside Mermaid."""
    return [
        Md(
            f"{n}. {code(s.src)} → {code(s.dst)} ({s.type}): "
            f"{evidence_link(result, s.evidence, repo, head_sha, world_root)}"
        )
        for n, s in enumerate(path.steps, start=1)
    ]


def cut_sentence(result: AnalysisResult, repo: str, head_sha: str, world_root: str) -> Md | None:
    """The minimum cut in one sentence, each cut edge linked to its evidence."""
    cut = result.min_cut
    if cut is None:
        return None
    if not cut.cuttable:
        return Md("No single permission can be removed without breaking required access.")
    if not cut.cut:
        return None
    where = (repo, head_sha, world_root)
    edges = [
        f"{code(f'{e.src} {e.type} {e.dst}')} ({evidence_link(result, e.evidence, *where)})" for e in cut.cut
    ]
    if len(edges) == 1:
        return Md(f"One change closes every path: {edges[0]}.")
    return Md(f"{len(edges)} changes close every path: {'; '.join(edges)}.")


def _fix_row(c: Candidate) -> list[Md]:
    who = "rule" if c.source == "rule" else escape(c.proposed_by)
    paths = []
    if c.paths_left:
        paths.append(f"{len(c.paths_left)} left")
    if c.new_paths:
        paths.append(f"{len(c.new_paths)} new")
    verdict_cell = f"{c.verdict}, needs a closer look" if c.needs_closer_look else c.verdict
    cells = [
        c.id,
        f"{escape(c.title)} ({who})",
        ", ".join(paths) or "all closed",
        f"breaks {escape(', '.join(c.requirements_broken))}" if c.requirements_broken else "kept",
        f"breaks {escape(', '.join(c.calls_broken))}" if c.calls_broken else "kept",
        verdict_cell,
    ]
    return [Md(f"**{cell}**" if c.recommended else cell) for cell in cells]


def apply_hint(candidates: list[Candidate]) -> Md | None:
    """How to commit a fix, naming only fixes that pass, the recommended one first."""
    passing = [c for c in candidates if c.verdict == "pass"]
    if not passing:
        return None
    recommended = next((c for c in passing if c.recommended), None)
    if recommended is None:
        ids = _names([code(c.id) for c in passing])
        return Md(f"Reply {code('/theseus apply <ID>')} with a fix that passes: {ids}.")
    others = [code(c.id) for c in passing if c is not recommended]
    also = f" {_names(others)} also {'passes' if len(others) == 1 else 'pass'}." if others else ""
    return Md(f"Reply {code(f'/theseus apply {recommended.id}')} to commit a fix.{also}")


def _path_row(p: PathRecord) -> dict[str, Md]:
    target = f"{code(p.target)} ({p.sensitivity})" if p.sensitivity else code(p.target)
    return {"actor": code(p.actor), "target": Md(target), "hops": Md(str(len(p.steps)))}


def coverage_line(result: AnalysisResult) -> Md:
    cov = result.coverage
    if cov.resources == 0:
        return Md("Coverage: not recorded.")
    skipped = sum(cov.skipped_types.values())
    if skipped:
        common = sorted(cov.skipped_types.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        such_as = _names([f"{code(t)} ({n})" for t, n in common])
        line = (
            f"Read {cov.resources} resources, modeled {cov.modeled}; skipped {skipped} of types Theseus"
            f" does not model, such as {such_as}."
        )
    else:
        line = f"Read {cov.resources} resources and modeled all of them."
    if cov.code_calls_skipped:
        line += f" Skipped {_plural(cov.code_calls_skipped, 'code call')} it could not resolve."
    return Md(line)


def timings_line(result: AnalysisResult) -> Md:
    t = result.timings
    if not t.total_ms:
        return Md("Timings: not recorded.")
    s = [f"{ms / 1000:.1f} s" for ms in (t.total_ms, t.engine_ms, t.llm_ms, t.jev_ms)]
    return Md(f"Took {s[0]}: engine {s[1]}, LLM {s[2]}, Jev {s[3]}.")


def versions_line(result: AnalysisResult) -> Md:
    if not result.models:
        return Md("Models: not recorded.")
    keys = [k for k in MODEL_NAMES if k in result.models] + sorted(set(result.models) - set(MODEL_NAMES))
    named = [f"{MODEL_NAMES.get(k, escape(k))} {code(result.models[k])}" for k in keys]
    return Md(f"Models: {', '.join(named)}.")


# Rendering --------------------------------------------------------------------------------------------------


def _finalize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Md):
        return value
    if isinstance(value, int | float):
        return str(value)
    return escape(str(value))


_ENV = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=False,
    finalize=_finalize,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def _context(
    result: AnalysisResult,
    repo: str,
    head_sha: str,
    checkov: dict[str, Any] | None,
    world_root: str,
    scale: int,
) -> dict[str, Any]:
    caps = {k: max(1, v // scale) for k, v in CAPS.items()}
    status = verdict(result)
    opened = sorted(result.opened, key=_rank)
    risks, risks_more = at_risk(result)
    pr = result.mode == "pr"
    passing = any(c.verdict == "pass" for c in result.candidates)
    return {
        "marker": Md(MARKER),
        "status": status,
        "headline": result.headline,
        "suspicious": bool(result.intent and result.intent.suspicious),
        "happened": Md(_BREAK.join(what_happened(result, repo, head_sha, world_root))),
        "risks": risks,
        "risks_more": risks_more,
        "asked": Md(_BREAK.join(lines)) if (lines := what_pr_says(result)) else None,
        "todo": Md(_BREAK.join(what_to_do(result, status.level))) if pr else None,
        "checkov": checkov_line(checkov, bool(result.opened)) if pr else None,
        "opened": [_path_row(p) for p in opened[: caps["opened"]]],
        "opened_more": max(0, len(opened) - caps["opened"]),
        "diagrams": [
            {
                "title": Md(f"How {_bold(p.actor)} reaches {_bold(p.target)}"),
                "mermaid": mermaid(p),
                "steps": step_links(p, result, repo, head_sha, world_root),
            }
            for p in pick_diagrams(result.opened)
        ],
        "cut": cut_sentence(result, repo, head_sha, world_root) if result.opened else None,
        "fixes": [_fix_row(c) for c in result.candidates],
        "nothing_passes": bool(result.candidates) and not passing,
        "apply_hint": apply_hint(result.candidates),
        "unknowns": result.unknowns[: caps["unknowns"]],
        "unknowns_count": len(result.unknowns),
        "unknowns_more": max(0, len(result.unknowns) - caps["unknowns"]),
        "change_line": change_line(result) if pr else None,
        "trace": [
            {"n": Md(str(n)), "tool": code(t.tool), "summary": t.summary, "ms": Md(str(t.ms))}
            for n, t in enumerate(result.tool_trace[: caps["trace"]], start=1)
        ],
        "trace_more": max(0, len(result.tool_trace) - caps["trace"]),
        "unchanged": [_path_row(p) for p in result.unchanged[: caps["unchanged"]]],
        "unchanged_more": max(0, len(result.unchanged) - caps["unchanged"]),
        "coverage": coverage_line(result),
        "timings": timings_line(result),
        "versions": versions_line(result),
    }


def render_comment(
    result: AnalysisResult,
    repo: str,
    head_sha: str,
    checkov: dict[str, Any] | None = None,
    world_root: str = "demo-infra",
) -> str:
    """The whole PR comment, marker first. Long lists are cut short, so the comment fits GitHub's limit."""
    template = _ENV.get_template("comment.md")
    scale = 1
    while True:
        comment = template.render(**_context(result, repo, head_sha, checkov, world_root, scale))
        if len(comment) < MAX_CHARS or scale >= 64:
            return comment
        scale *= 2
