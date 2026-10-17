"""The Theseus Action, the App's GitHub calls and the webhook (docs/spec/07-github-and-deploy.md), against a
respx-mocked GitHub API: no test touches the network."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import jwt
import pytest
import respx
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from theseus.agent.render import MARKER
from theseus.api import routes
from theseus.api.app import create_app
from theseus.api.github import API, GitHub
from theseus.config import Settings
from theseus.errors import GitHubError
from theseus.graph.store import MemoryStore

REPO = "demo-org/theseus"
APP_ID = 123
INSTALLATION = 42
HEAD = "a" * 40
BASE = "b" * 40
NOW = 1_790_000_000.0
SECRET = "webhook-secret-not-real"
TOKEN = "theseus-token-not-real"
WORKFLOW = Path(".github/workflows/theseus.yml")
PUBLISH = Path(".github/workflows/theseus-publish.yml")


@pytest.fixture(scope="module")
def key_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path_factory.mktemp("app") / "theseus.private-key.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path


@pytest.fixture
def settings(key_file: Path) -> Settings:
    return Settings(
        _env_file=None,
        github_app_id=str(APP_ID),
        github_app_private_key_path=key_file,
        github_webhook_secret=SECRET,
        theseus_token=TOKEN,
        theseus_repos=REPO,
    )


class FakeGitHub:
    """The slice of GitHub's REST API the App uses, as respx routes over a little state."""

    def __init__(self) -> None:
        self.router = respx.Router(base_url=API, assert_all_called=False)
        self.comments: list[dict[str, Any]] = []
        self.checks: list[dict[str, Any]] = []
        self.reruns: list[int] = []
        self.files = ["demo-infra/terraform/people.tf"]
        # PR 8 is open only when a test adds it; it may share PR 7's head and target another base.
        self.files_8: list[str] = []
        self.open_prs: list[dict[str, Any]] = [{"number": 7, "head": {"sha": HEAD}}]
        self.permission = "write"
        self.runs: list[dict[str, Any]] = [{"id": 99, "status": "completed", "head_sha": HEAD}]
        self.head = HEAD
        self.token_calls = 0
        self.pr_labels: list[str] = []
        self.repo_labels: dict[str, dict[str, Any]] = {}
        r = self.router
        r.get(f"/repos/{REPO}/installation").mock(side_effect=self._installation)
        r.post(f"/app/installations/{INSTALLATION}/access_tokens").mock(side_effect=self._token)
        r.get(f"/repos/{REPO}/pulls/7").mock(side_effect=self._pull)
        r.get(f"/repos/{REPO}/pulls/7/files").mock(side_effect=self._files)
        r.get(f"/repos/{REPO}/pulls/8/files").mock(side_effect=self._files_8)
        r.get(f"/repos/{REPO}/pulls").mock(side_effect=self._open_pulls)
        r.get(f"/repos/{REPO}/issues/7/comments").mock(side_effect=self._list_comments)
        r.post(f"/repos/{REPO}/issues/7/comments").mock(side_effect=self._create_comment)
        r.patch(url__regex=rf"/repos/{REPO}/issues/comments/(?P<cid>\d+)$").mock(
            side_effect=self._edit_comment
        )
        r.get(url__regex=rf"/repos/{REPO}/commits/(?P<sha>\w+)/check-runs").mock(
            side_effect=self._list_checks
        )
        r.post(f"/repos/{REPO}/check-runs").mock(side_effect=self._create_check)
        r.patch(url__regex=rf"/repos/{REPO}/check-runs/(?P<cid>\d+)$").mock(side_effect=self._edit_check)
        r.get(f"/repos/{REPO}/actions/workflows/theseus.yml/runs").mock(side_effect=self._runs)
        r.post(url__regex=rf"/repos/{REPO}/actions/runs/(?P<rid>\d+)/rerun$").mock(side_effect=self._rerun)
        r.get(url__regex=rf"/repos/{REPO}/collaborators/(?P<user>[\w-]+)/permission$").mock(
            side_effect=self._permission
        )
        r.get(url__regex=rf"/repos/{REPO}/contents/(?P<path>[^?]+)").mock(side_effect=self._contents)
        r.get(f"/repos/{REPO}/issues/7/labels").mock(side_effect=self._list_pr_labels)
        r.post(f"/repos/{REPO}/issues/7/labels").mock(side_effect=self._add_pr_labels)
        r.delete(url__regex=rf"/repos/{REPO}/issues/7/labels/(?P<name>[^?]+)$").mock(
            side_effect=self._remove_pr_label
        )
        r.get(f"/repos/{REPO}/labels").mock(side_effect=self._list_repo_labels)
        r.post(f"/repos/{REPO}/labels").mock(side_effect=self._create_repo_label)

    # Auth -------------------------------------------------------------------------------------------------

    def _installation(self, request: httpx.Request) -> httpx.Response:
        claims = jwt.decode(
            request.headers["Authorization"].removeprefix("Bearer "), options={"verify_signature": False}
        )
        assert claims["iss"] == str(APP_ID) and claims["exp"] - claims["iat"] <= 600
        return httpx.Response(200, json={"id": INSTALLATION})

    def _token(self, request: httpx.Request) -> httpx.Response:
        self.token_calls += 1
        return httpx.Response(201, json={"token": "ghs_installation", "expires_at": "2026-09-21T15:00:00Z"})

    @staticmethod
    def _authed(request: httpx.Request) -> None:
        assert request.headers["Authorization"] == "Bearer ghs_installation"

    # Pull requests ----------------------------------------------------------------------------------------

    def _pull(self, request: httpx.Request) -> httpx.Response:
        self._authed(request)
        return httpx.Response(200, json={"number": 7, "title": "t", "body": "b", "head": {"sha": self.head}})

    def _files(self, request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        rows = [{"filename": f} for f in self.files] if page == 1 else []
        return httpx.Response(200, json=rows)

    def _files_8(self, request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=[{"filename": f} for f in self.files_8] if page == 1 else [])

    def _open_pulls(self, request: httpx.Request) -> httpx.Response:
        assert request.url.params["state"] == "open"
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=self.open_prs if page == 1 else [])

    def _list_comments(self, request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=self.comments if page == 1 else [])

    def _create_comment(self, request: httpx.Request) -> httpx.Response:
        self._authed(request)
        comment = {
            "id": 1000 + len(self.comments),
            "body": json.loads(request.content)["body"],
            "performed_via_github_app": {"id": APP_ID},
        }
        self.comments.append(comment)
        return httpx.Response(201, json=comment)

    def _edit_comment(self, request: httpx.Request, cid: str) -> httpx.Response:
        comment = next(c for c in self.comments if c["id"] == int(cid))
        comment["body"] = json.loads(request.content)["body"]
        return httpx.Response(200, json=comment)

    # Checks -----------------------------------------------------------------------------------------------

    def _list_checks(self, request: httpx.Request, sha: str) -> httpx.Response:
        assert request.url.params["check_name"] == "Theseus"
        assert request.url.params["app_id"] == str(APP_ID)
        runs = [c for c in self.checks if c["head_sha"] == sha]
        return httpx.Response(200, json={"total_count": len(runs), "check_runs": runs})

    def _create_check(self, request: httpx.Request) -> httpx.Response:
        check = {"id": 500 + len(self.checks), **json.loads(request.content)}
        self.checks.append(check)
        return httpx.Response(201, json=check)

    def _edit_check(self, request: httpx.Request, cid: str) -> httpx.Response:
        check = next(c for c in self.checks if c["id"] == int(cid))
        check.update(json.loads(request.content))
        return httpx.Response(200, json=check)

    # Workflow runs and permissions ------------------------------------------------------------------------

    def _runs(self, request: httpx.Request) -> httpx.Response:
        sha = request.url.params["head_sha"]
        runs = [r for r in self.runs if r["head_sha"] == sha]
        return httpx.Response(200, json={"total_count": len(runs), "workflow_runs": runs})

    def _rerun(self, request: httpx.Request, rid: str) -> httpx.Response:
        self.reruns.append(int(rid))
        return httpx.Response(201)

    def _permission(self, request: httpx.Request, user: str) -> httpx.Response:
        return httpx.Response(200, json={"permission": self.permission, "user": {"login": user}})

    def _contents(self, request: httpx.Request, path: str) -> httpx.Response:
        assert request.url.params["ref"] == HEAD
        assert request.headers["Accept"] == "application/vnd.github.raw+json"
        return httpx.Response(200, text=f"# {path}\n")

    # Labels -----------------------------------------------------------------------------------------------

    def _list_pr_labels(self, request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=[{"name": n} for n in self.pr_labels] if page == 1 else [])

    def _add_pr_labels(self, request: httpx.Request) -> httpx.Response:
        for name in json.loads(request.content)["labels"]:
            assert name in self.repo_labels, f"{name} added before it was created"
            self.pr_labels.append(name)
        return httpx.Response(200, json=[{"name": n} for n in self.pr_labels])

    def _remove_pr_label(self, request: httpx.Request, name: str) -> httpx.Response:
        self.pr_labels.remove(unquote(name))
        return httpx.Response(200, json=[])

    def _list_repo_labels(self, request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=list(self.repo_labels.values()) if page == 1 else [])

    def _create_repo_label(self, request: httpx.Request) -> httpx.Response:
        label = json.loads(request.content)
        self.repo_labels[label["name"]] = label
        return httpx.Response(201, json=label)

    @property
    def calls(self) -> int:
        return len(self.router.calls)


