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

from theseus.contracts.result import AnalysisResult, Candidate, Contract, PathRecord, PathStep
from theseus.contracts.schema import INTERNET, parse_id
from theseus.engine import words
from theseus.engine.intent_effect import says

MARKER = "<!-- theseus:pr-comment -->"
MAX_CHARS = 65_536  # GitHub's limit on a comment body
DIAGRAMS = 3
NAMES_PER_ACTION = 3
RISKS = 5
ANNOTATIONS = 50  # GitHub takes at most 50 per request
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
# A line break in both GitHub comments and plain markdown; a newline alone doubles in comments.
_BREAK = "\\\n"


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


def _step_verb(step: PathStep, path: PathRecord) -> str:
    """What the hop lets its source do: its own edge's grants, or the path's when the step has none."""
    return words.verb(step.type, step.grants or path.grants)


def _who(node: str, result: AnalysisResult) -> str:
    """An actor as a sentence's subject: "**priya-intern**, a user,", "**Anyone on the internet**"."""
    if node == INTERNET:
        return "**Anyone on the internet**"
    return f"{_bold(node)}, {words.article(words.kind(node, result.nodes.get(node)))},"


def _what(node: str, result: AnalysisResult, path: PathRecord | None = None) -> str:
    """A target and what it holds: "**customer-db**, a database with personal, payment or health data"."""
    k = words.article(words.kind(node, result.nodes.get(node)))
    return f"{_bold(node)}, {k} with {words.holds(_sensitivity(node, result, path))}"


def consequence(result: AnalysisResult) -> Md:
    """The card's first line: who could now do what to which data, in plain words."""
    if result.opened:
        top = sorted(result.opened, key=_rank)[0]
        could = words.access_words(top.grants).replace("can ", "could ", 1)
        n = len(result.opened)
        more = f" (1 of {n} new ways in)" if n > 1 else ""
        return Md(f"{_who(top.actor, result)} {could} {_what(top.target, result, top)}{more}.")
    if result.use_beyond_intent:
        use = result.use_beyond_intent[0]
        return Md(
            f"The code of {_who(use.workload, result)} now {DOES[use.access]} {_what(use.resource, result)},"
            " and the PR does not mention it."
        )
    if result.unknowns:
        n = _plural(len(result.unknowns), "thing")
        return Md(f"Theseus could not check {n} in this change; see **What Theseus could not check** below.")
    return Md("This change opens no new way to reach sensitive data.")


def says_line(result: AnalysisResult) -> Md | None:
    """What the PR says it is for, in the model's plain words; None without intent."""
    intent = result.intent
    if intent is None:
        return None
    if not intent.stated or not intent.purpose.strip():
        return Md("**Says:** nothing about what it's for. Ask the author to describe it.")
    return Md(f"**Says:** {escape(says(intent.purpose))}.")


def _asked_targets(result: AnalysisResult) -> set[str]:
    return {g.resource for g in result.intent.grants} if result.intent else set()


def needs_and_grants(result: AnalysisResult) -> Md | None:
    """What the PR says it needs, then what the change grants: the gap is the finding."""
    parts: list[str] = []
    intent = result.intent
    if intent is not None and intent.stated:
        actors = {p.actor for p in result.opened}
        asked = [
            (f"{_bold(g.principal)} to " if g.principal not in actors else "")
            + f"{ASKED[g.access]} {_bold(g.resource)}"
            for g in intent.grants
        ]
        parts.append(f"**Needs:** {_names(asked)}" if asked else "**Needs:** no new access, it says")
    targets = list(dict.fromkeys(p.target for p in sorted(result.opened, key=_rank)))
    if targets:
        shown = [_bold(t) for t in targets[:NAMES_PER_ACTION]]
        asked_ids = _asked_targets(result)
        beyond = intent is not None and intent.stated and bool(asked_ids) and not set(targets) & asked_ids
        label = "Grants too" if beyond else "Grants"
        parts.append(f"**{label}:** {_names(shown, len(targets) - len(shown))}")
    reads = list(dict.fromkeys(u.resource for u in result.use_beyond_intent))
    if reads:
        parts.append(f"**Code now reads:** {_names([_bold(r) for r in reads[:NAMES_PER_ACTION]])}")
    return Md(" · ".join(parts)) if parts else None


