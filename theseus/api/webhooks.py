"""`/theseus apply <ID>`: a person's approval turns a verified fix into a commit on the PR branch
(docs/spec/07-github-and-deploy.md, "The apply command").

The engine has already checked the candidate on its own graph copy; a person with write access approves it
by name; the IaC adapter writes it as verified text edits; and the App commits only files under the world
root. The commit starts a new review of the fixed head, as any push does. Nothing a comment says reaches a
model: the command is matched whole, and only its candidate ID is read.
"""

from __future__ import annotations

import json
import logging
import re
import textwrap
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from theseus.agent.render import code, escape
from theseus.api import reviews
from theseus.api.github import GitHub
from theseus.contracts.result import AnalysisResult, Candidate, PatchOp
from theseus.contracts.schema import is_candidate_id
from theseus.errors import GraphError, PatchError, TheseusError

log = logging.getLogger(__name__)

APPLY = re.compile(r"/theseus apply(?: ([A-Z][0-9]*))?")
# GitHub logins: letters, digits and single hyphens, at most 39 characters; an App's bot ends in `[bot]`.
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?")
RESULTS_KEPT = 64
WRAP = 72  # commit body width (AGENTS.md, "Commits")

# The IaC adapter's verified edits: the head's files under the world root and the ops, to the edited files.
# `api/app.py` builds it from the head's theseus.yaml; tests replace it.
Render = Callable[[dict[str, str], list[PatchOp]], dict[str, str]]


