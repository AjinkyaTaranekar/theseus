"""`/theseus apply <ID>` and `POST /apply` (docs/spec/07-github-and-deploy.md, "The apply command"), against
a respx-mocked GitHub serving the intern PR's head under `demo-infra/`: no test touches the network.

The fix is a hand-written candidate B (E5's), so these tests need no rule or model to propose it. The
renderer is the real one, built by the app as it is in production.
"""

from __future__ import annotations

import json
import re
import runpy
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from tests.golden.test_simulate_intern import fix_b
from tests.unit import test_github as base
from tests.unit.test_github import HEAD, REPO, TOKEN, FakeGitHub, SampleReview, analyze, webhook
from theseus.adapters.terraform.adapter import TerraformAdapter
from theseus.api import reviews, routes, webhooks
from theseus.api.github import GitHub
from theseus.config import Settings
from theseus.contracts.result import AnalysisResult, Candidate, PatchOp
from theseus.errors import GitHubError, PatchError
from theseus.graph.store import MemoryStore

# The App's settings and client, as tests/unit/test_github.py builds them; `gh` talks to the FakeRepo below.
key_file, settings, gh = base.key_file, base.settings, base.gh

ROOT = Path(__file__).resolve().parents[2]
# The rules every commit message must pass (tools/ is scripts, not a package: load it as the other tests do).
problems = runpy.run_path(str(ROOT / "tools/check_commit_msg.py"))["problems"]
WORLD = ROOT / "fixtures/intern/head"
BRANCH = "demo/intern-2"
NEXT = "c" * 40
NEWER = "d" * 40


def head_files() -> dict[str, str]:
    """The intern PR's head, by path under the world root, as a review reads it."""
    return {
        p.relative_to(WORLD).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(WORLD.rglob("*"))
        if p.is_file()
    }


def rendered(ops: list[PatchOp]) -> dict[str, str]:
    """What the Terraform adapter writes for these ops on the head: the files it changes, by full path."""
    files = head_files()
    out = TerraformAdapter(yaml.safe_load(files["theseus.yaml"])).render(files, ops)
    return {f"demo-infra/{p}": text for p, text in out.items() if files.get(p) != text}


class FakeRepo(FakeGitHub):
    """FakeGitHub with what apply needs: the PR's branch, the head's files, and the Git Data API."""

    def __init__(self) -> None:
        super().__init__()
        self.state = "open"
        self.head_repo: str | None = REPO
        self.branch_moved = False
        self.trees: list[dict[str, Any]] = []
        self.commits: list[dict[str, Any]] = []
        self.refs: list[tuple[str, dict[str, Any]]] = []
        r = self.router
        r.get(url__regex=rf"/repos/{REPO}/git/trees/(?P<sha>\w+)").mock(side_effect=self._tree)
        r.post("/graphql").mock(side_effect=self._graphql)
        r.get(url__regex=rf"/repos/{REPO}/git/commits/(?P<sha>\w+)$").mock(side_effect=self._commit)
        r.post(f"/repos/{REPO}/git/trees").mock(side_effect=self._new_tree)
        r.post(f"/repos/{REPO}/git/commits").mock(side_effect=self._new_commit)
        r.patch(url__regex=rf"/repos/{REPO}/git/refs/(?P<ref>.+)$").mock(side_effect=self._move_ref)

    def _pull(self, request: httpx.Request) -> httpx.Response:
        self._authed(request)
        head = {
            "sha": self.head,
            "ref": BRANCH,
            "repo": {"full_name": self.head_repo} if self.head_repo else None,
        }
        pr = {
            "number": 7,
            "title": "t",
            "body": "b",
            "state": self.state,
            "head": head,
            "base": {"sha": "b" * 40},
        }
        return httpx.Response(200, json=pr)

    def _tree(self, request: httpx.Request, sha: str) -> httpx.Response:
        assert sha == self.head, "apply reads only the PR's head"
        tree = [{"path": f"demo-infra/{p}", "type": "blob"} for p in head_files()]
        return httpx.Response(200, json={"sha": sha, "tree": tree, "truncated": False})

    def _graphql(self, request: httpx.Request) -> httpx.Response:
        files = head_files()
        found = {}
        for key, expression in json.loads(request.content)["variables"].items():
            if key.startswith("e"):
                path = expression.partition(":")[2].removeprefix("demo-infra/")
                found[f"f{key[1:]}"] = {"text": files[path], "isBinary": False, "isTruncated": False}
        return httpx.Response(200, json={"data": {"repository": found}})

    def _commit(self, request: httpx.Request, sha: str) -> httpx.Response:
        return httpx.Response(200, json={"sha": sha, "tree": {"sha": f"tree-of-{sha}"}})

    def _new_tree(self, request: httpx.Request) -> httpx.Response:
        self._authed(request)
        self.trees.append(json.loads(request.content))
        return httpx.Response(201, json={"sha": "e" * 40})

    def _new_commit(self, request: httpx.Request) -> httpx.Response:
        self._authed(request)
        self.commits.append(json.loads(request.content))
        return httpx.Response(201, json={"sha": NEXT})

    def _move_ref(self, request: httpx.Request, ref: str) -> httpx.Response:
        self._authed(request)
        body = json.loads(request.content)
        self.refs.append((ref, body))
        if self.branch_moved:
            return httpx.Response(422, json={"message": "Update is not a fast forward"})
        self.head = body["sha"]
        return httpx.Response(200, json={"ref": f"refs/{ref}", "object": {"sha": body["sha"]}})

    @property
    def writes(self) -> list[str]:
        """Every request that writes code: none may happen when apply refuses."""
        return [
            f"{c.request.method} {c.request.url.path}"
            for c in self.router.calls
            if c.request.method != "GET" and "/git/" in c.request.url.path
        ]

    @property
    def replies(self) -> list[str]:
        return [c["body"] for c in self.comments if "theseus:pr-comment" not in c["body"]]