def chain(path: PathRecord, result: AnalysisResult, repo: str, head_sha: str, world_root: str) -> Md:
    """The path in one line, each hop in plain words, the hop this change adds or edits linked to its line."""
    if not path.steps:
        return Md(f"{_bold(path.actor)} can reach {_bold(path.target)}.")
    changed = {c.address for c in result.changes}
    parts: list[str] = []
    for n, s in enumerate(path.steps):
        ev = result.evidence.get(s.evidence)
        mark = ""
        if ev is not None and ev.address in changed and ev.file != "unknown":
            mark = f" ({evidence_link(result, s.evidence, repo, head_sha, world_root)}, changed here)"
        head = f"{_bold(s.src)} " if n == 0 else ""
        parts.append(f"{head}{_step_verb(s, path)} {_bold(s.dst)}{mark}")
    return Md(" → ".join(parts) + ".")


def why_line(result: AnalysisResult, repo: str, head_sha: str, world_root: str) -> Md | None:
    """How the most serious path runs, or where the code reads beyond intent; None when nothing opened."""
    if result.opened:
        top = sorted(result.opened, key=_rank)[0]
        return Md(f"**Why:** {chain(top, result, repo, head_sha, world_root)}")
    if result.use_beyond_intent:
        use = result.use_beyond_intent[0]
        where = (
            f"[{escape(f'{use.file}:{use.line}')}]({_blob(repo, head_sha, world_root, use.file, use.line)})"
            if use.file != "unknown"
            else "an unknown line"
        )
        reads = f"{DOES[use.access]} {_bold(use.resource)}"
        return Md(f"**Why:** {_bold(use.workload)}'s code {reads} at {where}.")
    return None


def do_line(result: AnalysisResult, level: str) -> Md:
    """The one thing to do next."""
    if level == "clear":
        return Md("**Do:** nothing. Theseus found no new access to sensitive data.")
    if level == "look":
        return Md("**Do:** read **What Theseus could not check** below before you merge.")
    passing = [c for c in result.candidates if c.verdict == "pass"]
    recommended = next((c for c in passing if c.recommended), None)
    if recommended is not None:
        tested = (
            f"it closes all {_plural(len(result.opened), 'way')} in and breaks nothing"
            if result.opened
            else "it breaks nothing"
        )
        return Md(
            f"**Do:** reply {code(f'/theseus apply {recommended.id}')} to commit fix {recommended.id}"
            f" ({escape(recommended.title)}). Theseus tested it on a copy of the graph: {tested}."
        )
    if passing:
        ids = _names([code(c.id) for c in passing])
        return Md(
            f"**Do:** {ids} {'passes' if len(passing) == 1 else 'pass'} Theseus's checks but needs a closer"
            f" look first; then reply {code('/theseus apply <ID>')}."
        )
    if result.candidates:
        return Md(
            "**Do:** ask the author to change the PR. No fix Theseus tested passes every check; see **All"
            " fixes Theseus tested**."
        )
    targets = {p.target for p in result.opened} | {u.resource for u in result.use_beyond_intent}
    intent = result.intent
    if intent is not None and intent.stated and targets and targets <= _asked_targets(result):
        return Md(
            "**Do:** the PR asks for this access on purpose. If it is meant, an owner of the data approves"
            f" it in {code('theseus.yaml')}."
        )
    if intent is not None and intent.stated and intent.grants:
        return Md("**Do:** ask the author to grant only what the PR says it needs.")
    return Md("**Do:** ask the author why the change needs this access.")


def card_lines(result: AnalysisResult, repo: str, head_sha: str, world_root: str, level: str) -> list[Md]:
    """The lines under the consequence: says, needs and grants, why, do. Outside PR mode, only why."""
    if result.mode != "pr":
        return [line for line in (why_line(result, repo, head_sha, world_root),) if line]
    lines = [
        says_line(result),
        needs_and_grants(result),
        why_line(result, repo, head_sha, world_root),
        do_line(result, level),
    ]
    return [line for line in lines if line]


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


