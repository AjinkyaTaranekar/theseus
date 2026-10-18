"""The analysis routes and the App's webhook (docs/spec/05-contracts.md, "API"; 07-github-and-deploy.md).

A request from the Action runs the real review (A5) and posts it on the PR as the comment and the `Theseus`
check run. A `{fixture}` request to `/analyze` or `/finding` still answers from that fixture's stub; `/scan`
runs the real scan (C3). The Try-it page (S4) runs the real engine on a PR fixture through
`POST /try/{preset}`, with the models replayed and a rate limit per address. `/theseus apply <ID>` and
`POST /apply` commit a fix that passed (A9, `api/webhooks.py`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from falkordb import FalkorDB
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

from theseus.agent.labels import MANAGED, labels_for
from theseus.agent.render import MARKER, annotations, best_fix, code, render_comment, tested_line, verdict
from theseus.api import reviews, suggest, webhooks
from theseus.api.github import CHECK_NAME, NOTHING_CHANGED, GitHub
from theseus.api.stub import result_from_expected
from theseus.config import Settings, get_settings
from theseus.contracts.incident import Incident, IncidentReport
from theseus.contracts.posture import OutageBasis, PostureReport
from theseus.contracts.result import AnalysisResult
from theseus.contracts.schema import is_candidate_id
from theseus.engine.incident import blast, read_incident
from theseus.errors import GitHubError, GraphError, PatchError, TheseusError
from theseus.graph.client import server_version

log = logging.getLogger(__name__)
router = APIRouter()

# Paths are relative to the working directory: the repo root locally, /app in the image.
FIXTURES = Path("fixtures")
SAMPLE = Path("tests/data/stub_expected.json")
FIXTURE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REVIEW_COMMAND = "/theseus review"
# The pull_request actions that start a review. `closed` starts none: `_on_closed` deletes the PR's graphs.
PR_ACTIONS = frozenset({"opened", "reopened", "synchronize", "edited"})

# What the `Theseus` check says while a review runs (07, "When Theseus reviews"): a title and a summary. The
# ruleset requires the check, so the merge waits for the verdict.
PLANNING = (
    "Reviewing: planning both commits",
    "Theseus is checking what this change lets people and services reach. It plans the Terraform at the base"
    " and head commits, builds a graph of each in FalkorDB, and traces every path to sensitive data. The"
    " merge waits for the result, usually a few minutes.",
)
AGAIN = ("Reviewing again: planning both commits", PLANNING[1])
TRACING = (
    "Reviewing: tracing paths in FalkorDB",
    "Both commits are planned. Theseus is building their graphs in FalkorDB, tracing every path to sensitive"
    " data and reading what the PR says it needs. The merge waits for the result.",
)
RETRY = "Comment `/theseus review` or re-run this check to try again."
REASON_MAX = 500


class AnalyzeRequest(BaseModel):
    """From the Action (repo and both plans) or from a test or the Try-it page (fixture)."""

    fixture: str | None = None
    repo: str | None = None
    pr_number: int | None = None
    base_sha: str | None = None
    head_sha: str | None = None
    pr_title: str | None = None
    pr_body: str | None = None
    base_plan: dict[str, Any] | None = None
    head_plan: dict[str, Any] | None = None
    checkov: dict[str, Any] | None = None


class FailedRequest(BaseModel):
    """From `Theseus publish` when the Theseus workflow failed before a review could start."""

    repo: str
    head_sha: str
    run_url: str | None = None


class ApplyRequest(BaseModel):
    """A person's approval of a fix that passed, made through the API instead of a comment."""

    repo: str
    pr_number: int
    candidate_id: str
    requested_by: str


class ApplyResponse(BaseModel):
    commit_sha: str


class PostureRequest(BaseModel):
    """`main` at a commit, planned by the Theseus main workflow."""

    repo: str
    sha: str
    plan: dict[str, Any]
    trigger: str = "workflow_dispatch"


class FindingRequest(BaseModel):
    fixture: str | None = None
    repo: str | None = None
    advisory: dict[str, Any] | None = None


class ScanRequest(BaseModel):
    fixture: str | None = None
    repo: str | None = None


class IncidentRequest(BaseModel):
    """An outage to answer on `main`: a headline (`text`), or a picked provider, service and region."""

    repo: str
    text: str | None = None
    provider: str | None = None
    service: str | None = None
    region: str | None = None
    severity: Literal["down", "degraded"] = "down"


class CheckRequest(BaseModel):
    repo: str
    trigger: str = "workflow_dispatch"


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_github(settings: SettingsDep) -> GitHub:
    """The App's client for this request; tests replace it."""
    return GitHub(settings)


GitHubDep = Annotated[GitHub, Depends(get_github)]

# The review behind `/analyze`: (gh, repo, pr number, head sha, the PR from the API, base plan, head plan).
# `api/app.py` builds the real one at startup, as the composition root; tests replace it.
Review = Callable[[GitHub, str, int, str, dict[str, Any], dict[str, Any], dict[str, Any]], AnalysisResult]


def get_review(request: Request) -> Review:
    review = getattr(request.app.state, "review", None)
    if review is None:
        raise HTTPException(503, "the review engine is not ready")
    return review


ReviewDep = Annotated[Review, Depends(get_review)]

# The scan behind `/scan`: a scan fixture's name to its result. `api/app.py` builds the real one at startup;
# tests replace it.
Scan = Callable[[str], AnalysisResult]


def get_scan(request: Request) -> Scan:
    scan = getattr(request.app.state, "scan", None)
    if scan is None:
        raise HTTPException(503, "the scan engine is not ready")
    return scan


ScanDep = Annotated[Scan, Depends(get_scan)]


# Finding mode on a fixture folder. `api/app.py` builds the real one; tests replace it.
Finder = Callable[[Path], AnalysisResult]


def get_finder(request: Request) -> Finder:
    finder = getattr(request.app.state, "finder", None)
    if finder is None:
        raise HTTPException(503, "the finding engine is not ready")
    return finder


FinderDep = Annotated[Finder, Depends(get_finder)]
FINDING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

# The posture of `main` behind `/posture`: (gh, repo, commit, its plan) to the report. `api/app.py` builds the
# real one at startup; tests replace it.
PostureRun = Callable[[GitHub, str, str, dict[str, Any]], PostureReport]


def get_posture(request: Request) -> PostureRun:
    run = getattr(request.app.state, "posture", None)
    if run is None:
        raise HTTPException(503, "the posture engine is not ready")
    return run


PostureDep = Annotated[PostureRun, Depends(get_posture)]

# A finding's containment (FM6): (gh, repo, main's commit, the finding, its page) to where its PR and rotate
# issue are, or None when nothing passes. `api/app.py` builds it with the IaC renderer; tests replace it.
Containment = Callable[[GitHub, str, str, AnalysisResult, str | None], Any]


def get_containment(request: Request) -> Containment:
    contain = getattr(request.app.state, "contain", None)
    if contain is None:
        raise HTTPException(503, "containment is not ready")
    return contain


ContainmentDep = Annotated[Containment, Depends(get_containment)]
# The providers' status feeds, read now: their incidents and a line per feed that failed. `api/app.py` builds
# it from the adapters' feed readers; tests replace it.
StatusFeeds = Callable[[], tuple[list[Incident], list[str]]]