class Refused(TheseusError):
    """Apply will not commit, and says why: `status` for `POST /apply`, the message for the reply."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class NoReview(Refused):
    """No review of the PR's head is at hand. The caller starts one (`routes._review_again`) and tells the
    person with `no_review`."""

    def __init__(self, sha: str) -> None:
        super().__init__(409, f"no review of {sha[:7]}")
        self.sha = sha


@dataclass(frozen=True)
class Applied:
    candidate: str
    commit_sha: str
    branch: str
    paths: list[str]
    title: str = ""


class Results:
    """The newest reviews by (repo, PR, head commit), in memory: the result a fix is applied from. At most
    `size` are kept; the one used longest ago goes first. Safe across the threads FastAPI serves from."""

    def __init__(self, size: int = RESULTS_KEPT) -> None:
        self.size = size
        self._items: OrderedDict[tuple[str, int, str], AnalysisResult] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _key(repo: str, number: int, sha: str) -> tuple[str, int, str]:
        return repo.lower(), number, sha

    def put(self, repo: str, number: int, sha: str, result: AnalysisResult) -> None:
        key = self._key(repo, number, sha)
        with self._lock:
            self._items[key] = result
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def get(self, repo: str, number: int, sha: str) -> AnalysisResult | None:
        key = self._key(repo, number, sha)
        with self._lock:
            if key not in self._items:
                return None
            self._items.move_to_end(key)
            return self._items[key]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def apply_command(body: str) -> str | None:
    """The candidate ID when the comment is exactly `/theseus apply <ID>`, "" when it is `/theseus apply`
    alone (the recommended fix), surrounding whitespace aside; else None."""
    found = APPLY.fullmatch(body.strip())
    return (found[1] or "") if found else None


def command_for(candidate_id: str) -> str:
    """The command as the person wrote it."""
    return f"/theseus apply {candidate_id}".strip()


def recommended(result: AnalysisResult) -> Candidate | None:
    """The fix `/theseus apply` commits: the recommended one that passes, else the first that passes."""
    passing = [c for c in result.candidates if c.verdict == "pass"]
    return next((c for c in passing if c.recommended), passing[0] if passing else None)


def latest(
    results: Results, store: reviews.ReviewStore, repo: str, number: int, sha: str
) -> AnalysisResult | None:
    """The review of this PR at this head commit: from memory, else the copy kept for the review page (so a
    restart loses nothing), else None. A review of any other commit is never returned."""
    found = results.get(repo, number, sha)
    if found is not None:
        return found
    try:
        text = store.get_doc(reviews.key(repo, number))
    except GraphError as e:
        log.warning("%s#%d: cannot read the kept review: %s", repo, number, e)
        return None
    if text is None:
        return None
    try:
        doc = json.loads(text)
        if doc.get("head_sha") != sha:
            return None
        result = AnalysisResult.model_validate(doc["result"])
    except (ValueError, KeyError, TypeError, AttributeError) as e:  # ValidationError is a ValueError
        log.warning("%s#%d: the kept review cannot be read back: %s", repo, number, e)
        return None
    results.put(repo, number, sha, result)
    return result


def _one_line(text: str) -> str:
    return " ".join(text.split())


def commit_message(candidate: Candidate, result: AnalysisResult, user: str) -> str:
    """`fix: Apply the fix Theseus suggested`, a body naming the fix by what it does, the paths it closes and
    the requirements it keeps, and the `Proposed-by:` and `Requested-by:` trailers, following AGENTS.md's
    commit rules."""

    def fill(text: str, indent: str = "") -> str:
        return textwrap.fill(
            text,
            WRAP,
            initial_indent=indent,
            subsequent_indent=" " * len(indent),
            break_long_words=False,
            break_on_hyphens=False,
        )

    paths = sorted({(p.actor, p.target) for p in result.opened})
    kept = sorted(r.id for r in result.requirements if r.status == "satisfied")
    title = " ".join(candidate.title.split()).rstrip(".")
    named = title[:1].lower() + title[1:]
    body = [fill(f"Theseus checked this fix ({named}) on a copy of the reviewed graph, where it passed.")]
    if paths:
        body += ["", "It closes the dangerous paths this pull request opened:"]
        body += [fill(f"{actor} -> {target}", "- ") for actor, target in paths]
    if kept:
        body += ["", fill("It keeps the access these requirements need: " + ", ".join(kept) + ".")]
    trailers = [f"Proposed-by: {_one_line(candidate.proposed_by)}", f"Requested-by: @{user}"]
    return "\n".join(["fix: Apply the fix Theseus suggested", "", *body, "", *trailers]) + "\n"


def _passing(result: AnalysisResult) -> str:
    ids = sorted(c.id for c in result.candidates if c.verdict == "pass")
    return f"Fixes that pass: {', '.join(ids)}." if ids else "No fix passes in that review."


def apply_fix(
    gh: GitHub,
    results: Results,
    store: reviews.ReviewStore,
    render: Render,
    repo: str,
    number: int,
    candidate_id: str,
    user: str,
) -> Applied:
    """Commits the candidate's rendered edits to the PR's branch, on the head that was reviewed, as `user`'s
    approval. Raises Refused, before anything is written, unless the user may write to the repo, the PR is
    open on a branch of this repo, its head has a review, the candidate passed in it, and every edit renders,
    changes something and lies under the world root."""
    if not LOGIN.fullmatch(user):
        raise Refused(422, f"{code(user)} is not a GitHub login")
    if not gh.can_write(repo, user):
        raise Refused(403, "Only people with write access to this repository can apply a fix.")
    pr = gh.pull_request(repo, number)
    if pr.get("state") != "open":
        raise Refused(409, "This pull request is closed, so there is nothing to apply a fix to.")
    head = pr.get("head") or {}
    owner = (head.get("repo") or {}).get("full_name")
    if not owner or owner.lower() != repo.lower():
        where = f" ({code(owner)})" if owner else ""
        raise Refused(
            409,
            f"This pull request's branch lives in another repository{where}, where Theseus cannot commit. "
            "Make the change by hand, or push the branch to this repository.",
        )
    sha, branch = head["sha"], head["ref"]
    result = latest(results, store, repo, number, sha)
    if result is None:
        raise NoReview(sha)
    if not candidate_id:
        best = recommended(result)
        if best is None:
            raise Refused(
                409, f"No fix passes in the review of {code(sha[:7])}, so there is nothing to apply."
            )
        candidate_id = best.id
    candidate = next((c for c in result.candidates if c.id == candidate_id), None)
    if candidate is None or not is_candidate_id(candidate_id):
        raise Refused(404, f"The review of {code(sha[:7])} has no fix {candidate_id}. {_passing(result)}")
    if candidate.verdict != "pass":
        reason = f": {_one_line(candidate.reason)}" if candidate.reason.strip() else ""
        raise Refused(
            409,
            f"Fix {candidate_id} is `{candidate.verdict}`{reason}. Only a fix that passes can be applied. "
            f"{_passing(result)}",
        )
    files = gh.world_files(repo, sha)
    try:
        edited = render(files, list(candidate.ops))
    except PatchError as e:
        raise Refused(
            422, f"Fix {candidate_id} could not be written safely, so nothing was committed: {code(str(e))}"
        ) from e
    gone = sorted(files.keys() - edited.keys())
    if gone:
        raise Refused(422, f"Fix {candidate_id} would delete {code(', '.join(gone))}; nothing was committed.")
    changed = {f"{gh.world_root}/{path}": text for path, text in edited.items() if files.get(path) != text}
    if not changed:
        raise Refused(409, f"Fix {candidate_id} is already in this branch: applying it changes nothing.")
    outside = sorted(path for path in changed if not gh.writable(path))
    if outside:
        raise Refused(
            422,
            f"Fix {candidate_id} would write outside `{gh.world_root}/` ({code(', '.join(outside))}), so the "
            "whole commit was refused and nothing was committed.",
        )
    commit = gh.commit_files(repo, branch, sha, changed, commit_message(candidate, result, user))
    log.info("%s#%d: applied fix %s for %s as %s", repo, number, candidate_id, user, commit[:7])
    return Applied(
        candidate=candidate_id, commit_sha=commit, branch=branch, paths=sorted(changed), title=candidate.title
    )


def no_review(sha: str, outcome: str, candidate_id: str, world_root: str) -> str:
    """What to tell a person whose fix has no review of the head to come from, after asking for one:
    `outcome` is what re-running the review did ("rerun", "running" or "none")."""
    if outcome == "none":
        return (
            f"Theseus has no review of {code(sha[:7])}, this pull request's head, and no Theseus run for "
            f"that commit to repeat. Push a commit that changes `{world_root}/` to start a review."
        )
    return (
        f"Theseus has no review of {code(sha[:7])}, this pull request's head, yet: it is reviewing it now. "
        f"Comment {code(command_for(candidate_id))} again once the `Theseus` check finishes."
    )


def applied_reply(applied: Applied) -> str:
    files = ", ".join(str(code(p)) for p in applied.paths)
    return (
        f"Committed the fix ({escape(applied.title)}) to {code(applied.branch)}"
        f" as {code(applied.commit_sha[:7])} "
        f"({files}). Theseus reviews the new head now; the comment and the `Theseus` check update when it "
        "finishes."
    )


def answer(command: str, user: str, text: str) -> str:
    """A reply to a command: the command quoted, then the answer to the person who gave it."""
    return f"> {command}\n\n@{user} {text}"