@pytest.fixture
def fake() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def gh(settings: Settings, fake: FakeGitHub) -> GitHub:
    client = httpx.Client(base_url=API, transport=httpx.MockTransport(fake.router.handler))
    return GitHub(settings, client=client, clock=lambda: NOW)


class SampleReview:
    """The review step, answering with the sample result and recording each call: these tests are about
    GitHub, so the real review (tests/e2e/test_analyze_route.py) stays out of them."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.error: Exception | None = None
        # `seen` reads GitHub's state while the review runs; `state` keeps what it read.
        self.seen: Callable[[], Any] | None = None
        self.state: Any = None

    def __call__(self, gh: GitHub, *args: Any) -> Any:
        self.calls.append(args)
        if self.seen is not None:
            self.state = self.seen()
        if self.error is not None:
            raise self.error
        return routes.stub_for("sample", "pr")


@pytest.fixture
def review() -> SampleReview:
    return SampleReview()


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def client(settings: Settings, gh: GitHub, review: SampleReview, store: MemoryStore) -> Iterator[TestClient]:
    app = create_app(connect=lambda: object())
    app.dependency_overrides[routes.get_settings] = lambda: settings
    app.dependency_overrides[routes.get_github] = lambda: gh
    app.dependency_overrides[routes.get_review] = lambda: review
    app.dependency_overrides[routes.get_store] = lambda: store
    with TestClient(app) as c:
        yield c


def analyze_body(**extra: Any) -> dict[str, Any]:
    return {
        "repo": REPO,
        "pr_number": 7,
        "base_sha": BASE,
        "head_sha": HEAD,
        "pr_title": "Add Priya to support-engineers",
        "pr_body": "She reads logs.",
        "base_plan": {},
        "head_plan": {},
        "checkov": {"passed": 228, "failed": 81, "skipped": 0, "checkov_version": "3.3.29"},
        **extra,
    }


def analyze(client: TestClient, token: str | None = TOKEN, **extra: Any) -> httpx.Response:
    headers = {"X-Theseus-Token": token} if token is not None else {}
    return client.post("/analyze", json=analyze_body(**extra), headers=headers)


def webhook(client: TestClient, event: str, payload: dict[str, Any], secret: str = SECRET) -> httpx.Response:
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-GitHub-Event": event, "X-Hub-Signature-256": signature, "Content-Type": "application/json"}
    return client.post("/webhooks/github", content=body, headers=headers)


# The App's calls --------------------------------------------------------------------------------------------


def test_the_app_jwt_is_short_lived_and_signed_with_the_app_key(gh: GitHub, key_file: Path) -> None:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    public = load_pem_private_key(key_file.read_bytes(), password=None).public_key()
    claims = jwt.decode(gh.app_jwt(), public, algorithms=["RS256"], options={"verify_exp": False})
    assert claims == {"iss": str(APP_ID), "iat": int(NOW) - 60, "exp": int(NOW) + 540}


def test_the_installation_token_is_cached_until_near_expiry(gh: GitHub, fake: FakeGitHub) -> None:
    assert gh.installation_token(REPO) == "ghs_installation"
    assert gh.installation_token(REPO) == "ghs_installation"
    assert fake.token_calls == 1


def test_a_repo_outside_theseus_repos_is_refused_before_any_request(gh: GitHub, fake: FakeGitHub) -> None:
    with pytest.raises(GitHubError, match="THESEUS_REPOS"):
        gh.upsert_comment("someone/else", 7, "hi")
    assert fake.calls == 0


def test_files_are_read_at_a_sha_and_only_under_the_world_root(gh: GitHub) -> None:
    assert gh.read_file(REPO, "demo-infra/terraform/people.tf", HEAD) == "# demo-infra/terraform/people.tf\n"
    for path in ("theseus/config.py", "demo-infra/../.env", "demo-infra-old/x.tf"):
        with pytest.raises(GitHubError, match="world root"):
            gh.read_file(REPO, path, HEAD)


def test_a_github_error_names_the_method_path_and_status(gh: GitHub, fake: FakeGitHub) -> None:
    fake.router.get(f"/repos/{REPO}/pulls/8").respond(404, json={"message": "Not Found"})
    with pytest.raises(GitHubError, match=r"GET /repos/demo-org/theseus/pulls/8: 404 Not Found"):
        gh.pull_request(REPO, 8)


def test_only_the_app_s_own_comment_is_edited(gh: GitHub, fake: FakeGitHub) -> None:
    """Someone pasting the marker into their own comment does not make Theseus edit it."""
    fake.comments.append({"id": 1, "body": f"{MARKER}\nfake", "performed_via_github_app": None})
    cid = gh.upsert_comment(REPO, 7, f"{MARKER}\nreal")
    assert cid != 1 and fake.comments[0]["body"] == f"{MARKER}\nfake"


# /analyze from the Action -----------------------------------------------------------------------------------


def test_the_comment_is_created_once_and_then_edited(client: TestClient, fake: FakeGitHub) -> None:
    assert analyze(client).status_code == 200
    assert analyze(client).status_code == 200
    [comment] = fake.comments
    assert comment["body"].startswith(MARKER)
    assert "Merge blocked" in comment["body"]


def test_the_check_run_carries_the_verdict_and_an_opened_path_fails_it(
    client: TestClient, fake: FakeGitHub
) -> None:
    res = analyze(client)
    assert res.status_code == 200 and res.json()["opened"]
    [check] = fake.checks
    assert (check["name"], check["head_sha"], check["status"], check["conclusion"]) == (
        "Theseus",
        HEAD,
        "completed",
        "failure",
    )
    assert check["output"]["title"].startswith("Merge blocked: ")
    summary = check["output"]["summary"]
    assert "Merge blocked" in summary and "<details>" not in summary and MARKER not in summary
    assert "```mermaid" not in summary  # the Checks tab draws no diagrams


def test_the_review_gets_the_pr_as_the_api_has_it_and_the_action_s_plans(
    client: TestClient, review: SampleReview
) -> None:
    """The title and body come from the API, never from the request (07, "When Theseus reviews")."""
    assert analyze(client, pr_title="stale", base_plan={"b": 1}, head_plan={"h": 1}).status_code == 200
    ((repo, number, head, pr, base_plan, head_plan),) = review.calls
    assert (repo, number, head) == (REPO, 7, HEAD)
    assert (pr["title"], pr["body"]) == ("t", "b") and (base_plan, head_plan) == ({"b": 1}, {"h": 1})


@pytest.mark.parametrize("missing", ["base_plan", "head_plan"])
def test_a_review_needs_both_plans(client: TestClient, review: SampleReview, missing: str) -> None:
    assert analyze(client, **{missing: None}).status_code == 422
    assert review.calls == []


def test_a_review_shows_it_is_tracing_paths_then_completes_the_same_check(
    client: TestClient, fake: FakeGitHub, review: SampleReview
) -> None:
    review.seen = lambda: [(c["status"], c["output"]["title"]) for c in fake.checks]
    assert analyze(client).status_code == 200
    assert review.state == [("in_progress", "Reviewing: tracing paths in FalkorDB")]
    [check] = fake.checks
    assert (check["status"], check["conclusion"]) == ("completed", "failure")


def test_a_second_review_of_a_commit_keeps_the_first_verdict_in_the_history(
    client: TestClient, fake: FakeGitHub
) -> None:
    assert analyze(client).status_code == 200
    assert analyze(client).status_code == 200
    assert [(c["status"], c["conclusion"]) for c in fake.checks] == [("completed", "failure")] * 2


def test_a_review_that_cannot_finish_fails_the_check_with_its_reason(
    client: TestClient, fake: FakeGitHub, review: SampleReview
) -> None:
    """It fails closed and says why: the merge waits for a review that finishes, and the PR shows the
    reason and how to try again."""
    from theseus.errors import IngestError

    review.error = IngestError("no theseus.yaml at the head")
    res = analyze(client)
    assert res.status_code == 500 and "no theseus.yaml" in res.json()["detail"]
    [check] = fake.checks
    assert (check["status"], check["conclusion"]) == ("completed", "failure")
    assert check["output"]["title"] == "Review could not finish"
    summary = check["output"]["summary"]
    assert "`no theseus.yaml at the head`" in summary and "/theseus review" in summary
    assert fake.comments == []


def test_a_stale_run_updates_its_own_check_but_not_the_comment(client: TestClient, fake: FakeGitHub) -> None:
    """A re-run of an old commit must not overwrite the comment a newer push wrote."""
    fake.head = "c" * 40
    assert analyze(client).status_code == 200
    assert fake.comments == [] and [c["head_sha"] for c in fake.checks] == [HEAD]


@pytest.mark.parametrize("token", [None, "wrong", ""])
def test_a_missing_or_wrong_token_is_refused(client: TestClient, fake: FakeGitHub, token: str | None) -> None:
    assert analyze(client, token=token).status_code == 401
    assert fake.calls == 0


def test_analyze_for_a_repo_outside_theseus_repos_is_refused(client: TestClient, fake: FakeGitHub) -> None:
    assert analyze(client, repo="someone/else").status_code == 403
    assert fake.calls == 0


def test_a_fixture_request_needs_no_token_and_calls_no_github(client: TestClient, fake: FakeGitHub) -> None:
    res = client.post("/analyze", json={"fixture": "sample"})
    assert res.status_code == 200 and fake.calls == 0


# The webhook ------------------------------------------------------------------------------------------------


def review_comment(body: str = "/theseus review", user: str = "sam") -> dict[str, Any]:
    return {
        "action": "created",
        "repository": {"full_name": REPO},
        "issue": {"number": 7, "pull_request": {"url": "x"}},
        "comment": {"body": body, "user": {"login": user}},
    }


def test_theseus_review_reruns_the_latest_workflow_run_for_the_head(
    client: TestClient, fake: FakeGitHub
) -> None:
    assert webhook(client, "issue_comment", review_comment()).status_code == 204
    assert fake.reruns == [99]


def test_theseus_review_from_someone_without_write_access_does_nothing(
    client: TestClient, fake: FakeGitHub
) -> None:
    fake.permission = "read"
    assert webhook(client, "issue_comment", review_comment()).status_code == 204
    assert fake.reruns == []


def test_other_comments_are_ignored(client: TestClient, fake: FakeGitHub) -> None:
    for body in ("/theseus reviewed", "please /theseus review", "LGTM"):
        assert webhook(client, "issue_comment", review_comment(body)).status_code == 204
    assert fake.calls == 0


def test_a_running_review_is_not_started_twice(client: TestClient, fake: FakeGitHub) -> None:
    fake.runs[0]["status"] = "in_progress"
    assert webhook(client, "issue_comment", review_comment()).status_code == 204
    assert fake.reruns == []


def rerequested(name: str = "Theseus", app_id: int = APP_ID) -> dict[str, Any]:
    return {
        "action": "rerequested",
        "repository": {"full_name": REPO},
        "check_run": {
            "name": name,
            "head_sha": HEAD,
            "app": {"id": app_id},
            "pull_requests": [{"number": 7}],
        },
    }


def test_rerunning_the_check_reruns_the_review(client: TestClient, fake: FakeGitHub) -> None:
    assert webhook(client, "check_run", rerequested()).status_code == 204
    assert fake.reruns == [99]


def test_rerunning_someone_else_s_check_does_nothing(client: TestClient, fake: FakeGitHub) -> None:
    assert webhook(client, "check_run", rerequested(app_id=7)).status_code == 204
    assert webhook(client, "check_run", rerequested(name="CI")).status_code == 204
    assert fake.reruns == []


def pull_request(action: str = "opened") -> dict[str, Any]:
    return {
        "action": action,
        "repository": {"full_name": REPO},
        "number": 7,
        "pull_request": {"number": 7, "head": {"sha": HEAD}},
    }


def test_a_pr_outside_the_world_root_gets_a_success_check(client: TestClient, fake: FakeGitHub) -> None:
    fake.files = ["README.md", "theseus/api/routes.py"]
    assert webhook(client, "pull_request", pull_request()).status_code == 204
    [check] = fake.checks
    assert (check["conclusion"], check["output"]["title"]) == ("success", "Nothing under demo-infra changed")


def test_a_pr_sharing_its_head_never_passes_a_failing_review(client: TestClient, fake: FakeGitHub) -> None:
    """PR 8 opens PR 7's head against a base where nothing under the world root differs. The check belongs
    to the commit, so PR 8 must not replace PR 7's failing review with a pass."""
    fake.files = ["demo-infra/terraform/people.tf"]
    fake.files_8 = ["README.md"]
    fake.open_prs.append({"number": 8, "head": {"sha": HEAD}})
    fake.checks.append(
        {"id": 500, "name": "Theseus", "head_sha": HEAD, "status": "completed", "conclusion": "failure"}
    )
    event = {**pull_request(), "number": 8, "pull_request": {"number": 8, "head": {"sha": HEAD}}}
    assert webhook(client, "pull_request", event).status_code == 204
    assert [(c["id"], c["conclusion"]) for c in fake.checks] == [(500, "failure")]