def get_status(request: Request) -> StatusFeeds:
    feeds = getattr(request.app.state, "status_feeds", None)
    if feeds is None:
        raise HTTPException(503, "the status feeds are not ready")
    return feeds


StatusDep = Annotated[StatusFeeds, Depends(get_status)]
SHA = re.compile(r"^[0-9a-f]{40}$")
# What started a posture run: the workflow's event, or a person at the command line.
TRIGGERS = frozenset({"push", "schedule", "workflow_dispatch", "cli"})


def now() -> str:
    """The time a document is kept, for the dashboard; never part of a result."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def get_store(request: Request) -> reviews.ReviewStore:
    """The store the graphs live in, for each review's page; `api/app.py` sets it at startup."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(503, "the graph store is not ready")
    return store


StoreDep = Annotated[reviews.ReviewStore, Depends(get_store)]


def get_results(request: Request) -> webhooks.Results:
    """The reviews a fix is applied from; `api/app.py` sets it at startup."""
    results = getattr(request.app.state, "results", None)
    if results is None:
        raise HTTPException(503, "the result cache is not ready")
    return results


ResultsDep = Annotated[webhooks.Results, Depends(get_results)]


def get_render(request: Request) -> webhooks.Render:
    """The IaC adapter's verified edits for a fix; `api/app.py` builds it as the composition root."""
    render = getattr(request.app.state, "render", None)
    if render is None:
        raise HTTPException(503, "the fix renderer is not ready")
    return render


RenderDep = Annotated[webhooks.Render, Depends(get_render)]


@dataclass(frozen=True)
class Fixing:
    """What applying a fix needs besides GitHub: the reviews, the store keeping them, and the renderer."""

    results: webhooks.Results
    store: reviews.ReviewStore
    render: webhooks.Render


def _suggest(
    gh: GitHub, render: webhooks.Render, repo: str, number: int, head_sha: str, result: AnalysisResult
) -> tuple[str, int] | None:
    """Suggests the fix that passes on the PR's own lines, once per head commit, and returns where the first
    suggestion sits; None when no fix passes or its edits cannot all sit on lines of the diff, so the comment
    offers `/theseus apply <ID>` instead. A failure here never stops the review: it is logged, and apply
    stays."""
    fix = best_fix(result)
    if fix is None or not fix.ops:
        return None
    try:
        files = gh.world_files(repo, head_sha)
        edited = render(files, list(fix.ops))
        in_diff = {path: suggest.diff_lines(patch) for path, patch in gh.pull_patches(repo, number).items()}
        placed = suggest.plan(files, edited, in_diff, gh.world_root)
        if not placed.suggestions or placed.unplaced:
            log.info(
                "%s#%d: fix %s has edits off the diff (%s); offering apply",
                repo,
                number,
                fix.id,
                placed.unplaced,
            )
            return None
        marker = f"<!-- theseus:head:{head_sha} -->"
        if not gh.has_review_with(repo, number, marker):
            tested = tested_line(result)
            comments = []
            for s in placed.suggestions:
                comment = {
                    "path": s.path,
                    "line": s.end,
                    "side": "RIGHT",
                    "body": suggest.comment_body(fix.title, tested, s),
                }
                if s.start < s.end:
                    comment |= {"start_line": s.start, "start_side": "RIGHT"}
                comments.append(comment)
            gh.post_review(repo, number, head_sha, suggest.review_body(head_sha), comments)
        first = placed.suggestions[0]
        return first.path, first.start
    except (PatchError, GitHubError) as e:
        log.warning("%s#%d: could not suggest fix %s: %s", repo, number, fix.id, e)
        return None


def get_falkordb_version(request: Request) -> str | None:
    """The version of the FalkorDB the graphs are built in, for the comment; None for a stand-in or when the
    server will not say."""
    db = getattr(request.app.state, "falkordb", None)
    if not isinstance(db, FalkorDB):
        return None
    try:
        return server_version(db)
    except GraphError as e:
        log.warning("FalkorDB would not say its version: %s", e)
        return None


FalkorVersionDep = Annotated[str | None, Depends(get_falkordb_version)]


