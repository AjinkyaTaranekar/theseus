"""The PR comment (05-contracts.md, "The PR comment"): an AnalysisResult as GitHub markdown.

Every value in a result is text someone else wrote: a PR author, a model, an advisory, a Terraform file. So
the template escapes every value by default. Only fragments built here, marked `Md`, pass through as markdown.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from theseus.contracts.result import AnalysisResult, Candidate, PathRecord

MARKER = "<!-- theseus:pr-comment -->"
MAX_CHARS = 65_536  # GitHub's limit on a comment body
DIAGRAMS = 3
NAMES_PER_ACTION = 3
CAPS = {"opened": 20, "unchanged": 30, "trace": 40, "unknowns": 20}
SENSITIVE_RANK = {"regulated": 0, "confidential": 1}
ACTIONS = (("create", "adds"), ("update", "updates"), ("delete", "deletes"))
MODEL_NAMES = {"llm": "LLM", "jev": "Jev"}
TEMPLATES = Path(__file__).with_name("templates")

_PUNCTUATION = re.compile(r"([\\`*_{}\[\]()#+!|~])")
_URL_OR_MENTION = re.compile(r"(?:https?://|www\.)[^\s|<>]+|(?<![\w.])@[A-Za-z0-9][\w-]*")
_BACKTICKS = re.compile(r"`+")
_MERMAID = {'"': "#quot;", "`": "#96;", "<": "#lt;", ">": "#gt;"}


class Md(str):
    """Markdown built by this module: the template prints it as it is."""


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


def _names(items: list[Md], more: int = 0) -> str:
    """`a`; `a` and `b`; `a`, `b` and `c`; or `a`, `b`, `c` and 2 more."""
    if more:
        return f"{', '.join(items)} and {more} more"
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def change_line(result: AnalysisResult) -> Md:
    """What the change adds, updates and deletes, then how many dangerous paths it opens and closes."""
    parts: list[str] = []
    for action, verb in ACTIONS:
        addresses = sorted(c.address for c in result.changes if c.action == action)
        if addresses:
            shown = [code(a) for a in addresses[:NAMES_PER_ACTION]]
            parts.append(f"{verb} {_names(shown, len(addresses) - len(shown))}")
    counts = f"{_plural(len(result.opened), 'dangerous path')}, closes {len(result.closed)}."
    if not parts:
        return Md(f"Opens {counts}")
    did = "; ".join(parts)
    return Md(f"{did[0].upper()}{did[1:]}. Opens {counts}")


def _rank(path: PathRecord) -> tuple[int, bool, int, str]:
    """Most sensitive first; then a target reached through what unlocks it, so a database comes before its
    secret (04-engine.md section 18); then the fewest hops, then the ID."""
    unlocked = bool(path.steps) and path.steps[-1].type == "UNLOCKS"
    return (SENSITIVE_RANK.get(path.sensitivity or "", 2), not unlocked, len(path.steps), path.id)


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
        lines += ["  classDef sensitive fill:#fde2e1,stroke:#c0392b", f"  class {ids[path.target]} sensitive"]
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


def checkov_line(checkov: dict[str, Any] | None) -> Md:
    """Checkov's JSON summary for the same commit, in one sentence."""
    if not checkov:
        return Md("Checkov did not run on this commit.")
    version = f" {escape(str(checkov['checkov_version']))}" if checkov.get("checkov_version") else ""
    parts = [f"{int(checkov.get('passed', 0))} passed", f"{int(checkov.get('failed', 0))} failed"]
    if skipped := int(checkov.get("skipped", 0)):
        parts.append(f"{skipped} skipped")
    return Md(f"Checkov{version} on this commit: {', '.join(parts)}.")


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
    verdict = f"{c.verdict}, needs a closer look" if c.needs_closer_look else c.verdict
    cells = [
        c.id,
        f"{escape(c.title)} ({who})",
        ", ".join(paths) or "all closed",
        f"breaks {escape(', '.join(c.requirements_broken))}" if c.requirements_broken else "kept",
        f"breaks {escape(', '.join(c.calls_broken))}" if c.calls_broken else "kept",
        verdict,
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
        such_as = _names([Md(f"{code(t)} ({n})") for t, n in common])
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
    opened = sorted(result.opened, key=_rank)
    unknowns = result.unknowns
    pr = result.mode == "pr"
    passing = any(c.verdict == "pass" for c in result.candidates)
    return {
        "marker": Md(MARKER),
        "change_line": change_line(result) if pr else None,
        "headline": result.headline,
        "suspicious": bool(result.intent and result.intent.suspicious),
        "opened": [_path_row(p) for p in opened[: caps["opened"]]],
        "opened_more": max(0, len(opened) - caps["opened"]),
        "diagrams": [
            {"mermaid": mermaid(p), "steps": step_links(p, result, repo, head_sha, world_root)}
            for p in pick_diagrams(result.opened)
        ],
        "checkov": checkov_line(checkov) if pr else None,
        "cut": cut_sentence(result, repo, head_sha, world_root) if result.opened else None,
        "fixes": [_fix_row(c) for c in result.candidates],
        "nothing_passes": bool(result.candidates) and not passing,
        "apply_hint": apply_hint(result.candidates),
        "unknowns": unknowns[: caps["unknowns"]],
        "unknowns_more": max(0, len(unknowns) - caps["unknowns"]),
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