def test_a_pass_is_withdrawn_when_a_pr_with_its_head_needs_a_review(
    client: TestClient, fake: FakeGitHub
) -> None:
    """PR 7 changes nothing under the world root and gets its pass. PR 8 then opens the same head against a
    base where the world root differs. The pass must not stand for PR 8: the newest check goes back to in
    progress until a review completes it, so a review that never finishes never reads as green."""
    fake.files = ["README.md"]
    assert webhook(client, "pull_request", pull_request()).status_code == 204
    [passed] = fake.checks
    assert (passed["conclusion"], passed["external_id"]) == ("success", "nothing-changed")

    fake.files_8 = ["demo-infra/terraform/people.tf"]
    fake.open_prs.append({"number": 8, "head": {"sha": HEAD}})
    event = {**pull_request(), "number": 8, "pull_request": {"number": 8, "head": {"sha": HEAD}}}
    assert webhook(client, "pull_request", event).status_code == 204
    newest = max(fake.checks, key=lambda c: c["id"])
    assert (newest["status"], newest.get("conclusion")) == ("in_progress", None)
    assert newest["output"]["title"] == "Reviewing: planning both commits"

    # Another event for PR 7 does not bring the pass back while PR 8 needs its review.
    assert webhook(client, "pull_request", pull_request("synchronize")).status_code == 204
    assert max(fake.checks, key=lambda c: c["id"])["status"] == "in_progress" and len(fake.checks) == 2

    # The review completes that same pending check with its verdict.
    assert analyze(client).status_code == 200
    assert len(fake.checks) == 2
    done = max(fake.checks, key=lambda c: c["id"])
    assert (done["status"], done["external_id"]) == ("completed", "review")