def load_expected(name: str) -> dict[str, Any]:
    """The expected.json for a fixture name, or the sample. Refuses any name that is not a plain slug."""
    if not FIXTURE_NAME.match(name):
        raise HTTPException(400, f"not a fixture name: {name!r}")
    path = SAMPLE if name == "sample" else FIXTURES / name / "expected.json"
    if not path.is_file():
        raise HTTPException(404, f"no expected.json for fixture {name!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_of(fixture: str, mode: str) -> dict[str, Any]:
    """The fixture's expected.json, or 400 and 404 when the name is bad, the fixture is missing or it is not
    a `mode` scenario."""
    expected = load_expected(fixture)
    if expected.get("mode") != mode:
        raise HTTPException(400, f"fixture {fixture!r} is a {expected.get('mode')} scenario, not {mode}")
    return expected


def stub_for(fixture: str | None, mode: str) -> AnalysisResult:
    if fixture is None:
        raise HTTPException(501, "only {fixture} requests are answered until the engine lands (E3, A5)")
    expected = fixture_of(fixture, mode)
    log.info("stub result for fixture %s", fixture)
    return result_from_expected(expected)


def card(comment: str) -> str:
    """The comment's card, for the check run's summary: everything before its diagram and the folded
    details. The Checks tab draws no diagrams."""
    top = comment.split("\n<details>", 1)[0].split("\n```mermaid", 1)[0]
    return top.replace(MARKER, "", 1).strip()


def _secret_matches(given: str | None, secret: str) -> bool:
    return given is not None and hmac.compare_digest(given.encode(), secret.encode())


def _require_repo(gh: GitHub, repo: str) -> None:
    if not gh.allowed(repo):
        log.warning("refused %s: not in THESEUS_REPOS", repo)
        raise HTTPException(403, f"{repo} is not a repo Theseus acts on")


def _require_token(settings: Settings, given: str | None) -> None:
    """Calls from `Theseus publish` carry THESEUS_TOKEN in X-Theseus-Token."""
    if settings.theseus_token is None:
        raise HTTPException(503, "THESEUS_TOKEN is not set on the server")
    if not _secret_matches(given, settings.theseus_token.get_secret_value()):
        raise HTTPException(401, "missing or wrong X-Theseus-Token")


@router.post("/analyze", response_model=AnalysisResult)
def analyze(
    req: AnalyzeRequest,
    settings: SettingsDep,
    gh: GitHubDep,
    review: ReviewDep,
    store: StoreDep,
    results: ResultsDep,
    falkordb: FalkorVersionDep,
    render: RenderDep,
    x_theseus_token: Annotated[str | None, Header()] = None,
) -> AnalysisResult:
    """PR mode. With a repo, from the Action: the real review of the PR's two commits (A5), posted as the
    comment and the `Theseus` check run. With `{fixture}` only, the stub answers (the Try-it page, S4)."""
    if req.repo is None:
        return stub_for(req.fixture, "pr")
    _require_token(settings, x_theseus_token)
    if req.pr_number is None or req.head_sha is None:
        raise HTTPException(422, "a request with a repo needs pr_number and head_sha")
    if req.base_plan is None or req.head_plan is None:
        raise HTTPException(422, "a review needs the plan of the base and of the head")
    _require_repo(gh, req.repo)
    try:
        # A review reads the PR as it is now, not the copy the Action's event carried (07, "When Theseus
        # reviews"): its title and body for the intent, its base commit for the base world.
        pr = gh.pull_request(req.repo, req.pr_number)
        gh.pending_check(req.repo, req.head_sha, *TRACING)
        try:
            result = review(gh, req.repo, req.pr_number, req.head_sha, pr, req.base_plan, req.head_plan)
        except TheseusError as e:
            # The check fails with the reason, so the merge stays blocked and says why (it fails closed).
            log.error("%s#%d: the review could not finish: %s", req.repo, req.pr_number, e)
            reason = f"Theseus could not finish reviewing this commit: {code(str(e)[:REASON_MAX])}"
            gh.upsert_check(
                req.repo,
                req.head_sha,
                "failure",
                "Review could not finish",
                f"{reason}\n\nThe merge stays blocked until a review finishes. {RETRY}",
            )
            raise HTTPException(500, f"the review could not finish: {e}") from e
        # Kept by the commit it reviewed: `/theseus apply` commits a fix only on the head it was checked on.
        results.put(req.repo, req.pr_number, req.head_sha, result)
        url = reviews.page_url(settings, req.repo, req.pr_number)
        # The fix that passes, as suggestions on the PR's own lines, before the comment that points at them.
        suggestion = (
            _suggest(gh, render, req.repo, req.pr_number, req.head_sha, result)
            if pr["head"]["sha"] == req.head_sha
            else None
        )
        comment = render_comment(
            result,
            req.repo,
            req.head_sha,
            req.checkov,
            settings.theseus_world_root,
            falkordb,
            url,
            suggestion,
        )
        status = verdict(result)
        notes = annotations(result, settings.theseus_world_root)
        gh.upsert_check(
            req.repo, req.head_sha, status.conclusion, status.title, card(comment), annotations=notes
        )
        if pr["head"]["sha"] == req.head_sha:
            # The page is kept first, so its link works the moment the comment shows it.
            shas = ((pr.get("base") or {}).get("sha") or "", req.head_sha)
            reviews.save(
                store,
                req.repo,
                req.pr_number,
                shas,
                settings.theseus_world_root,
                result,
                title=str(pr.get("title") or ""),
                updated_at=now(),
                # A review of a PR that is already closed (its description was edited, its check re-run)
                # keeps no graphs: nothing will close it again to delete them.
                closed=pr.get("state") == "closed",
            )
            gh.upsert_comment(req.repo, req.pr_number, comment)
            gh.set_labels(req.repo, req.pr_number, labels_for(result), MANAGED)
        else:
            log.info(
                "%s#%d moved on from %s; leaving the comment to the newer run",
                req.repo,
                req.pr_number,
                req.head_sha[:7],
            )
    except GitHubError as e:
        log.error("%s#%d: %s", req.repo, req.pr_number, e)
        raise HTTPException(502, str(e)) from e
    return result


@router.post("/apply", response_model=ApplyResponse)
def apply(
    req: ApplyRequest,
    settings: SettingsDep,
    gh: GitHubDep,
    results: ResultsDep,
    store: StoreDep,
    render: RenderDep,
    x_theseus_token: Annotated[str | None, Header()] = None,
) -> ApplyResponse:
    """Commits a fix that passed to the PR branch, approved by `requested_by`, who must have write access:
    the same checks and the same commit as `/theseus apply <ID>`. Refuses any file outside the world root."""
    _require_token(settings, x_theseus_token)
    _require_repo(gh, req.repo)
    if req.candidate_id and not is_candidate_id(req.candidate_id):
        raise HTTPException(422, f"not a candidate ID: {req.candidate_id!r}")
    try:
        applied = webhooks.apply_fix(
            gh, results, store, render, req.repo, req.pr_number, req.candidate_id, req.requested_by
        )
    except webhooks.NoReview as e:
        outcome = _review_again(gh, req.repo, e.sha, [req.pr_number])
        raise HTTPException(409, webhooks.no_review(e.sha, outcome, req.candidate_id, gh.world_root)) from e
    except webhooks.Refused as e:
        raise HTTPException(e.status, str(e)) from e
    except GitHubError as e:
        log.error("%s#%d: apply %s: %s", req.repo, req.pr_number, req.candidate_id, e)
        raise HTTPException(502, str(e)) from e
    return ApplyResponse(commit_sha=applied.commit_sha)


@router.post("/review-failed", status_code=204)
def review_failed(
    req: FailedRequest,
    settings: SettingsDep,
    gh: GitHubDep,
    x_theseus_token: Annotated[str | None, Header()] = None,
) -> Response:
    """The Theseus workflow failed before a review, often on a plan error: the commit's check fails with a
    link to the run, so the merge stays blocked and says why. A verdict already on the commit stays."""
    _require_token(settings, x_theseus_token)
    _require_repo(gh, req.repo)
    run_url = re.compile(rf"https://github\.com/{re.escape(req.repo)}/actions/runs/\d+(/attempts/\d+)?")
    link = f" [See the run]({req.run_url})." if req.run_url and run_url.fullmatch(req.run_url) else ""
    try:
        latest = gh.latest_check(req.repo, req.head_sha)
        if latest is not None and latest.get("status") == "completed":
            log.info("%s@%s: a check is already complete; leaving it", req.repo, req.head_sha[:7])
            return Response(status_code=204)
        gh.upsert_check(
            req.repo,
            req.head_sha,
            "failure",
            "Review could not run",
            "The Theseus workflow failed before the review could start, often because `terraform plan`"
            f" failed on this commit.{link}\n\nThe merge stays blocked until a review finishes. Push a fix,"
            " or re-run this check to try again.",
        )
    except GitHubError as e:
        log.error("%s@%s: %s", req.repo, req.head_sha[:7], e)
        raise HTTPException(502, str(e)) from e
    return Response(status_code=204)


# Each review's page -----------------------------------------------------------------------------------------

PAGE = Path(__file__).resolve().parents[1] / "web" / "review.html"


def _reviewed(settings: Settings, gh: GitHub, owner: str, name: str, number: int, k: str | None) -> str:
    """The repo, when the link is signed for it and it is one Theseus acts on; a 404 otherwise, so a wrong
    link says nothing about what exists."""
    repo = f"{owner}/{name}"
    if not gh.allowed(repo) or not reviews.signed(settings, repo, number, k):
        raise HTTPException(404, "no such review")
    return repo


# The lines behind a claim --------------------------------------------------------------------------------

SOURCE_FILE = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")
SOURCE_AROUND = 6
_sources: dict[tuple[str, str, str], str] = {}


def _source_lines(
    gh: GitHub, repo: str, sha: str, world_root: str, file: str, line: int | None
) -> dict[str, Any]:
    """The lines around `line` of a world file at a commit, read through the App and kept per commit: a
    commit's file never changes. A path outside the world root, or with `..`, is a 422."""
    if not SOURCE_FILE.fullmatch(file) or ".." in file.split("/") or len(file) > 200:
        raise HTTPException(422, "name a file under the world root, such as terraform/people.tf")
    if not SHA.fullmatch(sha):
        raise HTTPException(404, "no commit to read")
    cache = (repo, sha, file)
    if cache not in _sources:
        try:
            _sources[cache] = gh.read_file(repo, f"{world_root.strip('/')}/{file}", sha)
        except GitHubError as e:
            log.warning("%s@%s: cannot read %s: %s", repo, sha[:7], file, e)
            raise HTTPException(404, "that file isn't at this commit") from e
        if len(_sources) > 256:
            _sources.pop(next(iter(_sources)))
    text = _sources[cache].splitlines()
    at = min(max(line or 1, 1), max(len(text), 1))
    start, end = max(1, at - SOURCE_AROUND), min(len(text), at + SOURCE_AROUND)
    return {
        "file": file,
        "line": line,
        "sha": sha,
        "start": start,
        "lines": [{"n": n, "text": text[n - 1]} for n in range(start, end + 1)],
        "url": f"https://github.com/{repo}/blob/{sha}/{world_root.strip('/')}/{file}"
        + (f"#L{line}" if line else ""),
    }


@router.get("/dashboard/{owner}/{name}/source")
def dashboard_source(
    owner: str,
    name: str,
    settings: SettingsDep,
    gh: GitHubDep,
    store: StoreDep,
    k: str | None = None,
    file: str = "",
    line: int | None = None,
) -> dict[str, Any]:
    """The Terraform lines behind a claim on the dashboard, at main's scanned commit, so the proof opens for
    someone who can't open the private repo on GitHub."""
    repo = _dashboard_repo(settings, gh, owner, name, k)
    try:
        posture = reviews.kept_posture(store, repo)
    except GraphError as e:
        raise HTTPException(502, "the graph store did not answer") from e
    if posture is None:
        raise HTTPException(404, "main hasn't been scanned yet")
    return _source_lines(
        gh, repo, posture.get("sha", ""), posture.get("world_root") or settings.theseus_world_root, file, line
    )


@router.get("/reviews/{owner}/{name}/{number}/source")
def review_source(
    owner: str,
    name: str,
    number: int,
    settings: SettingsDep,
    gh: GitHubDep,
    store: StoreDep,
    k: str | None = None,
    file: str = "",
    line: int | None = None,
) -> dict[str, Any]:
    """The lines behind a step on a review's page, at the PR's head commit."""
    repo = _reviewed(settings, gh, owner, name, number, k)
    try:
        doc = reviews.kept_review(store, repo, number)
    except GraphError as e:
        raise HTTPException(502, "the graph store did not answer") from e
    if doc is None:
        raise HTTPException(404, "no such review")
    return _source_lines(
        gh, repo, doc.get("head_sha", ""), doc.get("world_root") or settings.theseus_world_root, file, line
    )


@router.get("/reviews/{owner}/{name}/{number}", response_class=HTMLResponse)
def review_page(
    owner: str, name: str, number: int, settings: SettingsDep, gh: GitHubDep, k: str | None = None
) -> HTMLResponse:
    """The page that draws a review's graphs; it reads them from `.../data` with the same signed link."""
    _reviewed(settings, gh, owner, name, number, k)
    return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/reviews/{owner}/{name}/{number}/data")
def review_data(
    owner: str,
    name: str,
    number: int,
    settings: SettingsDep,
    gh: GitHubDep,
    store: StoreDep,
    k: str | None = None,
) -> dict[str, Any]:
    """The PR's newest review and both its graphs, read from the store now."""
    repo = _reviewed(settings, gh, owner, name, number, k)
    try:
        data = reviews.page_data(store, repo, number)
    except GraphError as e:
        log.error("%s#%d: cannot read the review: %s", repo, number, e)
        raise HTTPException(502, "the graph store did not answer") from e
    if data is None:
        raise HTTPException(404, "no such review")
    return {**data, "dashboard": reviews.dashboard_url(settings, repo)}


@router.get("/reviews/{owner}/{name}/{number}/fixes/{fix_id}")
def review_fix(
    owner: str,
    name: str,
    number: int,
    fix_id: str,
    settings: SettingsDep,
    gh: GitHubDep,
    store: StoreDep,
    k: str | None = None,
) -> dict[str, Any]:
    """One fix and the graph copy the engine verified it on, read from the store when its view opens."""
    repo = _reviewed(settings, gh, owner, name, number, k)
    if not is_candidate_id(fix_id):
        raise HTTPException(404, "no such fix")
    try:
        fix = reviews.fix_graph(store, reviews.key(repo, number), fix_id)
    except GraphError as e:
        log.error("%s#%d: cannot read fix %s: %s", repo, number, fix_id, e)
        raise HTTPException(502, "the graph store did not answer") from e
    if fix is None:
        raise HTTPException(404, "no such fix")
    return fix


# The Try-it page (S4) ---------------------------------------------------------------------------------------

WEB = Path(__file__).resolve().parents[1] / "web"
# The only files `/web/` serves: the review page is behind its signed link, never here.
WEB_FILES = {"app.js": "text/javascript", "style.css": "text/css"}
PAGE_POLICY = (
    "default-src 'self'; script-src 'self' https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline';"
    " img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)
TRY_LIMIT = 10
TRY_WINDOW = 60.0
TRY_CLIENTS = 10_000

# The engine behind `/try/{preset}`: a fixture name to its result. `api/app.py` builds the real one at
# startup, as the composition root; tests replace it.
Try = Callable[[str], AnalysisResult]
_PAGE = Environment(loader=FileSystemLoader(WEB), autoescape=select_autoescape(["html"]))


def presets() -> dict[str, str]:
    """The presets the page offers: each PR fixture's name and what it does, sorted by name. Finding and scan
    fixtures are not offered: the page draws PR results."""
    found: dict[str, str] = {}
    for path in sorted(FIXTURES.glob("*/scenario.yaml")):
        scenario = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if scenario.get("mode") == "pr" and FIXTURE_NAME.match(path.parent.name):
            found[path.parent.name] = " ".join(str(scenario.get("description", "")).split())
    return found


class RateLimit:
    """At most `limit` requests per `window` seconds for each client, counted in this process. A refused
    request is not counted. The table is capped at `max_clients`: when it fills, quiet clients go first, then
    the oldest, so a flood of addresses cannot grow it without bound. `clock` is for tests."""

    def __init__(
        self,
        limit: int = TRY_LIMIT,
        window: float = TRY_WINDOW,
        clock: Callable[[], float] = time.monotonic,
        max_clients: int = TRY_CLIENTS,
    ) -> None:
        self.limit, self.window, self.clock, self.max_clients = limit, window, clock, max_clients
        self.hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def take(self, client: str) -> int | None:
        """Counts a request and returns None, or returns the whole seconds until one is allowed."""
        with self._lock:
            now = self.clock()
            seen = self.hits.setdefault(client, deque())
            while seen and now - seen[0] >= self.window:
                seen.popleft()
            if len(seen) >= self.limit:
                return max(1, int(seen[0] + self.window - now + 0.999))
            seen.append(now)
            if len(self.hits) > self.max_clients:
                self._shrink(now)
            return None

    def _shrink(self, now: float) -> None:
        for client in [c for c, seen in self.hits.items() if not seen or now - seen[-1] >= self.window]:
            del self.hits[client]
        # Still full: drop the clients that have been quiet longest, never the one being served.
        extra = len(self.hits) - self.max_clients
        for client in sorted(self.hits, key=lambda c: self.hits[c][-1])[: max(0, extra)]:
            del self.hits[client]


def client_address(request: Request) -> str:
    """Who is asking. The API is reached through Tailscale Funnel, which appends the address it saw to
    X-Forwarded-For, so the last entry is the one to trust: the first is whatever the client wrote. With no
    header (a direct call) it is the socket's peer."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def get_try(request: Request) -> Try:
    runner = getattr(request.app.state, "try_preset", None)
    if runner is None:
        raise HTTPException(503, "the engine is not ready")
    return runner


TryDep = Annotated[Try, Depends(get_try)]


def limited(request: Request) -> None:
    """429 with Retry-After once this address has used its allowance."""
    limiter = getattr(request.app.state, "try_limiter", None)
    if limiter is None:
        raise HTTPException(503, "the engine is not ready")
    wait = limiter.take(client_address(request))
    if wait is not None:
        log.info("try: %s is over %d a minute", client_address(request), limiter.limit)
        detail = f"{limiter.limit} tries a minute is the limit; try again in {wait} s"
        raise HTTPException(429, detail, {"Retry-After": str(wait)})


@router.get("/", response_class=HTMLResponse)
def try_page(settings: SettingsDep) -> HTMLResponse:
    """The front page: what Theseus is and every way in, the first repository's live dashboard (its signed
    link, when this server has a public hostname and a token), and one Try-it button for each preset."""
    repo = settings.repos[0] if settings.repos else None
    dashboard = reviews.dashboard_url(settings, repo) if repo else None
    html = _PAGE.get_template("index.html").render(presets=presets(), dashboard=dashboard, repo=repo)
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Content-Security-Policy": PAGE_POLICY})


@router.get("/web/{name}")
def web_file(name: str) -> FileResponse:
    """The page's script or style; 404 for any other name."""
    media = WEB_FILES.get(name)
    if media is None:
        raise HTTPException(404, "no such file")
    return FileResponse(WEB / name, media_type=media, headers={"Cache-Control": "no-cache"})


@router.post("/try/{preset}", response_model=AnalysisResult, dependencies=[Depends(limited)])
def try_preset(preset: str, run: TryDep) -> AnalysisResult:
    """The real engine on a PR fixture, with the models replayed: what the Action's review would say about it.
    Rate limited to 10 a minute per address."""
    if preset not in presets():
        raise HTTPException(404, f"not a preset: {preset!r}")
    try:
        return run(preset)
    except GraphError as e:
        log.error("try %s: the graph store did not answer: %s", preset, e)
        raise HTTPException(503, "the graph store did not answer; try again shortly") from e
    except TheseusError as e:
        log.error("try %s: %s", preset, e)
        raise HTTPException(502, "the engine could not analyze this preset") from e


@router.post("/finding", response_model=AnalysisResult)
def finding(
    req: FindingRequest,
    response: Response,
    settings: SettingsDep,
    store: StoreDep,
    finder: FinderDep,
    x_theseus_token: Annotated[str | None, Header()] = None,
) -> AnalysisResult:
    """Finding mode. Without a token, `{fixture}` answers from its stub (the Try-it page). With
    THESEUS_TOKEN, the real engine runs on the fixture with live Jev, the result is kept for its page, and
    the page's signed link comes back in `X-Theseus-Page`. Advisories from a repo arrive with FM6."""
    if x_theseus_token is None:
        return stub_for(req.fixture, "finding")
    _require_token(settings, x_theseus_token)
    if req.fixture is None:
        raise HTTPException(422, "a finding run needs a fixture until FM6 reads advisories from a repo")
    expected = load_expected(req.fixture)
    if expected.get("mode") != "finding":
        raise HTTPException(400, f"fixture {req.fixture!r} is a {expected.get('mode')} scenario, not finding")
    try:
        result = finder(FIXTURES / req.fixture)
    except TheseusError as e:
        log.error("finding %s could not finish: %s", req.fixture, e)
        raise HTTPException(500, f"the finding could not finish: {e}") from e
    repo = settings.repos[0] if settings.repos else ""
    reviews.save_finding(store, repo, f"fixtures/{req.fixture}/base", result)
    url = reviews.finding_url(settings, (result.finding or {}).get("id", ""))
    if url:
        response.headers["X-Theseus-Page"] = url
    return result


def _signed_finding(settings: Settings, finding_id: str, k: str | None) -> str:
    if not FINDING_ID.match(finding_id) or not reviews.signed_key(
        settings, reviews.finding_key(finding_id), k
    ):
        raise HTTPException(404, "no such finding")
    return finding_id


@router.get("/findings/{finding_id}", response_class=HTMLResponse)
def finding_page(finding_id: str, settings: SettingsDep, k: str | None = None) -> HTMLResponse:
    """The same page as a review's, drawing a finding: what a compromised Action reaches."""
    _signed_finding(settings, finding_id, k)
    return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/findings/{finding_id}/data")
def finding_data(
    finding_id: str, settings: SettingsDep, store: StoreDep, k: str | None = None
) -> dict[str, Any]:
    """The finding's newest result and its graph, read from the store now."""
    _signed_finding(settings, finding_id, k)
    try:
        data = reviews.page_doc(store, reviews.finding_key(finding_id))
    except GraphError as e:
        log.error("finding %s: cannot read it: %s", finding_id, e)
        raise HTTPException(502, "the graph store did not answer") from e
    if data is None:
        raise HTTPException(404, "no such finding")
    return {**data, "dashboard": reviews.dashboard_url(settings, str(data.get("repo") or ""))}


@router.get("/findings/{finding_id}/source")
def finding_source(
    finding_id: str,
    settings: SettingsDep,
    gh: GitHubDep,
    store: StoreDep,
    k: str | None = None,
    file: str = "",
    line: int | None = None,
) -> dict[str, Any]:
    """The lines behind a step on a finding's page, at the commit of main it was found on."""
    _signed_finding(settings, finding_id, k)
    try:
        doc = reviews.page_doc(store, reviews.finding_key(finding_id))
    except GraphError as e:
        raise HTTPException(502, "the graph store did not answer") from e
    repo = str((doc or {}).get("repo") or "")
    if doc is None or not gh.allowed(repo):
        raise HTTPException(404, "no such finding")
    return _source_lines(
        gh, repo, doc.get("head_sha", ""), doc.get("world_root") or settings.theseus_world_root, file, line
    )


@router.post("/scan", response_model=AnalysisResult)
def scan(req: ScanRequest, run: ScanDep) -> AnalysisResult:
    """Scan mode (C3). With `{fixture}`, the real scan of that fixture's `main`: the dangerous paths already
    there, the grants its code never calls and candidate U. A repo needs the issue and fix PRs that
    `/theseus apply` (A9) will open, so it is refused until then."""
    if req.fixture is None:
        raise HTTPException(501, "scanning a repo opens an issue and fix PRs, which wait for apply (A9)")
    fixture_of(req.fixture, "scan")
    try:
        return run(req.fixture)
    except TheseusError as e:
        log.error("scan of %s failed: %s", req.fixture, e)
        raise HTTPException(500, f"the scan could not finish: {e}") from e


@router.post("/posture")
def posture(
    req: PostureRequest,
    response: Response,
    settings: SettingsDep,
    gh: GitHubDep,
    run: PostureDep,
    store: StoreDep,
    contain: ContainmentDep,
    x_theseus_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """The posture of `main` (O1 to O3), sent by the Theseus main workflow on a push to `main`, nightly and on
    demand: its graph in FalkorDB, the scan, who reaches what, single points of failure, articulation points,
    the cost, and a finding for each advisory that affects it. Kept for the dashboard, whose link comes back
    in `X-Theseus-Page`."""
    _require_token(settings, x_theseus_token)
    _require_repo(gh, req.repo)
    if not SHA.fullmatch(req.sha):
        raise HTTPException(422, "sha must be a full commit SHA")
    if req.trigger not in TRIGGERS:
        raise HTTPException(422, f"trigger must be one of {', '.join(sorted(TRIGGERS))}")
    try:
        report = run(gh, req.repo, req.sha, req.plan)
    except GitHubError as e:
        log.error("%s@%s: posture: %s", req.repo, req.sha[:7], e)
        raise HTTPException(502, str(e)) from e
    except TheseusError as e:
        log.error("%s@%s: posture could not finish: %s", req.repo, req.sha[:7], e)
        raise HTTPException(500, f"the posture run could not finish: {e}") from e
    try:
        reviews.save_posture(
            store, req.repo, req.sha, settings.theseus_world_root, report, req.trigger, now()
        )
    except GraphError as e:
        log.error("%s: cannot keep the posture: %s", req.repo, e)
        raise HTTPException(502, "the graph store did not answer") from e
    contained, failed = [], []
    for finding in report.findings:
        finding_id = str((finding.finding or {}).get("id", ""))
        try:
            done = contain(gh, req.repo, req.sha, finding, reviews.finding_url(settings, finding_id))
        except TheseusError as e:  # one finding's PR failing leaves the posture and the others in place
            log.error("%s: containment of %s failed: %s", req.repo, finding_id, e)
            failed.append({"finding": finding_id, "error": str(e)})
            continue
        if done is not None:
            reviews.mark_contained(store, finding_id, done.pr, done.pr_number, done.issue)
            contained.append(
                {"finding": finding_id, "pr": done.pr, "issue": done.issue, "opened": done.opened}
            )
    url = reviews.dashboard_url(settings, req.repo)
    if url:
        response.headers["X-Theseus-Page"] = url
    return {
        "repo": req.repo,
        "sha": req.sha,
        "graph": report.scan.graphs.get("main"),
        "dangerous": len(report.scan.unchanged),
        "unused_grants": len(report.scan.unused_grants),
        "single_points": len(report.posture.single_points),
        "monthly_usd": report.posture.cost.monthly_usd,
        "findings": sorted((f.finding or {}).get("id", "") for f in report.findings),
        "contained": contained,
        "containment_failed": failed,
        "dashboard": url,
        "org": reviews.org_url(settings, req.repo.split("/", 1)[0]),
    }


# An outage's blast radius on main -------------------------------------------------------------------------

TEXT_MAX = 500


def _basis(store: reviews.ReviewStore, repo: str) -> OutageBasis:
    try:
        basis = reviews.outage_basis(store, repo)
    except GraphError as e:
        log.error("%s: cannot read the outage basis: %s", repo, e)
        raise HTTPException(502, "the graph store did not answer") from e
    if basis is None:
        raise HTTPException(404, "main has no posture with an outage basis yet; run Theseus main")
    return basis


def _incident(
    basis: OutageBasis,
    text: str | None,
    provider: str | None,
    service: str | None,
    region: str | None,
    severity: Literal["down", "degraded"],
) -> Incident:
    """The incident a headline names, or the one picked; a 422 naming what is known when neither works."""
    regions = {r.code for r in basis.regions}
    if region and region not in regions:
        raise HTTPException(422, f"unknown region {region[:40]!r}")
    if text and text.strip():
        found = read_incident(text[:TEXT_MAX], basis.terms, basis.regions)
        if found is None:
            names = ", ".join(t.name for t in basis.terms[:8])
            raise HTTPException(422, f"the headline names no service Theseus maps, such as {names}")
        return found.model_copy(update={"region": region or found.region})
    term = next((t for t in basis.terms if (t.provider, t.service) == (provider, service)), None)
    if term is None:
        raise HTTPException(422, "give a headline, or a provider and service from the picker")
    return Incident(
        provider=term.provider, service=term.service, region=region, severity=severity, title=term.name
    )


@router.post("/incident", response_model=IncidentReport)
def incident(
    req: IncidentRequest,
    settings: SettingsDep,
    gh: GitHubDep,
    store: StoreDep,
    x_theseus_token: Annotated[str | None, Header()] = None,
) -> IncidentReport:
    """An outage's blast radius on `main`, answered from the outage basis its newest posture kept: what goes
    down, what loses something it needs, and which dependencies break. The headline is matched against
    service and region names only; it is never evidence and never an instruction."""
    _require_token(settings, x_theseus_token)
    _require_repo(gh, req.repo)
    basis = _basis(store, req.repo)
    return blast(basis, _incident(basis, req.text, req.provider, req.service, req.region, req.severity))


def _check(store: reviews.ReviewStore, repo: str, feeds: StatusFeeds, trigger: str) -> dict[str, Any]:
    basis = _basis(store, repo)
    incidents, errors = feeds()
    reports = [blast(basis, i) for i in incidents]
    # The ones that reach this world first; the rest stay listed, so a reader sees what was checked.
    reports.sort(key=lambda r: (not r.matched, -len(r.broken), r.incident.provider, r.incident.service))
    try:
        return reviews.save_incidents(store, repo, reports, errors, now(), trigger)
    except GraphError as e:
        log.error("%s: cannot keep the incidents: %s", repo, e)
        raise HTTPException(502, "the graph store did not answer") from e


@router.post("/incidents/check")
def incidents_check(
    req: CheckRequest,
    settings: SettingsDep,
    gh: GitHubDep,
    store: StoreDep,
    feeds: StatusDep,
    x_theseus_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Reads the providers' status feeds now and keeps each current incident's blast radius on `main` for
    the dashboard. Sent by the Theseus main workflow nightly and on demand."""
    _require_token(settings, x_theseus_token)
    _require_repo(gh, req.repo)
    if req.trigger not in TRIGGERS:
        raise HTTPException(422, f"trigger must be one of {', '.join(sorted(TRIGGERS))}")
    doc = _check(store, req.repo, feeds, req.trigger)
    return {
        "repo": req.repo,
        "incidents": len(doc["reports"]),
        "reaching_main": sum(1 for r in doc["reports"] if r["matched"]),
        "errors": doc["errors"],
        "headlines": [r["headline"] for r in doc["reports"] if r["matched"]],
    }


# The organisation's dashboard (O4) --------------------------------------------------------------------------

DASHBOARD = Path(__file__).resolve().parents[1] / "web" / "dashboard.html"


def _dashboard_repo(settings: Settings, gh: GitHub, owner: str, name: str, k: str | None) -> str:
    """The repo, when the link is signed for its dashboard and Theseus acts on it; a 404 otherwise."""
    repo = f"{owner}/{name}"
    if not gh.allowed(repo) or not reviews.signed_key(settings, reviews.dashboard_key(repo), k):
        raise HTTPException(404, "no such dashboard")
    return repo


@router.get("/dashboard/{owner}/{name}", response_class=HTMLResponse)
def dashboard_page(
    owner: str, name: str, settings: SettingsDep, gh: GitHubDep, k: str | None = None
) -> HTMLResponse:
    """One page for the organisation: `main`'s posture, every PR review and every finding, and onboarding."""
    _dashboard_repo(settings, gh, owner, name, k)
    return HTMLResponse(DASHBOARD.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/dashboard/{owner}/{name}/reviews")
def dashboard_reviews(
    owner: str,
    name: str,
    settings: SettingsDep,
    gh: GitHubDep,
    store: StoreDep,
    k: str | None = None,
    q: str = "",
    verdict: str = "",
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """One page of the repo's PR reviews, filtered and searched on the server, so a repo with thousands of
    PRs sends only the page in view."""
    repo = _dashboard_repo(settings, gh, owner, name, k)
    if verdict not in ("", "blocked", "look", "clear"):
        raise HTTPException(422, "verdict must be blocked, look or clear")
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(422, "offset must be 0 or more and limit 1 to 200")
    try:
        return reviews.review_page(
            store, settings, repo, q=q[:200], verdict=verdict, offset=offset, limit=limit
        )
    except GraphError as e:
        log.error("%s: cannot read the reviews: %s", repo, e)
        raise HTTPException(502, "the graph store did not answer") from e


@router.get("/dashboard/{owner}/{name}/incident", response_model=IncidentReport)
def dashboard_incident(
    owner: str,
    name: str,
    settings: SettingsDep,
    gh: GitHubDep,
    store: StoreDep,
    k: str | None = None,
    text: str | None = None,
    provider: str | None = None,
    service: str | None = None,
    region: str | None = None,
    severity: Literal["down", "degraded"] = "down",
) -> IncidentReport:
    """The dashboard's what-if: an outage picked or typed, answered from the kept basis. Reads only."""
    repo = _dashboard_repo(settings, gh, owner, name, k)
    basis = _basis(store, repo)
    return blast(basis, _incident(basis, text, provider, service, region or None, severity))


@router.get("/dashboard/{owner}/{name}/compromise")
def dashboard_compromise(
    owner: str,
    name: str,
    settings: SettingsDep,
    gh: GitHubDep,
    store: StoreDep,
    k: str | None = None,
    node: str = "",
) -> dict[str, Any]:
    """What a node could reach on main if it were compromised, traced now by the engine on main's graph in
    FalkorDB: every resource with its shortest valid path and the file and line behind each hop, the data
    classes at risk, and the links any one of which cuts every route to sensitive data. Reads only."""
    repo = _dashboard_repo(settings, gh, owner, name, k)
    if not node or len(node) > 300:
        raise HTTPException(422, "name a node on main, such as user:casey-contractor")
    try:
        found = reviews.compromise(store, repo, node)
    except KeyError as e:
        raise HTTPException(404, "main's graph has no such node") from e
    except GraphError as e:
        log.error("%s: cannot trace %s: %s", repo, node, e)
        raise HTTPException(502, "the graph store did not answer") from e
    if found is None:
        raise HTTPException(404, "main has no graph yet")
    return found


@router.post("/dashboard/{owner}/{name}/incidents/check")
def dashboard_incidents_check(
    owner: str,
    name: str,
    settings: SettingsDep,
    gh: GitHubDep,
    store: StoreDep,
    feeds: StatusDep,
    k: str | None = None,
) -> dict[str, Any]:
    """Checks the status feeds now, from the dashboard: the nightly check, kept the same way."""
    repo = _dashboard_repo(settings, gh, owner, name, k)
    return _check(store, repo, feeds, "workflow_dispatch")


@router.get("/dashboard/{owner}/{name}/graph")
def dashboard_graph(
    owner: str, name: str, settings: SettingsDep, gh: GitHubDep, store: StoreDep, k: str | None = None
) -> dict[str, Any]:
    """`main`'s whole graph, read from FalkorDB now, for the dashboard's Graph view. Loaded only when that
    view opens, so the other views stay light however large the graph is."""
    repo = _dashboard_repo(settings, gh, owner, name, k)
    try:
        graph = reviews.main_graph(store, repo)
    except GraphError as e:
        log.error("%s: cannot read main's graph: %s", repo, e)
        raise HTTPException(502, "the graph store did not answer") from e
    if graph is None:
        raise HTTPException(404, "main has no graph yet")
    return graph


def _org(settings: Settings, gh: GitHub, owner: str, k: str | None) -> str:
    """The owner, when the link is signed for its organisation dashboard and Theseus acts on one of its
    repos; a 404 otherwise."""
    acts = any(r.split("/", 1)[0].lower() == owner.lower() for r in settings.repos)
    if not acts or not reviews.signed_key(settings, reviews.org_key(owner), k):
        raise HTTPException(404, "no such organisation")
    return owner


@router.get("/org/{owner}", response_class=HTMLResponse)
def org_page(owner: str, settings: SettingsDep, gh: GitHubDep, k: str | None = None) -> HTMLResponse:
    """The organisation's dashboard: every connected repo at a glance, each linked to its own."""
    _org(settings, gh, owner, k)
    return HTMLResponse(DASHBOARD.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/org/{owner}/data")
def org_data(
    owner: str, settings: SettingsDep, gh: GitHubDep, store: StoreDep, k: str | None = None
) -> dict[str, Any]:
    """Every connected repo's posture and reviews, summarised, with totals; read from FalkorDB now."""
    _org(settings, gh, owner, k)
    try:
        return reviews.org_data(store, settings, owner)
    except GraphError as e:
        log.error("%s: cannot read the organisation: %s", owner, e)
        raise HTTPException(502, "the graph store did not answer") from e


@router.get("/dashboard/{owner}/{name}/data")
def dashboard_data(
    owner: str, name: str, settings: SettingsDep, gh: GitHubDep, store: StoreDep, k: str | None = None
) -> dict[str, Any]:
    """What the dashboard shows, read from FalkorDB now."""
    repo = _dashboard_repo(settings, gh, owner, name, k)
    try:
        return reviews.dashboard_data(store, settings, repo)
    except GraphError as e:
        log.error("%s: cannot read the dashboard: %s", repo, e)
        raise HTTPException(502, "the graph store did not answer") from e


# The App's webhook ------------------------------------------------------------------------------------------


def _signed(body: bytes, signature: str | None, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return _secret_matches(signature, expected)


def _nothing_changed(gh: GitHub, repo: str, number: int, head_sha: str) -> bool:
    """Posts a `success` check when the PR changes nothing under the world root, so every PR gets the check
    the ruleset requires. Returns whether it did.

    A check belongs to a commit, not a PR, and two PRs can share a head while targeting different bases. So
    the check passes only when no open PR with this head changes the world root: a second PR never replaces
    the first one's review with a pass. And when one does, a pass already on the commit is withdrawn, so the
    required check waits for that review instead of staying green."""
    for pr in sorted({number, *gh.open_pulls_at(repo, head_sha)}):
        if gh.touches_world_root(repo, pr):
            if pr != number:
                log.warning(
                    "%s#%d: shares head %s with #%d, which changes %s/; leaving its check to the review",
                    repo,
                    number,
                    head_sha[:7],
                    pr,
                    gh.world_root,
                )
            gh.withdraw_pass(repo, head_sha, pr)
            return False
    root = gh.world_root
    gh.upsert_check(
        repo,
        head_sha,
        "success",
        f"Nothing under {root} changed",
        f"This pull request changes no file under `{root}/`, so there is nothing for Theseus to review.",
        source=NOTHING_CHANGED,
    )
    return True


def _review_again(gh: GitHub, repo: str, head_sha: str, numbers: list[int]) -> str:
    """Re-runs the review of the commit, and returns what `GitHub.rerun_review` did."""
    outcome = gh.rerun_review(repo, head_sha)
    if outcome == "rerun":
        gh.pending_check(repo, head_sha, *AGAIN)
    elif outcome == "none":
        for number in numbers:
            if _nothing_changed(gh, repo, number, head_sha):
                return outcome
        log.warning("%s@%s: no Theseus run to repeat", repo, head_sha[:7])
    return outcome


def _apply_by_comment(
    gh: GitHub, repo: str, number: int, candidate_id: str, user: str, fixing: Fixing
) -> None:
    """`/theseus apply <ID>`: commits the fix, or says why not, in a reply to the person who asked."""
    command = webhooks.command_for(candidate_id)
    try:
        applied = webhooks.apply_fix(
            gh, fixing.results, fixing.store, fixing.render, repo, number, candidate_id, user
        )
        text = webhooks.applied_reply(applied)
    except webhooks.NoReview as e:
        outcome = _review_again(gh, repo, e.sha, [number])
        text = webhooks.no_review(e.sha, outcome, candidate_id, gh.world_root)
    except webhooks.Refused as e:
        log.info("%s#%d: %s's %s refused: %s", repo, number, user, command, e)
        text = str(e)
    except GitHubError as e:
        log.error("%s#%d: %s failed: %s", repo, number, command, e)
        failed = f"Theseus could not commit the fix: {code(str(e)[:REASON_MAX])}. Comment again to retry."
        gh.reply(repo, number, webhooks.answer(command, user, failed))
        raise
    gh.reply(repo, number, webhooks.answer(command, user, text))


def _on_comment(gh: GitHub, repo: str, payload: dict[str, Any], fixing: Fixing) -> None:
    comment, issue = payload.get("comment") or {}, payload.get("issue") or {}
    if payload.get("action") != "created" or "pull_request" not in issue:
        return
    body = comment.get("body") or ""
    user = (comment.get("user") or {}).get("login", "")
    candidate_id = webhooks.apply_command(body)
    if candidate_id is not None:
        _apply_by_comment(gh, repo, int(issue["number"]), candidate_id, user, fixing)
        return
    if body.strip() != REVIEW_COMMAND:
        return
    if not gh.can_write(repo, user):
        log.info(
            "%s#%s: %s asked for a review without write access; ignored", repo, issue.get("number"), user
        )
        return
    number = int(issue["number"])
    head = gh.pull_request(repo, number)["head"]["sha"]
    _review_again(gh, repo, head, [number])


def _on_check_run(gh: GitHub, repo: str, payload: dict[str, Any]) -> None:
    check = payload.get("check_run") or {}
    if payload.get("action") != "rerequested" or check.get("name") != CHECK_NAME:
        return
    if str((check.get("app") or {}).get("id")) != gh.app_id:
        return
    numbers = [int(p["number"]) for p in check.get("pull_requests") or []]
    _review_again(gh, repo, check["head_sha"], numbers)


def _on_pull_request(gh: GitHub, repo: str, payload: dict[str, Any]) -> None:
    if payload.get("action") not in PR_ACTIONS:
        return
    pr = payload.get("pull_request") or {}
    number, head = int(pr["number"]), pr["head"]["sha"]
    if gh.touches_world_root(repo, number):
        # The Action is planning it now; the check says so until /analyze completes it.
        gh.pending_check(repo, head, *PLANNING)
        return
    _nothing_changed(gh, repo, number, head)


def _on_closed(store: reviews.ReviewStore, settings: Settings, repo: str, payload: dict[str, Any]) -> None:
    """A PR closed or merged: its base, head and fix graphs are deleted. Its review stays in the documents
    graph, so its page keeps its text and the dashboard its history; reopening it reviews it again and
    rebuilds the graphs. The event carries the number, so GitHub is not called."""
    number = int((payload.get("pull_request") or {})["number"])
    reviews.drop_graphs(store, settings.theseus_world_root, repo, number)


HANDLERS = {"check_run": _on_check_run, "pull_request": _on_pull_request}
EVENTS = frozenset({"issue_comment", *HANDLERS})


@router.post("/webhooks/github", status_code=204)
async def github_webhook(
    request: Request,
    settings: SettingsDep,
    gh: GitHubDep,
    results: ResultsDep,
    store: StoreDep,
    render: RenderDep,
    x_github_event: Annotated[str | None, Header()] = None,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> Response:
    """The App's events, checked against GITHUB_WEBHOOK_SECRET before anything is read: `/theseus apply <ID>`
    commits a fix that passed; `/theseus review` and Re-run on the check run the review again; a PR that
    changes the world root shows its check in progress while the Action plans it, and one that changes
    nothing there gets a `success` check; a PR that is closed has its graphs deleted and keeps its review.
    Every other event is accepted and ignored."""
    if settings.github_webhook_secret is None:
        raise HTTPException(503, "GITHUB_WEBHOOK_SECRET is not set on the server")
    body = await request.body()
    if not _signed(body, x_hub_signature_256, settings.github_webhook_secret.get_secret_value()):
        raise HTTPException(401, "bad webhook signature")
    if x_github_event not in EVENTS:
        return Response(status_code=204)
    payload = json.loads(body)
    repo = (payload.get("repository") or {}).get("full_name", "")
    _require_repo(gh, repo)
    try:
        # The handlers call GitHub synchronously, and applying a fix takes seconds: off the event loop, so
        # the next delivery is read meanwhile instead of GitHub giving up on it.
        if x_github_event == "issue_comment":
            await run_in_threadpool(_on_comment, gh, repo, payload, Fixing(results, store, render))
        elif x_github_event == "pull_request" and payload.get("action") == "closed":
            await run_in_threadpool(_on_closed, store, settings, repo, payload)
        else:
            await run_in_threadpool(HANDLERS[x_github_event], gh, repo, payload)
    except GitHubError as e:
        log.error("webhook %s for %s: %s", x_github_event, repo, e)
        raise HTTPException(502, str(e)) from e
    except GraphError as e:
        # The delivery fails, so it shows in GitHub's list and can be redelivered; `prune` also clears it.
        log.error("webhook %s for %s: %s", x_github_event, repo, e)
        raise HTTPException(502, "the graph store did not answer") from e
    return Response(status_code=204)