def fixes(b_ops: list[PatchOp] | None = None) -> list[Candidate]:
    def fix(identifier: str, verdict: str, reason: str, ops: list[PatchOp]) -> Candidate:
        return Candidate(
            id=identifier,
            source="rule",
            proposed_by="theseus",
            title=f"Fix {identifier}",
            ops=ops,
            verdict=verdict,  # type: ignore[arg-type]
            reason=reason,
        )

    return [
        fix("A", "fail", "Required access lost: I1", [fix_b().ops[0]]),
        fix("B", "pass", "Requested dangerous paths are closed.", fix_b().ops if b_ops is None else b_ops),
        fix("C", "unknown", "path P9: user:priya-intern -> db:customer-db is unknown", []),
    ]


class FixReview(SampleReview):
    """The sample review, carrying fixes A, B and C."""

    def __init__(self) -> None:
        super().__init__()
        self.candidates = fixes()

    def __call__(self, gh: GitHub, *args: Any) -> Any:
        result: AnalysisResult = super().__call__(gh, *args)
        return result.model_copy(update={"candidates": self.candidates})


@pytest.fixture
def fake() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def review() -> FixReview:
    return FixReview()


@pytest.fixture
def results() -> webhooks.Results:
    return webhooks.Results()


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def render_with() -> dict[str, webhooks.Render]:
    """Set "render" to replace the app's renderer in one test."""
    return {}


@pytest.fixture
def client(
    settings: Settings,
    gh: GitHub,
    review: FixReview,
    store: MemoryStore,
    results: webhooks.Results,
    render_with: dict[str, webhooks.Render],
) -> Iterator[TestClient]:
    from theseus.api.app import create_app

    app = create_app(connect=lambda: object())
    app.dependency_overrides[routes.get_settings] = lambda: settings
    app.dependency_overrides[routes.get_github] = lambda: gh
    app.dependency_overrides[routes.get_review] = lambda: review
    app.dependency_overrides[routes.get_store] = lambda: store
    app.dependency_overrides[routes.get_results] = lambda: results
    # The app's own renderer unless a test sets another; read per request, so a test can set it late.
    app.dependency_overrides[routes.get_render] = lambda: render_with.get("render") or app.state.render
    with TestClient(app) as c:
        yield c


def comment(body: str, user: str = "sakshi", action: str = "created", on_pr: bool = True) -> dict[str, Any]:
    issue: dict[str, Any] = {"number": 7, **({"pull_request": {"url": "x"}} if on_pr else {})}
    return {
        "action": action,
        "issue": issue,
        "comment": {"id": 77, "body": body, "user": {"login": user}},
        "repository": {"full_name": REPO},
    }