def test_a_review_s_verdict_is_never_withdrawn(client: TestClient, fake: FakeGitHub) -> None:
    fake.files, fake.files_8 = ["README.md"], ["demo-infra/terraform/people.tf"]
    fake.open_prs.append({"number": 8, "head": {"sha": HEAD}})
    fake.checks.append(
        {
            "id": 500,
            "name": "Theseus",
            "head_sha": HEAD,
            "status": "completed",
            "conclusion": "success",
            "external_id": "review",
            "output": {"title": "No dangerous path opened"},
        }
    )
    assert webhook(client, "pull_request", pull_request()).status_code == 204
    assert [(c["id"], c["conclusion"]) for c in fake.checks] == [(500, "success")]


def test_a_pr_alone_on_its_head_still_gets_its_pass(client: TestClient, fake: FakeGitHub) -> None:
    fake.files = ["README.md"]
    fake.files_8 = ["docs/x.md"]
    fake.open_prs.append({"number": 8, "head": {"sha": "c" * 40}})
    assert webhook(client, "pull_request", pull_request()).status_code == 204
    [check] = fake.checks
    assert check["conclusion"] == "success"


@pytest.mark.parametrize("action", ["opened", "synchronize", "reopened", "edited"])
def test_a_pr_inside_the_world_root_shows_its_review_in_progress_at_once(
    client: TestClient, fake: FakeGitHub, action: str
) -> None:
    """The Action is planning both commits now; the required check says so, and the merge waits."""
    fake.files = ["README.md", "demo-infra/terraform/people.tf"]
    assert webhook(client, "pull_request", pull_request(action)).status_code == 204
    [check] = fake.checks
    assert (check["head_sha"], check["status"], check["external_id"]) == (HEAD, "in_progress", "review")
    assert check["output"]["title"] == "Reviewing: planning both commits"
    assert "merge waits" in check["output"]["summary"] and "FalkorDB" in check["output"]["summary"]


