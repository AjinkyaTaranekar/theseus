"""The containment PR and rotate issue (FM6), against a respx-mocked GitHub serving the compromised-action
world as `main`, with the real Terraform renderer: one branch, one commit that changes only `ci.tf`, one PR
labelled `demo`, one rotate issue listing exactly the secrets; and nothing new when it runs again."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.golden.conftest import FIXTURES, deps_for, world
from theseus.api.app import build_render
from theseus.api.contain import branch_for, commit_message, contain
from theseus.api.github import API, GitHub
from theseus.config import Settings
from theseus.contracts.result import AnalysisResult
from theseus.engine.pipeline import run_finding

REPO = "demo-org/theseus"
MAIN = "e" * 40
INSTALLATION = 42
ROOT = FIXTURES / "compromised-action" / "base"
BRANCH = "theseus/contain-GHSA-demo-0001"

_spec = importlib.util.spec_from_file_location(
    "check_commit_msg", Path(__file__).resolve().parents[2] / "tools" / "check_commit_msg.py"
)
assert _spec is not None and _spec.loader is not None
_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_check)


def files() -> dict[str, str]:
    return {
        p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(ROOT.rglob("*"))
        if p.is_file() and ".ruff_cache" not in p.parts
    }


@pytest.fixture(scope="module")
def finding() -> AnalysisResult:
    advisory = json.loads((FIXTURES / "compromised-action/advisory.json").read_text(encoding="utf-8"))
    return run_finding(world("compromised-action", "base"), advisory, deps_for("compromised-action"))


class FakeGitHub:
    """Branches, commits, PRs and issues, as the App would see them."""

    def __init__(self) -> None:
        self.branches: dict[str, str] = {"main": MAIN}
        self.trees: list[dict[str, Any]] = []
        self.commits: list[dict[str, Any]] = []
        self.pulls: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self.labels: dict[int, list[str]] = {}
        self.router = respx.Router(base_url=API, assert_all_called=False)
        r = self.router
        r.get(f"/repos/{REPO}/installation").mock(return_value=httpx.Response(200, json={"id": INSTALLATION}))
        r.post(f"/app/installations/{INSTALLATION}/access_tokens").mock(
            return_value=httpx.Response(201, json={"token": "ghs_x", "expires_at": "2099-01-01T00:00:00Z"})
        )
        r.get(f"/repos/{REPO}").mock(return_value=httpx.Response(200, json={"default_branch": "main"}))
        r.get(url__regex=rf"/repos/{REPO}/git/matching-refs/heads/(?P<name>.+)").mock(side_effect=self._refs)
        r.post(f"/repos/{REPO}/git/refs").mock(side_effect=self._new_ref)
        r.get(url__regex=rf"/repos/{REPO}/git/commits/(?P<sha>\w+)").mock(
            side_effect=lambda req, sha: httpx.Response(200, json={"sha": sha, "tree": {"sha": "t" * 40}})
        )
        r.post(f"/repos/{REPO}/git/trees").mock(side_effect=self._tree)
        r.post(f"/repos/{REPO}/git/commits").mock(side_effect=self._commit)
        r.patch(url__regex=rf"/repos/{REPO}/git/refs/heads/(?P<name>.+)").mock(side_effect=self._move)
        r.get(f"/repos/{REPO}/pulls").mock(side_effect=self._list_pulls)
        r.post(f"/repos/{REPO}/pulls").mock(side_effect=self._pull)
        r.post(url__regex=rf"/repos/{REPO}/issues/(?P<n>\d+)/labels").mock(side_effect=self._label)
        r.get(f"/repos/{REPO}/issues").mock(side_effect=self._list_issues)
        r.post(f"/repos/{REPO}/issues").mock(side_effect=self._issue)

    def _refs(self, request: httpx.Request, name: str) -> httpx.Response:
        found = [
            {"ref": f"refs/heads/{b}", "object": {"sha": s}} for b, s in self.branches.items() if b == name
        ]
        return httpx.Response(200, json=found)

    def _new_ref(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        name = body["ref"].removeprefix("refs/heads/")
        assert name not in self.branches
        self.branches[name] = body["sha"]
        return httpx.Response(201, json={"ref": body["ref"]})

    def _tree(self, request: httpx.Request) -> httpx.Response:
        self.trees.append(json.loads(request.content))
        return httpx.Response(201, json={"sha": "f" * 40})

    def _commit(self, request: httpx.Request) -> httpx.Response:
        self.commits.append(json.loads(request.content))
        return httpx.Response(201, json={"sha": "c" * 40})

    def _move(self, request: httpx.Request, name: str) -> httpx.Response:
        body = json.loads(request.content)
        assert body["force"] is False
        self.branches[name] = body["sha"]
        return httpx.Response(200, json={})

    def _list_pulls(self, request: httpx.Request) -> httpx.Response:
        head = request.url.params["head"].split(":", 1)[1]
        return httpx.Response(200, json=[p for p in self.pulls if p["head"] == head])

    def _pull(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        number = 200 + len(self.pulls)
        pr = {**body, "number": number, "html_url": f"https://github.com/{REPO}/pull/{number}"}
        self.pulls.append(pr)
        return httpx.Response(201, json=pr)

    def _label(self, request: httpx.Request, n: str) -> httpx.Response:
        self.labels[int(n)] = json.loads(request.content)["labels"]
        return httpx.Response(200, json=[])

    def _list_issues(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=self.issues)

    def _issue(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        number = 300 + len(self.issues)
        issue = {**body, "number": number, "html_url": f"https://github.com/{REPO}/issues/{number}"}
        self.issues.append(issue)
        return httpx.Response(201, json=issue)


@pytest.fixture
def fake() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def gh(tmp_path: Path, fake: FakeGitHub, monkeypatch: pytest.MonkeyPatch) -> GitHub:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "app.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    settings = Settings(
        _env_file=None, github_app_id="123", github_app_private_key_path=path, theseus_repos=REPO
    )
    client = GitHub(
        settings, client=httpx.Client(base_url=API, transport=httpx.MockTransport(fake.router.handler))
    )
    monkeypatch.setattr(client, "world_files", lambda repo, sha: files())
    return client


def test_the_containment_pr_changes_only_ci_tf_and_the_issue_lists_the_secrets(
    gh: GitHub, fake: FakeGitHub, finding: AnalysisResult
) -> None:
    done = contain(
        gh, build_render(), REPO, MAIN, finding, "https://theseus.example/findings/GHSA-demo-0001?k=x"
    )
    assert done is not None and done.opened
    assert fake.branches[BRANCH] == "c" * 40  # created at main, then moved to the one commit
    [tree] = fake.trees
    assert [entry["path"] for entry in tree["tree"]] == ["demo-infra/terraform/ci.tf"]
    assert (
        'StringLike = { "token.actions.githubusercontent.com:sub" = "repo:demo-org/*" }'
        not in tree["tree"][0]["content"]
    )
    assert "repo:demo-org/infra:environment:production" in tree["tree"][0]["content"]
    [commit] = fake.commits
    assert commit["parents"] == [MAIN] and commit["message"].startswith("fix: Contain GHSA-demo-0001\n")
    [pr] = fake.pulls
    assert (pr["title"], pr["head"], pr["base"]) == ("fix: Contain GHSA-demo-0001", BRANCH, "main")
    assert "prod-db-credentials" in pr["body"] and "See the finding on a graph" in pr["body"]
    assert fake.labels[pr["number"]] == ["demo"]
    [issue] = fake.issues
    assert issue["title"] == "Rotate these secrets: GHSA-demo-0001" and issue["labels"] == ["demo"]
    assert issue["body"].count("- [ ] ") == 1 and "`prod-db-credentials`" in issue["body"]
    assert (done.pr, done.issue) == (pr["html_url"], issue["html_url"])


def test_running_again_finds_the_open_pr_and_issue_and_opens_nothing(
    gh: GitHub, fake: FakeGitHub, finding: AnalysisResult
) -> None:
    first = contain(gh, build_render(), REPO, MAIN, finding, None)
    again = contain(gh, build_render(), REPO, MAIN, finding, None)
    assert first is not None and again is not None and not again.opened
    assert (again.pr, again.issue) == (first.pr, first.issue)
    assert len(fake.pulls) == 1 and len(fake.issues) == 1 and len(fake.commits) == 1


def test_a_finding_without_a_passing_k_opens_nothing(
    gh: GitHub, fake: FakeGitHub, finding: AnalysisResult
) -> None:
    failed = finding.model_copy(
        update={"candidates": [c.model_copy(update={"verdict": "fail"}) for c in finding.candidates]}
    )
    assert contain(gh, build_render(), REPO, MAIN, failed, None) is None
    assert fake.pulls == [] and fake.issues == [] and list(fake.branches) == ["main"]


def vetoed(finding: AnalysisResult) -> AnalysisResult:
    """The finding as Jev's veto leaves it: K still passes, but is not recommended and needs a closer look."""
    return finding.model_copy(
        update={
            "candidates": [
                c.model_copy(update={"recommended": False, "needs_closer_look": True})
                for c in finding.candidates
            ]
        }
    )


