"""The containment PR and the rotate issue for a finding (task FM6; 07-github-and-deploy.md, "Finding and
scan outputs").

When an advisory affects a workflow on `main`, finding mode proposes candidate K and verifies it on a graph
copy. A posture run then opens one PR, `fix: Contain <id>`, from `theseus/contain-<id>`, with K's verified
Terraform edits and nothing else, and one issue listing exactly the secrets to rotate. Both carry the `demo`
label. A person still decides: the PR merges only after its own review and an approval. Running again finds
the open PR and the open issue instead of opening new ones.
"""

from __future__ import annotations

import logging
import re
import textwrap
from dataclasses import dataclass

from theseus.api.github import GitHub
from theseus.api.webhooks import Render
from theseus.contracts.result import AnalysisResult, Candidate
from theseus.engine.words import name
from theseus.errors import PatchError

log = logging.getLogger(__name__)

LABEL = "demo"
FIX = "K"
WRAP = 72  # commit body width (AGENTS.md, "Commits")
# Theseus's own notes in a PR body: what it checked and what to do outside the PR. A review reads the PR's
# purpose without them, since a PR that says it is safe is steering its review, whoever wrote it.
NOTES_OPEN = "<!-- theseus:notes -->"
NOTES_CLOSE = "<!-- /theseus:notes -->"
_NOTES = re.compile(re.escape(NOTES_OPEN) + r".*?" + re.escape(NOTES_CLOSE), re.S)


@dataclass(frozen=True)
class Contained:
    """Where a finding's containment lives: the PR and the rotate issue, and whether this run opened them."""

    finding: str
    pr: str
    pr_number: int
    issue: str | None
    opened: bool


def branch_for(finding_id: str) -> str:
    return f"theseus/contain-{finding_id}"


def _passing(result: AnalysisResult) -> Candidate | None:
    return next((c for c in result.candidates if c.id == FIX and c.verdict == "pass"), None)


def commit_message(finding_id: str, result: AnalysisResult) -> str:
    """`fix: Contain <id>`, a body naming the trust it removes, and the Proposed-by trailer, wrapped at 72."""
    finding = result.finding or {}
    cut = result.min_cut.cut if result.min_cut is not None else []
    action = name(str(finding.get("action") or "An Action"))
    body = textwrap.fill(
        f"{finding_id} affects {action}. Theseus checked this fix on a copy of main's graph: the affected "
        "workflows reach no sensitive data, and every requirement in theseus.yaml still holds.",
        WRAP,
        break_long_words=False,
        break_on_hyphens=False,
    )
    lines = [f"fix: Contain {finding_id}", "", body]
    if cut:
        lines += ["", "It removes:"]
        lines += [f"- {name(c.src)} -> {name(c.dst)}" for c in cut]
    lines += ["", "Proposed-by: theseus"]
    return "\n".join(lines) + "\n"


def pr_body(finding_id: str, result: AnalysisResult, k: Candidate, page: str | None) -> str:
    """The PR description: what is exposed, the cut, how it was checked, and what to rotate."""
    finding = result.finding or {}
    workflows = ", ".join(f"`{name(w)}`" for w in finding.get("workflows") or []) or "no workflow"
    reach = sorted({p.target for p in result.opened})
    cut = result.min_cut.cut if result.min_cut is not None else []
    parts = [
        f"**{finding_id}** affects `{finding.get('action', '')}`, which {workflows} use at an affected "
        "version. If it runs malicious code, those workflows could reach:",
        "",
        *[f"- `{name(t)}`" for t in reach],
        "",
        "**The fix.** "
        + (
            "Stop trusting " + ", ".join(f"`{name(c.src)}` as `{name(c.dst)}`" for c in cut) + ". "
            if cut
            else ""
        )
        + "The role now trusts only the workflows a requirement needs, as `terraform-apply` already does.",
        "",
        NOTES_OPEN,
        f"**Verification:** fix {k.id}, verdict `{k.verdict}` on a copy of main's graph. "
        f"Paths left: {len(k.paths_left)}. Requirements broken: {len(k.requirements_broken)}.",
    ]
    if result.rotate:
        parts += [
            "",
            "**Rotate** these secrets as well, since the workflows could read them before this merges:",
        ]
        parts += [f"- `{name(s)}`" for s in result.rotate]
    if page:
        parts += ["", f"[See the finding on a graph →]({page})"]
    parts.append(NOTES_CLOSE)
    return "\n".join(parts)


def purpose_text(body: str) -> str:
    """A PR body as its review reads it for intent: without Theseus's own notes blocks. Removing text only
    narrows what the model reads; nothing in a PR body is evidence either way."""
    return _NOTES.sub("", body).strip()


def issue_body(finding_id: str, result: AnalysisResult, page: str | None) -> str:
    finding = result.finding or {}
    workflows = ", ".join(f"`{name(w)}`" for w in finding.get("workflows") or [])
    lines = [
        f"{finding_id} affects {workflows}. They could read these secrets, so treat them as exposed and "
        "rotate them:",
        "",
        *[f"- [ ] `{name(s)}`" for s in result.rotate],
    ]
    if page:
        lines += ["", f"[See the finding on a graph →]({page})"]
    return "\n".join(lines)


def contain(
    gh: GitHub, render: Render, repo: str, sha: str, result: AnalysisResult, page: str | None
) -> Contained | None:
    """Opens the finding's containment PR and rotate issue, or finds the ones already open. None when K did
    not pass, or applying it to `main` at `sha` changes nothing. Raises GitHubError, or PatchError when K
    cannot be written safely."""
    finding_id = str((result.finding or {}).get("id", ""))
    k = _passing(result)
    if not finding_id or k is None:
        log.info("%s: no passing containment for %s", repo, finding_id or "this finding")
        return None
    branch = branch_for(finding_id)
    pr = gh.open_pull_from(repo, branch)
    opened = False
    if pr is None:
        files = gh.world_files(repo, sha)
        edited = render(files, list(k.ops))
        if files.keys() - edited.keys():
            raise PatchError(f"containment of {finding_id} would delete files; nothing was committed")
        changed = {f"{gh.world_root}/{p}": text for p, text in edited.items() if files.get(p) != text}
        if not changed:
            log.info("%s: %s is already contained at %s", repo, finding_id, sha[:7])
            return None
        if gh.branch_head(repo, branch) is None:
            gh.create_branch(repo, branch, sha)
            gh.commit_files(repo, branch, sha, changed, commit_message(finding_id, result))
        pr = gh.open_pull(
            repo,
            branch,
            gh.default_branch(repo),
            f"fix: Contain {finding_id}",
            pr_body(finding_id, result, k, page),
            [LABEL],
        )
        opened = True
    issue = None
    if result.rotate:
        found, _ = gh.open_issue_titled(
            repo, f"Rotate these secrets: {finding_id}", issue_body(finding_id, result, page), [LABEL]
        )
        issue = str(found["html_url"])
    return Contained(
        finding=finding_id, pr=str(pr["html_url"]), pr_number=int(pr["number"]), issue=issue, opened=opened
    )