def test_another_event_while_a_review_runs_keeps_one_check(client: TestClient, fake: FakeGitHub) -> None:
    assert webhook(client, "pull_request", pull_request("opened")).status_code == 204
    assert webhook(client, "pull_request", pull_request("edited")).status_code == 204
    assert [c["status"] for c in fake.checks] == ["in_progress"]


def test_a_pr_inside_the_world_root_replaces_no_verdict_in_place(
    client: TestClient, fake: FakeGitHub
) -> None:
    """An edit re-runs the review: a new check shows it in progress, and the earlier verdict stays in the
    commit's history."""
    fake.checks.append(
        {"id": 500, "name": "Theseus", "head_sha": HEAD, "status": "completed", "conclusion": "failure"}
    )
    assert webhook(client, "pull_request", pull_request("edited")).status_code == 204
    assert [(c["id"], c["status"]) for c in fake.checks] == [(500, "completed"), (501, "in_progress")]


def test_reviewing_again_shows_the_check_in_progress(client: TestClient, fake: FakeGitHub) -> None:
    fake.checks.append(
        {"id": 500, "name": "Theseus", "head_sha": HEAD, "status": "completed", "conclusion": "failure"}
    )
    assert webhook(client, "issue_comment", review_comment()).status_code == 204
    assert fake.reruns == [99]
    newest = max(fake.checks, key=lambda c: c["id"])
    assert (newest["status"], newest["output"]["title"]) == (
        "in_progress",
        "Reviewing again: planning both commits",
    )


