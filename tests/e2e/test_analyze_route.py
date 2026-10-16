"""`POST /analyze` from the Action runs the real review (task A5), end to end.

GitHub is mocked by respx and serves the intern fixture under `demo-infra/` at a base and a head commit. The
review fetches the files, lays them out, runs the pipeline and posts the comment and the check. The store is
in memory and the model and Jev replay, so nothing touches the network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from tests.golden.conftest import RecordedIntent, RecordedJev
from theseus.agent.render import MARKER
from theseus.api import routes
from theseus.api.app import build_review, create_app
from theseus.api.github import API, GitHub
from theseus.config import Settings
from theseus.graph.store import MemoryStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/intern"
REPO = "demo-org/theseus"
APP_ID, INSTALLATION = 123, 42
HEAD, BASE = "a" * 40, "b" * 40
TOKEN = "theseus-token-not-real"
SIDES = {HEAD: FIXTURE / "head", BASE: FIXTURE / "base"}


class FakeRepo:
    """The slice of GitHub a review reads and writes, with the intern PR's two commits."""

    def __init__(self) -> None:
        self.comments: list[dict[str, Any]] = []
        self.checks: list[dict[str, Any]] = []
        self.read: list[str] = []
        title, _, body = (FIXTURE / "pr.md").read_text(encoding="utf-8").partition("\n")
        pr = {"number": 7, "title": title.removeprefix("# "), "body": body.strip()}
        pr |= {"head": {"sha": HEAD}, "base": {"sha": BASE}}
        self.router = respx.Router(base_url=API, assert_all_called=False)
        r = self.router
        r.get(f"/repos/{REPO}/installation").mock(return_value=httpx.Response(200, json={"id": INSTALLATION}))
        r.post(f"/app/installations/{INSTALLATION}/access_tokens").mock(
            return_value=httpx.Response(201, json={"token": "ghs_x", "expires_at": "2099-01-01T00:00:00Z"})
        )
        r.get(f"/repos/{REPO}/pulls/7").mock(return_value=httpx.Response(200, json=pr))
        r.get(url__regex=rf"/repos/{REPO}/git/trees/(?P<sha>\w+)").mock(side_effect=self._tree)
        r.get(url__regex=rf"/repos/{REPO}/contents/(?P<path>[^?]+)").mock(side_effect=self._contents)
        r.get(f"/repos/{REPO}/issues/7/comments").mock(side_effect=lambda req: self._page(req, self.comments))
        r.post(f"/repos/{REPO}/issues/7/comments").mock(side_effect=self._comment)
        r.get(url__regex=rf"/repos/{REPO}/commits/(?P<sha>\w+)/check-runs").mock(
            side_effect=self._list_checks
        )
        r.post(f"/repos/{REPO}/check-runs").mock(side_effect=self._check)
        r.patch(url__regex=rf"/repos/{REPO}/check-runs/(?P<cid>\d+)$").mock(side_effect=self._edit_check)

    def _tree(self, request: httpx.Request, sha: str) -> httpx.Response:
        assert request.url.params["recursive"] == "1"
        side = SIDES[sha]
        files = [p.relative_to(side).as_posix() for p in sorted(side.rglob("*")) if p.is_file()]
        tree = [{"path": f"demo-infra/{f}", "type": "blob"} for f in files]
        tree += [{"path": "demo-infra", "type": "tree"}, {"path": "README.md", "type": "blob"}]
        return httpx.Response(200, json={"sha": sha, "tree": tree, "truncated": False})

    def _contents(self, request: httpx.Request, path: str) -> httpx.Response:
        assert path.startswith("demo-infra/"), path
        self.read.append(path)
        side = SIDES[request.url.params["ref"]]
        return httpx.Response(200, text=(side / path.removeprefix("demo-infra/")).read_text(encoding="utf-8"))

    @staticmethod
    def _page(request: httpx.Request, rows: list[dict[str, Any]]) -> httpx.Response:
        return httpx.Response(200, json=rows if request.url.params.get("page", "1") == "1" else [])

    def _comment(self, request: httpx.Request) -> httpx.Response:
        comment = {
            "id": 900,
            "body": json.loads(request.content)["body"],
            "performed_via_github_app": {"id": APP_ID},
        }
        self.comments.append(comment)
        return httpx.Response(201, json=comment)

    def _list_checks(self, request: httpx.Request, sha: str) -> httpx.Response:
        runs = [c for c in self.checks if c["head_sha"] == sha]
        return httpx.Response(200, json={"total_count": len(runs), "check_runs": runs})

    def _check(self, request: httpx.Request) -> httpx.Response:
        check = {"id": 500 + len(self.checks), **json.loads(request.content)}
        self.checks.append(check)
        return httpx.Response(201, json=check)

    def _edit_check(self, request: httpx.Request, cid: str) -> httpx.Response:
        check = next(c for c in self.checks if c["id"] == int(cid))
        check.update(json.loads(request.content))
        return httpx.Response(200, json=check)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "app.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    return Settings(
        _env_file=None,
        github_app_id=str(APP_ID),
        github_app_private_key_path=path,
        theseus_token=TOKEN,
        theseus_repos=REPO,
    )


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def client(settings: Settings, repo: FakeRepo, store: MemoryStore) -> Iterator[TestClient]:
    gh = GitHub(
        settings, client=httpx.Client(base_url=API, transport=httpx.MockTransport(repo.router.handler))
    )
    app = create_app(connect=lambda: object())
    app.dependency_overrides[routes.get_settings] = lambda: settings
    app.dependency_overrides[routes.get_github] = lambda: gh
    app.dependency_overrides[routes.get_review] = lambda: build_review(
        store, RecordedIntent(), RecordedJev(), settings
    )
    with TestClient(app) as c:
        yield c