def apply(client: TestClient, candidate: str = "B", user: str = "sakshi") -> httpx.Response:
    return webhook(client, "issue_comment", comment(f"/theseus apply {candidate}", user))


def reviewed(client: TestClient) -> None:
    assert analyze(client).status_code == 200


# A writer's command ---------------------------------------------------------------------------------------


def test_a_writer_s_command_commits_the_rendered_fix_to_the_pr_branch(
    client: TestClient, fake: FakeRepo
) -> None:
    reviewed(client)
    assert apply(client).status_code == 204
    [tree] = fake.trees
    assert tree["base_tree"] == f"tree-of-{HEAD}"
    # Exactly the renderer's edits, every one under the world root, as one commit on the reviewed head.
    want = rendered(fix_b().ops)
    assert sorted(want) == ["demo-infra/terraform/people.tf", "demo-infra/terraform/theseus_fixes.tf"]
    assert {e["path"]: e["content"] for e in tree["tree"]} == want
    assert all(e["mode"] == "100644" and e["type"] == "blob" for e in tree["tree"])
    [commit] = fake.commits
    assert commit["parents"] == [HEAD] and commit["tree"] == "e" * 40
    # The branch moves only forward: never a force push.
    assert fake.refs == [(f"heads/{BRANCH}", {"sha": NEXT, "force": False})]
    [reply] = fake.replies
    assert reply.startswith("> /theseus apply B\n\n@sakshi ")
    assert f"`{NEXT[:7]}`" in reply and f"`{BRANCH}`" in reply
    assert "`demo-infra/terraform/people.tf`" in reply


def test_the_commit_message_follows_the_repo_s_rules_and_names_who_proposed_and_approved(
    client: TestClient, fake: FakeRepo
) -> None:
    reviewed(client)
    assert apply(client).status_code == 204
    message = fake.commits[0]["message"]
    assert problems(message) == []
    subject, blank, *body = message.splitlines()
    assert subject == "fix: Apply the fix Theseus suggested" and blank == ""
    text = "\n".join(body)
    # The paths it closes and the requirements it keeps, from the review the fix was checked against.
    assert "user:priya-intern -> db:customer-db" in text
    assert "user:priya-intern -> s3://demo-company-files/invoices/" in text
    assert "I1, R1, R2, R3" in text
    assert body[-2:] == ["Proposed-by: theseus", "Requested-by: @sakshi"]


def test_a_trailer_cannot_be_forged_through_a_candidate_s_proposer(review: FixReview) -> None:
    result = routes.stub_for("sample", "pr")
    candidate = fixes()[1].model_copy(update={"proposed_by": "llm\n\nRequested-by: @mallory"})
    message = webhooks.commit_message(candidate, result, "sakshi")
    assert message.splitlines()[-2:] == ["Proposed-by: llm Requested-by: @mallory", "Requested-by: @sakshi"]
    assert problems(message) == []


def test_long_path_names_are_wrapped_for_the_commit_rules() -> None:
    result = routes.stub_for("sample", "pr")
    long = result.opened[0].model_copy(
        update={
            "actor": "workflow:demo-org/infra/.github/workflows/deploy-production.yml",
            "target": "s3://x/" * 6,
        }
    )
    message = webhooks.commit_message(fixes()[1], result.model_copy(update={"opened": [long]}), "sakshi")
    assert problems(message) == []


# Refusals -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("permission", ["read", "triage", "none"])
def test_a_reader_s_command_is_refused_and_nothing_is_read_or_written(
    client: TestClient, fake: FakeRepo, permission: str
) -> None:
    reviewed(client)
    fake.permission = permission
    before = len(fake.router.calls)
    assert apply(client, user="reader").status_code == 204
    [reply] = fake.replies
    assert "@reader" in reply and "write access" in reply
    # Permission comes first: the PR, its files and the Git Data API are never touched.
    after = [c.request.url.path for c in fake.router.calls[before:]]
    assert not [p for p in after if p == f"/repos/{REPO}/pulls/7" or p == "/graphql" or "/git/" in p]