def review_failed(client: TestClient, token: str | None = TOKEN, **extra: Any) -> httpx.Response:
    headers = {"X-Theseus-Token": token} if token is not None else {}
    run = f"https://github.com/{REPO}/actions/runs/123"
    body = {"repo": REPO, "head_sha": HEAD, "run_url": run, **extra}
    return client.post("/review-failed", json=body, headers=headers)


def test_a_failed_workflow_fails_the_pending_check_with_a_link_to_its_run(
    client: TestClient, fake: FakeGitHub
) -> None:
    assert webhook(client, "pull_request", pull_request()).status_code == 204
    assert review_failed(client).status_code == 204
    [check] = fake.checks
    assert (check["status"], check["conclusion"]) == ("completed", "failure")
    assert check["output"]["title"] == "Review could not run"
    assert f"[See the run](https://github.com/{REPO}/actions/runs/123)" in check["output"]["summary"]


def test_a_failed_workflow_leaves_a_verdict_already_on_the_commit(
    client: TestClient, fake: FakeGitHub
) -> None:
    assert analyze(client).status_code == 200
    assert review_failed(client).status_code == 204
    [check] = fake.checks
    assert check["output"]["title"].startswith("Merge blocked")


@pytest.mark.parametrize(
    "url", ["https://evil.example/actions/runs/1", f"https://github.com/{REPO}/pulls/1", "javascript:x"]
)
def test_a_failed_workflow_links_only_to_a_run_of_this_repo(
    client: TestClient, fake: FakeGitHub, url: str
) -> None:
    assert review_failed(client, run_url=url).status_code == 204
    [check] = fake.checks
    assert "See the run" not in check["output"]["summary"] and url not in check["output"]["summary"]


@pytest.mark.parametrize("token", [None, "wrong"])
def test_review_failed_needs_the_token(client: TestClient, fake: FakeGitHub, token: str | None) -> None:
    assert review_failed(client, token=token).status_code == 401
    assert fake.calls == 0


def test_rerunning_the_check_of_a_pr_outside_the_world_root_posts_it_again(
    client: TestClient, fake: FakeGitHub
) -> None:
    fake.files, fake.runs = ["README.md"], []
    assert webhook(client, "check_run", rerequested()).status_code == 204
    assert [c["conclusion"] for c in fake.checks] == ["success"]


def test_a_bad_signature_is_refused_and_nothing_is_called(client: TestClient, fake: FakeGitHub) -> None:
    assert webhook(client, "issue_comment", review_comment(), secret="wrong").status_code == 401
    res = client.post("/webhooks/github", content=b"{}", headers={"X-GitHub-Event": "ping"})
    assert res.status_code == 401
    assert fake.calls == 0


def test_a_webhook_from_a_repo_outside_theseus_repos_is_refused(client: TestClient, fake: FakeGitHub) -> None:
    payload = {**review_comment(), "repository": {"full_name": "someone/else"}}
    assert webhook(client, "issue_comment", payload).status_code == 403
    assert fake.calls == 0


def test_other_events_are_accepted_and_ignored(client: TestClient, fake: FakeGitHub) -> None:
    assert webhook(client, "ping", {"zen": "Keep it logically awesome."}).status_code == 204
    assert (
        webhook(client, "push", {"repository": {"full_name": REPO}, "ref": "refs/heads/main"}).status_code
        == 204
    )
    assert webhook(client, "pull_request", pull_request("closed")).status_code == 204
    assert fake.calls == 0


# The Action -------------------------------------------------------------------------------------------------
# Two workflows: `Theseus` plans the PR's own Terraform, so it is untrusted and holds no secrets; `Theseus
# publish` runs from main's copy when it finishes, holds the token, and never runs PR code.