def post(client: TestClient) -> httpx.Response:
    body = {
        "repo": REPO,
        "pr_number": 7,
        "head_sha": HEAD,
        "base_plan": json.loads((FIXTURE / "base.plan.json").read_text(encoding="utf-8")),
        "head_plan": json.loads((FIXTURE / "head.plan.json").read_text(encoding="utf-8")),
        "checkov": {"passed": 365, "failed": 0, "skipped": 53, "checkov_version": "3.3.29"},
    }
    return client.post("/analyze", json=body, headers={"X-Theseus-Token": TOKEN})


def test_the_intern_pr_gets_its_headline_three_opened_paths_and_a_failing_check(
    client: TestClient, repo: FakeRepo, store: MemoryStore
) -> None:
    res = post(client)
    assert res.status_code == 200, res.text
    result = res.json()
    assert (result["repo"], result["pr_number"]) == (REPO, 7)
    assert sorted(p["target"] for p in result["opened"]) == [
        "db:customer-db",
        "s3://demo-company-files/invoices/",
        "secret:prod-db-credentials",
    ]
    assert "Your change grants customer-db, a database." in result["headline"]

    [comment] = repo.comments
    body = comment["body"]
    assert body.startswith(MARKER)
    # The card says what Priya could do, each hop with its own access: the role reads the secret, and the
    # secret opens the database to reads and changes.
    assert "**priya-intern**, a user, could read and change **customer-db**, a database" in body
    assert "can read **prod-db-credentials** → unlocks **customer-db**" in body
    for target in ("db:customer-db", "s3://demo-company-files/invoices/", "secret:prod-db-credentials"):
        assert f"| `user:priya-intern` | `{target}` (" in body
    # Each hop links to its line at the head commit the review read.
    assert f"/blob/{HEAD}/demo-infra/terraform/people.tf#L83" in body

    [check] = repo.checks
    assert (check["head_sha"], check["status"], check["conclusion"]) == (HEAD, "completed", "failure")
    assert check["output"]["title"].startswith("Merge blocked")
    # The note sits on the line the PR adds: Priya's membership.
    [note] = check["output"]["annotations"]
    assert (note["path"], note["start_line"], note["annotation_level"]) == (
        "demo-infra/terraform/people.tf",
        83,
        "failure",
    )
    assert note["title"] == "Opens 3 new ways to sensitive data"
    assert store.list_graphs() == ["demo-infra__pr7-base", "demo-infra__pr7-head"]


def test_the_review_reads_only_the_world_root_at_both_commits(client: TestClient, repo: FakeRepo) -> None:
    assert post(client).status_code == 200
    assert "README.md" not in repo.read and all(p.startswith("demo-infra/") for p in repo.read)
    assert {"demo-infra/theseus.yaml", "demo-infra/terraform/people.tf"} <= set(repo.read)
    assert any(p.startswith("demo-infra/services/") for p in repo.read)
    assert any(p.startswith("demo-infra/workflows/") for p in repo.read)