def test_a_vetoed_k_still_opens_the_pr_and_the_pr_says_so(
    gh: GitHub, fake: FakeGitHub, finding: AnalysisResult
) -> None:
    """A veto removes the recommendation, not the proposal: K passed the engine's check, and a person still
    reviews and merges the PR. Holding it back would leave a compromised Action trusted on a model's guess."""
    from theseus.api.contain import purpose_text

    done = contain(gh, build_render(), REPO, MAIN, vetoed(finding), None)
    assert done is not None and done.opened and done.issue is not None
    [pr] = fake.pulls
    [warning] = [line for line in pr["body"].splitlines() if line.startswith("**Needs a closer look.**")]
    assert "`demo-org/docs-site/preview.yml` assuming `github-deploy`" in warning
    # The warning is one of Theseus's notes, so the review of this PR never reads it as the PR's purpose.
    assert "closer look" not in purpose_text(pr["body"])


def test_a_recommended_k_carries_no_warning(gh: GitHub, fake: FakeGitHub, finding: AnalysisResult) -> None:
    assert contain(gh, build_render(), REPO, MAIN, finding, None) is not None
    [pr] = fake.pulls
    assert "closer look" not in pr["body"]


def test_the_commit_message_follows_the_commit_rules(finding: AnalysisResult) -> None:
    message = commit_message("GHSA-demo-0001", finding)
    assert _check.problems(message) == []
    assert message.rstrip().endswith("Proposed-by: theseus")
    assert branch_for("GHSA-demo-0001") == BRANCH


def test_the_review_reads_a_containment_pr_without_theseus_s_own_notes() -> None:
    """The verification notes said the PR was safe, which the intent model rightly called steering."""
    from theseus.api.contain import NOTES_CLOSE, NOTES_OPEN, purpose_text

    body = (
        f"Stop trusting preview.yml as github-deploy.\n\n{NOTES_OPEN}\n**Verification:** pass.\n{NOTES_CLOSE}"
    )
    assert purpose_text(body) == "Stop trusting preview.yml as github-deploy."
    assert purpose_text("No notes here.") == "No notes here."
    # Only the marked block goes: text after it stays for the model to read.
    assert purpose_text(f"a {NOTES_OPEN} b {NOTES_CLOSE} c") == "a  c"