@pytest.fixture(scope="module")
def workflow() -> dict[Any, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def publish() -> dict[Any, Any]:
    return yaml.safe_load(PUBLISH.read_text(encoding="utf-8"))


def steps_of(flow: dict[Any, Any]) -> list[dict[str, Any]]:
    return [s for job in flow["jobs"].values() for s in job["steps"]]


def test_the_action_runs_only_for_pull_requests_touching_the_world_root(workflow: dict[Any, Any]) -> None:
    on = workflow[True]  # YAML 1.1 reads the key `on` as True
    assert list(on) == ["pull_request"]
    assert on["pull_request"]["types"] == ["opened", "synchronize", "reopened", "edited"]
    assert on["pull_request"]["paths"] == ["demo-infra/**"]


def test_the_action_runs_once_per_pr_with_read_only_permissions(workflow: dict[Any, Any]) -> None:
    assert workflow["concurrency"] == {
        "group": "theseus-${{ github.event.pull_request.number }}",
        "cancel-in-progress": True,
    }
    assert workflow["permissions"] == {"contents": "read"}


def test_the_run_that_plans_pr_terraform_holds_no_secret_and_sends_nothing() -> None:
    """Terraform plans the PR's own files, and a `data "external"` block runs during the plan. Anything it
    plants (GITHUB_ENV, BASH_ENV, files) stays in a run with no secret and no way to reach the backend."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for needle in ("secrets.", "THESEUS_TOKEN", "THESEUS_URL", "/analyze", "curl"):
        assert needle not in text, needle


def test_the_action_plans_both_sides_runs_checkov_and_uploads_data(workflow: dict[Any, Any]) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    steps = steps_of(workflow)
    setup = next(s for s in steps if s.get("uses", "").startswith("hashicorp/setup-terraform"))
    assert setup["with"]["terraform_version"] == "1.16.6"
    checkout = [s for s in steps if s.get("uses", "").startswith("actions/checkout")]
    assert [c["with"].get("path") for c in checkout] == [None, "base"]
    assert all(c["with"]["persist-credentials"] is False for c in checkout)
    for needle in ("terraform show -json", "checkov==3.3.29", "jq -n"):
        assert needle in text, needle
    upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact"))
    assert (upload["with"]["name"], upload["with"]["path"]) == ("theseus-review", "review.json")


def test_the_publisher_runs_from_main_after_the_action_and_only_for_its_successes(
    publish: dict[Any, Any],
) -> None:
    assert publish[True] == {"workflow_run": {"workflows": ["Theseus"], "types": ["completed"]}}
    assert publish["permissions"] == {"actions": "read", "contents": "read"}
    assert list(publish["jobs"]) == ["publish", "failed"]
    job = publish["jobs"]["publish"]
    assert "workflow_run.event == 'pull_request'" in job["if"]
    assert "workflow_run.conclusion == 'success'" in job["if"]


def test_a_failed_run_is_reported_so_the_check_never_hangs(publish: dict[Any, Any]) -> None:
    """A cancelled run is left alone: a newer push cancelled it, and that push's own run reviews."""
    job = publish["jobs"]["failed"]
    assert "workflow_run.event == 'pull_request'" in job["if"]
    assert "conclusion == 'failure'" in job["if"] and "conclusion == 'timed_out'" in job["if"]
    assert "cancelled" not in job["if"]
    [step] = job["steps"]
    assert step["env"]["HEAD_SHA"] == "${{ github.event.workflow_run.head_sha }}"
    assert step["env"]["RUN_URL"] == "${{ github.event.workflow_run.html_url }}"
    assert "/review-failed" in step["run"] and "X-Theseus-Token" in step["run"]


def test_the_publisher_never_runs_pr_code_and_takes_the_commit_from_its_event(
    publish: dict[Any, Any],
) -> None:
    steps = steps_of(publish)
    assert not any(s.get("uses", "").startswith("actions/checkout") for s in steps)
    download = next(s for s in steps if s.get("uses", "").startswith("actions/download-artifact"))
    assert download["with"]["run-id"] == "${{ github.event.workflow_run.id }}"
    send = next(s for s in publish["jobs"]["publish"]["steps"] if "run" in s)
    assert send["env"]["HEAD_SHA"] == "${{ github.event.workflow_run.head_sha }}"
    assert send["env"]["THESEUS_TOKEN"] == "${{ secrets.THESEUS_TOKEN }}"
    run = send["run"]
    for needle in ("stat -c %s", "jq -e", "-L", "/analyze", "X-Theseus-Token", '--arg head_sha "$HEAD_SHA"'):
        assert needle in run, needle
    assert "head_sha: .head_sha" not in run  # never the artifact's commit


def test_no_run_step_interpolates_an_expression(workflow: dict[Any, Any], publish: dict[Any, Any]) -> None:
    """Values reach the shell as data, through env:, never as ${{ }} inside a run: script."""
    for flow in (workflow, publish):
        runs = [s["run"] for s in steps_of(flow) if "run" in s]
        assert runs and all("${{" not in run for run in runs)


def test_every_action_is_pinned_to_a_version(workflow: dict[Any, Any], publish: dict[Any, Any]) -> None:
    uses = [s["uses"] for flow in (workflow, publish) for s in steps_of(flow) if "uses" in s]
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@v\d+(\.\d+)*", u) for u in uses), uses


MAIN = Path(".github/workflows/theseus-main.yml")


@pytest.fixture(scope="module")
def main_flow() -> dict[Any, Any]:
    return yaml.safe_load(MAIN.read_text(encoding="utf-8"))


def test_main_is_scanned_on_a_push_every_night_and_on_demand_never_for_a_pr(
    main_flow: dict[Any, Any],
) -> None:
    on = main_flow[True]
    assert on["push"] == {"branches": ["main"], "paths": ["demo-infra/**"]}
    assert on["schedule"] == [{"cron": "17 3 * * *"}] and "workflow_dispatch" in on
    assert "pull_request" not in on and "pull_request_target" not in on
    assert main_flow["permissions"] == {"contents": "read"}


def test_main_s_posture_is_sent_with_its_own_commit_and_event(main_flow: dict[Any, Any]) -> None:
    steps = steps_of(main_flow)
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"] == {"persist-credentials": False}
    send = next(s for s in steps if "/posture" in s.get("run", ""))
    assert send["env"]["SHA"] == "${{ github.sha }}" and send["env"]["TRIGGER"] == "${{ github.event_name }}"
    assert send["env"]["THESEUS_TOKEN"] == "${{ secrets.THESEUS_TOKEN }}"
    assert all("${{" not in s["run"] for s in steps if "run" in s)
    assert all(re.fullmatch(r"[\w.-]+/[\w.-]+@v\d+(\.\d+)*", s["uses"]) for s in steps if "uses" in s)
    # Only the steps that send hold the token.
    assert [s.get("name") for s in steps if "secrets." in json.dumps(s)] == [
        "Send main to Theseus",
        "Check the providers' status feeds",
    ]


def test_the_status_feeds_are_checked_nightly_and_on_demand_not_on_a_push(main_flow: dict[Any, Any]) -> None:
    check = next(s for s in steps_of(main_flow) if "/incidents/check" in s.get("run", ""))
    assert check["if"] == "github.event_name != 'push'"
    assert check["env"]["TRIGGER"] == "${{ github.event_name }}" and "${{" not in check["run"]


def test_the_app_manifest_asks_for_what_spec_07_lists() -> None:
    manifest = json.loads(Path("deploy/github-app-manifest.json").read_text(encoding="utf-8"))
    assert manifest["default_permissions"] == {
        "actions": "write",
        "checks": "write",
        "contents": "write",
        "issues": "write",
        "metadata": "read",
        "pull_requests": "write",
    }
    assert sorted(manifest["default_events"]) == ["check_run", "issue_comment", "pull_request", "push"]
    assert manifest["hook_attributes"]["url"] == "https://<DOMAIN>/webhooks/github"
    assert manifest["public"] is False


# Labels -----------------------------------------------------------------------------------------------------


def test_labels_change_only_theseus_s_own_and_are_created_with_their_colour(
    gh: GitHub, fake: FakeGitHub
) -> None:
    from theseus.agent.labels import LABELS, SEVERITY, VERDICT

    fake.pr_labels = ["demo", "theseus: S6", "someone's label"]
    fake.repo_labels = {
        n: {"name": n} for n in ("demo", "theseus: S6", "someone's label", "theseus: blocked")
    }
    gh.set_labels(REPO, 7, [SEVERITY[1], VERDICT["blocked"]], LABELS)
    assert sorted(fake.pr_labels) == ["demo", "someone's label", "theseus: S1", "theseus: blocked"]
    assert fake.repo_labels["theseus: S1"] == {
        "name": "theseus: S1",
        "color": SEVERITY[1].color,
        "description": SEVERITY[1].description,
    }
    assert fake.repo_labels["theseus: blocked"] == {"name": "theseus: blocked"}  # left as it was


def test_labels_already_right_cost_one_request(gh: GitHub, fake: FakeGitHub) -> None:
    from theseus.agent.labels import LABELS, SEVERITY

    fake.pr_labels = ["theseus: S6"]
    gh.installation_token(REPO)
    before = fake.calls
    gh.set_labels(REPO, 7, [SEVERITY[6]], LABELS)
    assert fake.calls - before == 1 and fake.pr_labels == ["theseus: S6"]


def test_a_label_theseus_does_not_manage_is_refused_before_any_request(gh: GitHub, fake: FakeGitHub) -> None:
    from theseus.agent.labels import LABELS, Label

    with pytest.raises(GitHubError, match="does not manage"):
        gh.set_labels(REPO, 7, [Label(name="demo", color="ededed", description="")], LABELS)
    assert fake.calls == 0


def test_a_review_labels_the_pr_and_a_stale_run_does_not(client: TestClient, fake: FakeGitHub) -> None:
    assert analyze(client).status_code == 200
    assert "theseus: blocked" in fake.pr_labels and any(n.startswith("theseus: S") for n in fake.pr_labels)
    fake.pr_labels = []
    fake.head = "c" * 40
    assert analyze(client).status_code == 200
    assert fake.pr_labels == []


# Reading a commit's world -----------------------------------------------------------------------------------


def tree_of(*paths: str) -> dict[str, Any]:
    return {"sha": HEAD, "truncated": False, "tree": [{"path": p, "type": "blob"} for p in paths]}


def test_a_commit_s_world_is_read_in_one_query_and_a_large_file_on_its_own(
    gh: GitHub, fake: FakeGitHub
) -> None:
    fake.router.get(f"/repos/{REPO}/git/trees/{HEAD}").respond(
        200,
        json=tree_of(
            "demo-infra/theseus.yaml",
            "demo-infra/terraform/people.tf",
            "demo-infra/terraform/big.tf",
            "demo-infra/README.md",
            "theseus/config.py",
        ),
    )
    queries: list[dict[str, Any]] = []

    def graphql(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        queries.append(body)
        found = {}
        for key, expression in body["variables"].items():
            if key.startswith("e"):
                path = expression.partition(":")[2]
                big = path.endswith("big.tf")
                found[f"f{key[1:]}"] = {
                    "text": "x" if big else f"# {path}",
                    "isBinary": False,
                    "isTruncated": big,
                }
        return httpx.Response(200, json={"data": {"repository": found}})

    fake.router.post("/graphql").mock(side_effect=graphql)
    files = gh.world_files(REPO, HEAD)
    assert files == {
        "terraform/big.tf": "# demo-infra/terraform/big.tf\n",  # from the contents API
        "terraform/people.tf": "# demo-infra/terraform/people.tf",
        "theseus.yaml": "# demo-infra/theseus.yaml",
    }
    [query] = queries
    assert query["variables"]["owner"] == "demo-org" and query["variables"]["name"] == "theseus"
    assert "demo-infra" not in query["query"]  # paths travel only as variables


def test_a_graphql_error_is_a_github_error(gh: GitHub, fake: FakeGitHub) -> None:
    fake.router.get(f"/repos/{REPO}/git/trees/{HEAD}").respond(200, json=tree_of("demo-infra/theseus.yaml"))
    fake.router.post("/graphql").respond(200, json={"errors": [{"message": "Something went wrong"}]})
    with pytest.raises(GitHubError, match="POST /graphql: Something went wrong"):
        gh.world_files(REPO, HEAD)
