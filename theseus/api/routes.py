"""The analysis routes and the App's webhook (docs/spec/05-contracts.md, "API"; 07-github-and-deploy.md).

A request from the Action runs the real review (A5) and posts it on the PR as the comment and the `Theseus`
check run. A `{fixture}` request still answers from that fixture's stub, for the Try-it page (S4).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from falkordb import FalkorDB
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from theseus.agent.labels import LABELS, labels_for
from theseus.agent.render import MARKER, annotations, code, render_comment, verdict
from theseus.api import reviews
from theseus.api.github import CHECK_NAME, NOTHING_CHANGED, GitHub
from theseus.api.stub import result_from_expected
from theseus.config import Settings, get_settings
from theseus.contracts.result import AnalysisResult
from theseus.errors import GitHubError, GraphError, TheseusError
from theseus.graph.client import server_version

log = logging.getLogger(__name__)
router = APIRouter()

# Paths are relative to the working directory: the repo root locally, /app in the image.
FIXTURES = Path("fixtures")
SAMPLE = Path("tests/data/stub_expected.json")
FIXTURE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REVIEW_COMMAND = "/theseus review"
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


class FindingRequest(BaseModel):
    fixture: str | None = None
    repo: str | None = None
    advisory: dict[str, Any] | None = None


class ScanRequest(BaseModel):
    fixture: str | None = None
    repo: str | None = None


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

# Finding mode on a fixture folder. `api/app.py` builds the real one; tests replace it.
Finder = Callable[[Path], AnalysisResult]


def get_finder(request: Request) -> Finder:
    finder = getattr(request.app.state, "finder", None)
    if finder is None:
        raise HTTPException(503, "the finding engine is not ready")
    return finder


FinderDep = Annotated[Finder, Depends(get_finder)]
FINDING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def get_store(request: Request) -> reviews.ReviewStore:
    """The store the graphs live in, for each review's page; `api/app.py` sets it at startup."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(503, "the graph store is not ready")
    return store


StoreDep = Annotated[reviews.ReviewStore, Depends(get_store)]


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


def stub_for(fixture: str | None, mode: str) -> AnalysisResult:
    if fixture is None:
        raise HTTPException(501, "only {fixture} requests are answered until the engine lands (E3, A5)")
    expected = load_expected(fixture)
    if expected.get("mode") != mode:
        raise HTTPException(400, f"fixture {fixture!r} is a {expected.get('mode')} scenario, not {mode}")
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
    falkordb: FalkorVersionDep,
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
        url = reviews.page_url(settings, req.repo, req.pr_number)
        comment = render_comment(
            result, req.repo, req.head_sha, req.checkov, settings.theseus_world_root, falkordb, url
        )
        status = verdict(result)
        notes = annotations(result, settings.theseus_world_root)
        gh.upsert_check(
            req.repo, req.head_sha, status.conclusion, status.title, card(comment), annotations=notes
        )
        if pr["head"]["sha"] == req.head_sha:
            # The page is kept first, so its link works the moment the comment shows it.
            shas = ((pr.get("base") or {}).get("sha") or "", req.head_sha)
            reviews.save(store, req.repo, req.pr_number, shas, settings.theseus_world_root, result)
            gh.upsert_comment(req.repo, req.pr_number, comment)
            gh.set_labels(req.repo, req.pr_number, labels_for(result), LABELS)
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
    return data


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
    return data


@router.post("/scan", response_model=AnalysisResult)
def scan(req: ScanRequest) -> AnalysisResult:
    """Scan mode."""
    return stub_for(req.fixture, "scan")


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


def _review_again(gh: GitHub, repo: str, head_sha: str, numbers: list[int]) -> None:
    outcome = gh.rerun_review(repo, head_sha)
    if outcome == "rerun":
        gh.pending_check(repo, head_sha, *AGAIN)
    elif outcome == "none":
        for number in numbers:
            if _nothing_changed(gh, repo, number, head_sha):
                return
        log.warning("%s@%s: no Theseus run to repeat", repo, head_sha[:7])


def _on_comment(gh: GitHub, repo: str, payload: dict[str, Any]) -> None:
    comment, issue = payload.get("comment") or {}, payload.get("issue") or {}
    if payload.get("action") != "created" or "pull_request" not in issue:
        return
    if (comment.get("body") or "").strip() != REVIEW_COMMAND:
        return
    user = (comment.get("user") or {}).get("login", "")
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


HANDLERS = {"issue_comment": _on_comment, "check_run": _on_check_run, "pull_request": _on_pull_request}


@router.post("/webhooks/github", status_code=204)
async def github_webhook(
    request: Request,
    settings: SettingsDep,
    gh: GitHubDep,
    x_github_event: Annotated[str | None, Header()] = None,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> Response:
    """The App's events, checked against GITHUB_WEBHOOK_SECRET before anything is read: `/theseus review` and
    Re-run on the check run the review again; a PR that changes the world root shows its check in progress
    while the Action plans it, and one that changes nothing there gets a `success` check. Every other event
    is accepted and ignored."""
    if settings.github_webhook_secret is None:
        raise HTTPException(503, "GITHUB_WEBHOOK_SECRET is not set on the server")
    body = await request.body()
    if not _signed(body, x_hub_signature_256, settings.github_webhook_secret.get_secret_value()):
        raise HTTPException(401, "bad webhook signature")
    handler = HANDLERS.get(x_github_event or "")
    if handler is None:
        return Response(status_code=204)
    payload = json.loads(body)
    repo = (payload.get("repository") or {}).get("full_name", "")
    _require_repo(gh, repo)
    try:
        handler(gh, repo, payload)
    except GitHubError as e:
        log.error("webhook %s for %s: %s", x_github_event, repo, e)
        raise HTTPException(502, str(e)) from e
    return Response(status_code=204)
