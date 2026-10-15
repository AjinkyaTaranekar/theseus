"""The analysis routes and the App's webhook (docs/spec/05-contracts.md, "API"; 07-github-and-deploy.md).

Until E3 and A5 the analysis is a stub: `{fixture}` answers from that fixture, and a request from the Action
answers with the sample result, posted on the PR as the comment and the `Theseus` check run.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel

from theseus.agent.render import MARKER, render_comment, verdict
from theseus.api.github import CHECK_NAME, GitHub
from theseus.api.stub import result_from_expected
from theseus.config import Settings, get_settings
from theseus.contracts.result import AnalysisResult
from theseus.errors import GitHubError

log = logging.getLogger(__name__)
router = APIRouter()

# Paths are relative to the working directory: the repo root locally, /app in the image.
FIXTURES = Path("fixtures")
SAMPLE = Path("tests/data/stub_expected.json")
FIXTURE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REVIEW_COMMAND = "/theseus review"
PR_ACTIONS = frozenset({"opened", "reopened", "synchronize", "edited"})


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
    """The comment's first section, for the check run's summary: everything before the folded details."""
    return comment.split("\n<details>", 1)[0].replace(MARKER, "", 1).strip()


def _secret_matches(given: str | None, secret: str) -> bool:
    return given is not None and hmac.compare_digest(given.encode(), secret.encode())


def _require_repo(gh: GitHub, repo: str) -> None:
    if not gh.allowed(repo):
        log.warning("refused %s: not in THESEUS_REPOS", repo)
        raise HTTPException(403, f"{repo} is not a repo Theseus acts on")


@router.post("/analyze", response_model=AnalysisResult)
def analyze(
    req: AnalyzeRequest,
    settings: SettingsDep,
    gh: GitHubDep,
    x_theseus_token: Annotated[str | None, Header()] = None,
) -> AnalysisResult:
    """PR mode. With a repo, from the Action: posts the comment and the `Theseus` check run on the PR."""
    if req.repo is None:
        return stub_for(req.fixture, "pr")
    if settings.theseus_token is None:
        raise HTTPException(503, "THESEUS_TOKEN is not set on the server")
    if not _secret_matches(x_theseus_token, settings.theseus_token.get_secret_value()):
        raise HTTPException(401, "missing or wrong X-Theseus-Token")
    if req.pr_number is None or req.head_sha is None:
        raise HTTPException(422, "a request with a repo needs pr_number and head_sha")
    _require_repo(gh, req.repo)
    result = stub_for(req.fixture or "sample", "pr")
    comment = render_comment(result, req.repo, req.head_sha, req.checkov, settings.theseus_world_root)
    status = verdict(result)
    try:
        # A review reads the PR as it is now, not the copy the Action's event carried (07, "When Theseus
        # reviews"). A5 reads its title and body from here; F7 needs only its head.
        pr = gh.pull_request(req.repo, req.pr_number)
        gh.upsert_check(req.repo, req.head_sha, status.conclusion, status.title, card(comment))
        if pr["head"]["sha"] == req.head_sha:
            gh.upsert_comment(req.repo, req.pr_number, comment)
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


@router.post("/finding", response_model=AnalysisResult)
def finding(req: FindingRequest) -> AnalysisResult:
    """Finding mode."""
    return stub_for(req.fixture, "finding")


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
    the ruleset requires. Returns whether it did."""
    if gh.touches_world_root(repo, number):
        return False
    root = gh.world_root
    gh.upsert_check(
        repo,
        head_sha,
        "success",
        f"Nothing under {root} changed",
        f"This pull request changes no file under `{root}/`, so there is nothing for Theseus to review.",
    )
    return True


def _review_again(gh: GitHub, repo: str, head_sha: str, numbers: list[int]) -> None:
    outcome = gh.rerun_review(repo, head_sha)
    if outcome == "none":
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
    _nothing_changed(gh, repo, int(pr["number"]), pr["head"]["sha"])


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
    Re-run on the check run the review again; a PR that changes nothing under the world root gets a `success`
    check. Every other event is accepted and ignored."""
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