@pytest.mark.parametrize(
    ("candidate", "verdict", "reason"),
    [("A", "fail", "Required access lost: I1"), ("C", "unknown", "is unknown")],
)
def test_a_candidate_that_does_not_pass_is_refused_with_its_verdict_and_reason(
    client: TestClient, fake: FakeRepo, candidate: str, verdict: str, reason: str
) -> None:
    reviewed(client)
    assert apply(client, candidate).status_code == 204
    [reply] = fake.replies
    assert f"Fix {candidate} is `{verdict}`" in reply and reason in reply
    assert "Fixes that pass: B." in reply
    assert fake.writes == []


@pytest.mark.parametrize(
    "edits",
    [
        {"terraform/people.tf": "# fixed\n", "../.github/workflows/theseus.yml": "on: push\n"},
        {"terraform/people.tf": "# fixed\n", "../README.md": "pwned\n"},
        {"terraform/./people.tf": "# fixed\n"},
    ],
)
def test_a_change_outside_the_world_root_refuses_the_whole_commit(
    client: TestClient, fake: FakeRepo, render_with: dict[str, webhooks.Render], edits: dict[str, str]
) -> None:
    render_with["render"] = lambda files, ops: {**files, **edits}
    reviewed(client)
    assert apply(client).status_code == 204
    [reply] = fake.replies
    assert "outside `demo-infra/`" in reply and "nothing was committed" in reply
    assert fake.writes == []


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        ".github/workflows/theseus.yml",
        "demo-infra",
        "demo-infra/",
        "demo-infra/../theseus/api/routes.py",
        "demo-infra//terraform/people.tf",
        "demo-infra/./terraform/people.tf",
        "demo-infra\\terraform\\people.tf",
        # A literal backslash in git, but a separator on a Windows checkout: it would climb out there.
        "demo-infra/terraform\\..\\..\\README.md",
        "/demo-infra/terraform/people.tf",
        "DEMO-INFRA/terraform/people.tf",
        "demo-infra-evil/terraform/people.tf",
        "demo-infra/terraform/people.tf\x00",
    ],
)
def test_commit_files_refuses_any_path_outside_the_world_root_before_any_request(
    gh: GitHub, fake: FakeRepo, path: str
) -> None:
    good = {"demo-infra/terraform/people.tf": "# ok\n"}
    with pytest.raises(GitHubError, match="world root"):
        gh.commit_files(REPO, BRANCH, HEAD, {**good, path: "x"}, "fix: Apply Theseus fix B")
    assert fake.calls == 0


def test_commit_files_makes_one_commit_on_its_parent_and_never_forces(gh: GitHub, fake: FakeRepo) -> None:
    files = {"demo-infra/terraform/b.tf": "b\n", "demo-infra/terraform/a.tf": "a\n"}
    assert gh.commit_files(REPO, BRANCH, HEAD, files, "fix: Apply Theseus fix B") == NEXT
    assert [e["path"] for e in fake.trees[0]["tree"]] == sorted(files)
    assert fake.commits == [{"message": "fix: Apply Theseus fix B", "tree": "e" * 40, "parents": [HEAD]}]
    assert fake.refs == [(f"heads/{BRANCH}", {"sha": NEXT, "force": False})]


def test_commit_files_refuses_an_empty_commit_and_a_repo_outside_theseus_repos(
    gh: GitHub, fake: FakeRepo
) -> None:
    with pytest.raises(GitHubError, match="nothing to commit"):
        gh.commit_files(REPO, BRANCH, HEAD, {}, "fix: Apply Theseus fix B")
    with pytest.raises(GitHubError, match="THESEUS_REPOS"):
        gh.commit_files("someone/else", BRANCH, HEAD, {"demo-infra/x.tf": "x"}, "fix: Apply Theseus fix B")
    assert fake.calls == 0


def test_an_unknown_fix_names_the_fixes_that_pass(client: TestClient, fake: FakeRepo) -> None:
    reviewed(client)
    assert webhook(client, "issue_comment", comment("/theseus apply H12")).status_code == 204
    [reply] = fake.replies
    assert "no fix H12" in reply and "Fixes that pass: B." in reply
    assert fake.writes == []


def test_with_no_passing_fix_the_reply_says_so(client: TestClient, fake: FakeRepo, review: FixReview) -> None:
    review.candidates = [c for c in fixes() if c.id != "B"]
    reviewed(client)
    assert apply(client).status_code == 204
    assert "No fix passes" in fake.replies[0]


