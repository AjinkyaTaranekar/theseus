"""A verified fix as GitHub suggestions on the PR's own lines: where the edits can sit, and the one review a
head gets. Fix B on the intern PR: the PR adds Priya's membership at people.tf:82-86; the fix removes it and
adds a role in a new file, so one suggestion replaces the membership with the role."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

import pytest

from tests.golden.test_simulate_intern import fix_b
from theseus.api import routes
from theseus.api.app import build_render
from theseus.api.suggest import comment_body, diff_lines, plan
from theseus.contracts.result import AnalysisResult, Candidate

ROOT = Path("fixtures/intern")
PEOPLE = "demo-infra/terraform/people.tf"
HEAD = "a" * 40


def files(side: str) -> dict[str, str]:
    root = ROOT / side
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".ruff_cache" not in p.parts
    }


def pr_patch() -> str:
    """people.tf's patch as GitHub shows it for the intern PR."""
    before, after = files("base")["terraform/people.tf"], files("head")["terraform/people.tf"]
    lines = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=3)
    return "\n".join(line for line in lines if not line.startswith(("---", "+++")))


def test_the_lines_a_comment_can_sit_on_are_the_added_and_context_lines() -> None:
    patch = "@@ -79,3 +79,8 @@ x\n   a\n   b\n }\n+\n+resource\n+  user\n+  groups\n+}\n"
    assert diff_lines(patch) == set(range(79, 87))
    assert diff_lines("@@ -5,2 +5,1 @@\n-gone\n kept\n") == {5}
    assert diff_lines(None) == set()


def test_fix_b_becomes_one_suggestion_replacing_the_pr_s_membership_with_the_new_role() -> None:
    head = files("head")
    edited = build_render()(head, list(fix_b().ops))
    placed = plan(head, edited, {PEOPLE: diff_lines(pr_patch())}, "demo-infra")
    assert placed.unplaced == []
    [s] = placed.suggestions
    old = head["terraform/people.tf"].splitlines()
    assert (s.path, old[s.start - 1]) == (
        PEOPLE,
        'resource "aws_iam_user_group_membership" "priya_support" {',
    )
    assert old[s.end - 1] == "}" and "aws_iam_user_group_membership" not in "\n".join(s.lines)
    assert any('resource "aws_iam_role"' in line for line in s.lines)
    assert any("arn:aws:s3:::demo-app-logs" in line for line in s.lines)
    body = comment_body("B", "A new role", "closes all 3 ways in, breaks nothing", s)
    assert body.count("```suggestion\n") == 1 and body.rstrip().endswith("```")


def test_an_edit_off_the_diff_is_left_for_apply() -> None:
    head = files("head")
    edited = build_render()(head, list(fix_b().ops))
    placed = plan(head, edited, {PEOPLE: {1, 2, 3}}, "demo-infra")
    assert placed.suggestions == [] and placed.unplaced


class FakeGitHub:
    world_root = "demo-infra"

    def __init__(self, reviewed: bool = False) -> None:
        self.reviews: list[dict[str, Any]] = []
        self.reviewed = reviewed

    def world_files(self, repo: str, sha: str) -> dict[str, str]:
        return files("head")

    def pull_patches(self, repo: str, number: int) -> dict[str, str]:
        return {PEOPLE: pr_patch()}

    def has_review_with(self, repo: str, number: int, marker: str) -> bool:
        return self.reviewed or any(marker in r["body"] for r in self.reviews)

    def post_review(
        self, repo: str, number: int, head_sha: str, body: str, comments: list[dict[str, Any]]
    ) -> int:
        self.reviews.append({"head": head_sha, "body": body, "comments": comments})
        return len(self.reviews)


def result_with(verdict: str) -> AnalysisResult:
    """A PR result whose one fix is fix B, with this verdict."""
    candidate = Candidate(
        id="B",
        source="llm",
        proposed_by="m",
        title="A new role",
        ops=fix_b().ops,
        verdict=verdict,
        recommended=verdict == "pass",
    )
    return AnalysisResult(mode="pr", candidates=[candidate])


def test_a_passing_fix_is_suggested_once_per_head() -> None:
    gh = FakeGitHub()
    where = routes._suggest(gh, build_render(), "o/r", 85, HEAD, result_with("pass"))  # type: ignore[arg-type]
    assert where is not None and where[0] == PEOPLE
    [review] = gh.reviews
    [comment] = review["comments"]
    assert (comment["path"], comment["side"], comment["start_side"]) == (PEOPLE, "RIGHT", "RIGHT")
    assert comment["start_line"] == where[1] < comment["line"]
    assert f"<!-- theseus:head:{HEAD} -->" in review["body"] and "```suggestion" in comment["body"]
    again = routes._suggest(gh, build_render(), "o/r", 85, HEAD, result_with("pass"))  # type: ignore[arg-type]
    assert again == where and len(gh.reviews) == 1


@pytest.mark.parametrize("verdict", ["fail", "unknown"])
def test_a_fix_that_does_not_pass_is_never_suggested(verdict: str) -> None:
    gh = FakeGitHub()
    assert routes._suggest(gh, build_render(), "o/r", 85, HEAD, result_with(verdict)) is None  # type: ignore[arg-type]
    assert gh.reviews == []