def annotations(result: AnalysisResult, world_root: str) -> list[dict[str, Any]]:
    """Notes for the check run on the lines that cause a finding, shown beside them in Files changed: each
    line this change adds or edits on a dangerous path, with what it opens, and each code line that reads
    beyond intent. Plain text, sorted by file and line, at most ANNOTATIONS."""
    changed = {c.address for c in result.changes}
    by_line: dict[tuple[str, int], list[str]] = {}
    for p in sorted(result.opened, key=_rank):
        for s in p.steps:
            ev = result.evidence.get(s.evidence)
            if ev is None or ev.address not in changed or ev.file == "unknown" or not ev.line:
                continue
            targets = by_line.setdefault((ev.file, ev.line), [])
            if p.target not in targets:
                targets.append(p.target)
    root = world_root.strip("/")
    out: list[dict[str, Any]] = []
    for (file, line), targets in sorted(by_line.items()):
        named = [f"{words.name(t)} ({words.kind(t, result.nodes.get(t))})" for t in targets[:3]]
        ways = _plural(len(targets), "new way")
        out.append(
            {
                "path": f"{root}/{file}",
                "start_line": line,
                "end_line": line,
                "annotation_level": "failure",
                "title": f"Opens {ways} to sensitive data",
                "message": f"This line opens {ways} to reach sensitive data:"
                f" {_names(named, len(targets) - len(named))}. The Theseus comment shows each step.",
            }
        )
    for use in result.use_beyond_intent:
        if use.file == "unknown" or not use.line:
            continue
        out.append(
            {
                "path": f"{root}/{use.file}",
                "start_line": use.line,
                "end_line": use.line,
                "annotation_level": "failure",
                "title": "Reads sensitive data the PR does not mention",
                "message": f"This code {DOES[use.access]} {words.name(use.resource)}"
                f" ({words.kind(use.resource, result.nodes.get(use.resource))}), and the PR does not"
                " mention it.",
            }
        )
    return sorted(out, key=lambda a: (a["path"], a["start_line"]))[:ANNOTATIONS]


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


def falkordb_line(result: AnalysisResult, version: str | None) -> Md | None:
    """Where the graph lives and how big it is: "Built in FalkorDB 4.22.0: 70 nodes and 146 edges ..."."""
    cov = result.coverage
    if not cov.nodes:
        return None
    where = f"FalkorDB {escape(version)}" if version else "FalkorDB"
    took = f"; the engine took {result.timings.engine_ms / 1000:.1f} s" if result.timings.engine_ms else ""
    size = f"{_plural(cov.nodes, 'node')} and {_plural(cov.edges, 'edge')}"
    return Md(f"Built in {where}: {size} for the head commit{took}.")


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
    falkordb: str | None,
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
        # PR mode says the headline as its Says and Grants lines; the other modes print it as it is.
        "headline": None if pr else result.headline,
        "consequence": consequence(result) if pr or result.opened or result.use_beyond_intent else None,
        "suspicious": bool(result.intent and result.intent.suspicious),
        "lines": Md(_BREAK.join(card_lines(result, repo, head_sha, world_root, status.level))),
        "risks": risks,
        "risks_more": risks_more,
        "checkov": checkov_line(checkov, bool(result.opened)) if pr else None,
        "falkordb": falkordb_line(result, falkordb),
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
    falkordb: str | None = None,
) -> str:
    """The whole PR comment, marker first. `falkordb` is the version the graphs were built in. Long lists are
    cut short, so the comment fits GitHub's limit."""
    template = _ENV.get_template("comment.md")
    scale = 1
    while True:
        comment = template.render(**_context(result, repo, head_sha, checkov, world_root, scale, falkordb))
        if len(comment) < MAX_CHARS or scale >= 64:
            return comment
        scale *= 2