def test_a_review_of_an_older_commit_is_never_applied_and_the_head_is_reviewed(
    client: TestClient, fake: FakeRepo
) -> None:
    reviewed(client)
    fake.head = NEWER  # someone pushed after the review
    fake.runs.append({"id": 100, "status": "completed", "head_sha": NEWER})
    assert apply(client).status_code == 204
    [reply] = fake.replies
    assert f"`{NEWER[:7]}`" in reply and "reviewing it now" in reply
    assert fake.reruns == [100] and fake.writes == []


def test_with_no_review_and_no_run_to_repeat_the_reply_says_what_to_do(
    client: TestClient, fake: FakeRepo
) -> None:
    fake.runs = []
    assert apply(client).status_code == 204
    assert "no Theseus run" in fake.replies[0] and fake.writes == []


def test_the_review_in_memory_serves_without_the_store(
    client: TestClient, fake: FakeRepo, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviewed(client)
    monkeypatch.setattr(store, "get_doc", lambda key: None)  # the page's copy is gone or unreadable
    assert apply(client).status_code == 204
    assert len(fake.commits) == 1 and fake.reruns == []


def test_the_review_kept_in_the_store_still_serves_after_a_restart(
    client: TestClient, fake: FakeRepo, results: webhooks.Results
) -> None:
    reviewed(client)
    results.clear()  # a restart empties memory; the review page's copy in FalkorDB remains
    assert apply(client).status_code == 204
    assert len(fake.commits) == 1 and fake.reruns == []


def test_a_kept_review_of_another_commit_is_not_used(
    client: TestClient, fake: FakeRepo, results: webhooks.Results, store: MemoryStore
) -> None:
    reviewed(client)
    results.clear()
    fake.head = NEWER
    assert apply(client).status_code == 204
    # The kept review is of HEAD, and NEWER never ran the workflow: nothing to apply, nothing to repeat.
    assert fake.writes == [] and "no Theseus run" in fake.replies[0]


def test_a_branch_in_a_fork_is_refused(client: TestClient, fake: FakeRepo) -> None:
    reviewed(client)
    fake.head_repo = "someone/fork"
    assert apply(client).status_code == 204
    assert "`someone/fork`" in fake.replies[0] and fake.writes == []


def test_a_branch_whose_fork_was_deleted_is_refused(client: TestClient, fake: FakeRepo) -> None:
    reviewed(client)
    fake.head_repo = None
    assert apply(client).status_code == 204
    assert "another repository" in fake.replies[0] and fake.writes == []


def test_a_closed_pr_is_refused(client: TestClient, fake: FakeRepo) -> None:
    reviewed(client)
    fake.state = "closed"
    assert apply(client).status_code == 204
    assert "closed" in fake.replies[0] and fake.writes == []


def test_a_fix_the_renderer_cannot_verify_is_refused(
    client: TestClient, fake: FakeRepo, render_with: dict[str, webhooks.Render]
) -> None:
    def refuse(files: dict[str, str], ops: list[PatchOp]) -> dict[str, str]:
        raise PatchError("Sid 'ReadAppLogs' must match exactly one statement")

    render_with["render"] = refuse
    reviewed(client)
    assert apply(client).status_code == 204
    [reply] = fake.replies
    assert "could not be written safely" in reply and "ReadAppLogs" in reply
    assert fake.writes == []


def test_a_fix_already_in_the_branch_is_not_committed_again(
    client: TestClient, fake: FakeRepo, render_with: dict[str, webhooks.Render]
) -> None:
    render_with["render"] = lambda files, ops: dict(files)
    reviewed(client)
    assert apply(client).status_code == 204
    assert "changes nothing" in fake.replies[0] and fake.writes == []


def test_a_renderer_that_drops_a_file_is_refused(
    client: TestClient, fake: FakeRepo, render_with: dict[str, webhooks.Render]
) -> None:
    render_with["render"] = lambda files, ops: {k: v for k, v in files.items() if k != "terraform/people.tf"}
    reviewed(client)
    assert apply(client).status_code == 204
    assert "would delete" in fake.replies[0] and fake.writes == []


def test_a_branch_that_moved_since_the_review_is_never_overwritten(
    client: TestClient, fake: FakeRepo
) -> None:
    reviewed(client)
    fake.branch_moved = True
    assert apply(client).status_code == 502
    assert [body["force"] for _, body in fake.refs] == [False]
    assert "could not commit the fix" in fake.replies[0] and "422" in fake.replies[0]


# What counts as the command -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        comment("/theseus apply b"),
        comment("/theseus apply B now"),
        comment("please /theseus apply B"),
        comment("/theseus apply B C"),
        comment("/theseus apply B", action="edited"),
        comment("/theseus apply B", on_pr=False),
    ],
)
def test_only_an_exact_command_in_a_new_pr_comment_counts(
    client: TestClient, fake: FakeRepo, payload: dict[str, Any]
) -> None:
    reviewed(client)
    before = fake.calls
    assert webhook(client, "issue_comment", payload).status_code == 204
    assert fake.calls == before and fake.replies == []


