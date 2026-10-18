"""The check before a PR (`python -m theseus check`): the working tree's change against main, reviewed as a PR
would be, printed for a terminal and answered as a Claude Code hook. A git repository holds the intern world,
its change left uncommitted; Terraform is stood in for by the intern fixture's plans."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.golden.conftest import FIXTURES, RecordedJev
from theseus import cli
from theseus.agent.render import check_text
from theseus.config import get_settings
from theseus.contracts.result import AnalysisResult
from theseus.graph.store import MemoryStore

WORLD = "demo-infra"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
    )


def fixture_plan(terraform: Path) -> dict[str, Any]:
    side = terraform.parent.name
    return json.loads((FIXTURES / "intern" / f"{side}.plan.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("check") / "repo"
    shutil.copytree(FIXTURES / "intern" / "base", root / WORLD)
    _git(root.parent, "init", "-q", str(root))
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "branch", "-M", "main")
    shutil.rmtree(root / WORLD)
    shutil.copytree(FIXTURES / "intern" / "head", root / WORLD)
    return root


@pytest.fixture(scope="module")
def checked(repo: Path) -> AnalysisResult:
    store = MemoryStore()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli, "models", lambda settings: (None, RecordedJev()))
        result = cli.check_change(repo, "main", WORLD, store, get_settings(), plan=fixture_plan)
    assert store.list_graphs() == []  # a check leaves no graph behind
    return result


def test_the_change_is_the_working_tree_against_main(repo: Path, tmp_path: Path) -> None:
    assert cli.base_ref(repo) == "main"
    assert cli.world_changed(repo, "main", WORLD)
    fixture = cli.prepare_change(repo, "main", WORLD, tmp_path, fixture_plan, "Logs for Priya")
    people = "terraform/people.tf"
    assert (fixture / "base" / people).read_text() == (FIXTURES / "intern/base" / people).read_text()
    assert (fixture / "head" / people).read_text() == (FIXTURES / "intern/head" / people).read_text()
    assert (fixture / "pr.md").read_text() == "# Logs for Priya\n"


def test_the_intern_change_is_blocked_with_its_path_lines_impact_and_fix(checked: AnalysisResult) -> None:
    text = check_text(checked)
    first, *rest = text.splitlines()
    assert first == "Theseus check: BLOCKED. priya-intern can reach customer-db."
    assert "Impact: Lands on support-engineers" in text
    assert "priya-intern is in support-engineers (terraform/people.tf:83, new)" in text
    assert "customer-db holds personal, payment or health data." in text
    assert any(line.startswith("Fix ") and "Tested on a copy of the graph" in line for line in rest)


def test_the_command_prints_the_check_and_exits_2_when_blocked(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "models", lambda settings: (None, RecordedJev()))
    monkeypatch.setattr(cli, "plan_json", lambda terraform, cache: fixture_plan(terraform))
    monkeypatch.setattr(cli, "get_client", lambda settings: None)
    monkeypatch.setattr(cli, "FalkorStore", lambda client: MemoryStore())
    assert cli.main(["check", "--world", WORLD]) == 2
    assert capsys.readouterr().out.startswith("Theseus check: BLOCKED.")


def _event(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def test_the_hook_denies_a_blocked_commit_once_then_asks(checked: AnalysisResult, tmp_path: Path) -> None:
    seen = tmp_path / ".theseus" / "denied"
    runs: list[Path] = []

    def run(repo: Path) -> AnalysisResult:
        runs.append(repo)
        return checked

    assert cli.hook(_event("ls -la", tmp_path), run, seen) == ""
    assert cli.hook({"tool_name": "Edit", "tool_input": {}}, run, seen) == ""
    assert runs == []  # only a commit, a push or a new PR is checked
    first = json.loads(cli.hook(_event('git commit -m "Logs for Priya"', tmp_path), run, seen))
    out = first["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert out["permissionDecisionReason"].startswith("Theseus check: BLOCKED.")
    assert "offer the fix" in out["permissionDecisionReason"]
    again = json.loads(cli.hook(_event("git commit -m again && git push", tmp_path), run, seen))
    assert again["hookSpecificOutput"]["permissionDecision"] == "ask"
    pr = json.loads(cli.hook(_event("gh pr create --fill", tmp_path), run, seen))
    assert pr["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_the_hook_lets_a_clear_or_unchanged_world_through(checked: AnalysisResult, tmp_path: Path) -> None:
    clear = checked.model_copy(update={"opened": [], "use_beyond_intent": [], "unknowns": []})
    seen = tmp_path / "denied"
    assert cli.hook(_event("git push", tmp_path), lambda repo: clear, seen) == ""
    assert cli.hook(_event("git push", tmp_path), lambda repo: None, seen) == ""
    assert not seen.exists()


def test_a_hook_that_cannot_check_lets_the_command_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    event = json.dumps(_event("git commit -m x", tmp_path))  # not a git repository
    monkeypatch.setattr("sys.stdin", io.StringIO(event))
    assert cli.main(["check", "--hook"]) == 0
    out = capsys.readouterr()
    assert out.out == "" and "the command runs unchecked" in out.err