@pytest.mark.parametrize("body", ["/theseus apply B\n", "  /theseus apply B  ", "/theseus apply B\r\n"])
def test_surrounding_whitespace_is_allowed(client: TestClient, fake: FakeRepo, body: str) -> None:
    reviewed(client)
    assert webhook(client, "issue_comment", comment(body)).status_code == 204
    assert len(fake.commits) == 1


@pytest.mark.parametrize(
    ("body", "candidate"), [("/theseus apply B", "B"), ("/theseus apply H12", "H12"), ("/theseus apply", "")]
)
def test_the_command_names_a_letter_a_person_s_fix_or_nothing(body: str, candidate: str) -> None:
    assert webhooks.apply_command(body) == candidate


def test_apply_alone_commits_the_recommended_fix(client: TestClient, fake: FakeRepo) -> None:
    reviewed(client)
    assert webhook(client, "issue_comment", comment("/theseus apply")).status_code == 204
    assert len(fake.commits) == 1
    assert fake.replies[0].startswith("> /theseus apply\n") and "Committed the fix (" in fake.replies[0]


@pytest.mark.parametrize("body", ["/theseus apply Z9", "/theseus apply H0", "/theseus apply K12"])
def test_an_id_no_candidate_can_have_is_answered_like_an_unknown_one(
    client: TestClient, fake: FakeRepo, body: str
) -> None:
    reviewed(client)
    assert webhook(client, "issue_comment", comment(body)).status_code == 204
    assert "no fix" in fake.replies[0] and fake.writes == []


def test_theseus_review_still_reruns_the_review(client: TestClient, fake: FakeRepo) -> None:
    assert webhook(client, "issue_comment", comment("/theseus review")).status_code == 204
    assert fake.reruns == [99] and fake.replies == []


# The result cache -----------------------------------------------------------------------------------------


def test_results_are_kept_by_repo_pr_and_commit_and_the_oldest_go_first() -> None:
    results = webhooks.Results(size=2)
    one, two, three = (routes.stub_for("sample", "pr").model_copy(update={"headline": h}) for h in "123")
    results.put("Demo-Org/Theseus", 7, HEAD, one)
    assert results.get("demo-org/theseus", 7, HEAD) == one
    assert results.get(REPO, 7, NEWER) is None and results.get(REPO, 8, HEAD) is None
    results.put(REPO, 7, NEWER, two)
    results.get(REPO, 7, HEAD)  # touched, so it stays
    results.put(REPO, 8, HEAD, three)
    assert results.get(REPO, 7, NEWER) is None
    assert results.get(REPO, 7, HEAD) == one and results.get(REPO, 8, HEAD) == three


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"head_sha": "' + HEAD + '"}',
        '{"head_sha": "' + HEAD + '", "result": {"mode": "nope"}}',
    ],
)
def test_a_kept_review_that_cannot_be_read_back_counts_as_none(store: MemoryStore, text: str) -> None:
    store.put_doc(reviews.key(REPO, 7), text)
    assert webhooks.latest(webhooks.Results(), store, REPO, 7, HEAD) is None


def test_a_kept_review_is_read_back_as_the_same_result(store: MemoryStore) -> None:
    result = routes.stub_for("sample", "pr").model_copy(update={"candidates": fixes()})
    reviews.save(store, REPO, 7, ("b" * 40, HEAD), "demo-infra", result)
    assert webhooks.latest(webhooks.Results(), store, REPO, 7, HEAD) == result
    assert webhooks.latest(webhooks.Results(), store, REPO, 7, NEWER) is None
    assert webhooks.latest(webhooks.Results(), store, REPO, 8, HEAD) is None


# POST /apply ----------------------------------------------------------------------------------------------


def post_apply(client: TestClient, token: str | None = TOKEN, **body: Any) -> httpx.Response:
    headers = {"X-Theseus-Token": token} if token is not None else {}
    payload = {"repo": REPO, "pr_number": 7, "candidate_id": "B", "requested_by": "sakshi", **body}
    return client.post("/apply", json=payload, headers=headers)


def test_post_apply_commits_and_returns_the_commit(client: TestClient, fake: FakeRepo) -> None:
    reviewed(client)
    res = post_apply(client)
    assert res.status_code == 200, res.text
    assert res.json() == {"commit_sha": NEXT}
    assert fake.commits[0]["message"].splitlines()[-1] == "Requested-by: @sakshi"
    assert fake.replies == []  # an API call answers itself; only a command gets a reply


@pytest.mark.parametrize("token", [None, "wrong"])
def test_post_apply_needs_the_token(client: TestClient, fake: FakeRepo, token: str | None) -> None:
    assert post_apply(client, token=token).status_code == 401
    assert fake.calls == 0


@pytest.mark.parametrize(
    ("change", "status"),
    [
        (lambda fake, body: fake.__setattr__("permission", "read"), 403),
        (lambda fake, body: body.update(candidate_id="C"), 409),
        (lambda fake, body: body.update(candidate_id="D"), 404),
        (lambda fake, body: body.update(candidate_id="b"), 422),
        (lambda fake, body: body.update(requested_by="x\nRequested-by: @y"), 422),
        (lambda fake, body: body.update(repo="someone/else"), 403),
        (lambda fake, body: fake.__setattr__("state", "closed"), 409),
    ],
)
def test_post_apply_refuses_with_a_status_that_says_why(
    client: TestClient, fake: FakeRepo, change: Callable[[FakeRepo, dict[str, Any]], None], status: int
) -> None:
    reviewed(client)
    body: dict[str, Any] = {}
    change(fake, body)
    res = post_apply(client, **body)
    assert res.status_code == status, res.text
    assert fake.writes == []


# The hand-written fix, end to end ------------------------------------------------------------------------


def test_fix_b_passes_on_its_graph_copy_and_apply_commits_what_the_renderer_verified(
    client: TestClient, fake: FakeRepo, review: FixReview
) -> None:
    """E5 checks B on a copy of the intern head; A9 commits exactly the edits E9 verified for it."""
    from tests.golden.test_simulate_intern import intern
    from theseus.engine.simulate import simulate
    from theseus.graph.load import load_graph

    deps, head, reqs = intern()
    load_graph(deps.store, head)
    checked = simulate(deps.store, head, fix_b(), ["user:priya-intern"], reqs, deps.adapters)
    assert checked.verdict == "pass"
    review.candidates = [checked]
    reviewed(client)
    assert apply(client).status_code == 204
    assert {e["path"]: e["content"] for e in fake.trees[0]["tree"]} == rendered(checked.ops)
    assert re.search(r"^Proposed-by: theseus$", fake.commits[0]["message"], re.M)


@pytest.mark.falkordb
def test_a_review_kept_in_falkordb_is_read_back_as_the_same_result() -> None:
    """After a restart, apply reads the review the page keeps in FalkorDB: every field survives the trip."""
    import os

    from theseus.config import get_settings
    from theseus.graph.client import get_client
    from theseus.graph.store import DOCS, FalkorStore

    falkor = FalkorStore(get_client(get_settings()))
    repo = f"a9-test/pid-{os.getpid()}"
    result = routes.stub_for("sample", "pr").model_copy(update={"candidates": fixes()})
    try:
        reviews.save(falkor, repo, 7, ("b" * 40, HEAD), "demo-infra", result)
        assert webhooks.latest(webhooks.Results(), falkor, repo, 7, HEAD) == result
        assert webhooks.latest(webhooks.Results(), falkor, repo, 7, NEWER) is None
    finally:
        falkor.db.select_graph(DOCS).query(
            "MATCH (d:Doc {key: $key}) DELETE d", {"key": reviews.key(repo, 7)}
        )
