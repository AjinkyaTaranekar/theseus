"""`python -m theseus prune`: a dry run by default that lists the graphs of closed and merged PRs, and with
`--yes` deletes exactly those, by name, and prints the memory before and after. FalkorDB is a MemoryStore
and GitHub a fake, so nothing here touches a network."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from typing import Any

import pytest

from theseus import cli
from theseus.cli import main
from theseus.config import Settings
from theseus.contracts.result import GraphRows, NodeRow
from theseus.errors import GitHubError, GraphError
from theseus.graph.client import Memory
from theseus.graph.store import MemoryStore

REPO, OTHER = "acme/infra", "acme/web"

# PR 1 closed, 2 merged, 3 open; PR 4 is not one GitHub lists; and graphs that are no PR's at all.
GRAPHS = [
    "demo-infra__main",
    "demo-infra__finding-ghsa-demo-0001",
    "demo-infra__pr1-base",
    "demo-infra__pr1-fix-a",
    "demo-infra__pr1-head",
    "demo-infra__pr2-base",
    "demo-infra__pr2-head",
    "demo-infra__pr3-base",
    "demo-infra__pr3-fix-a",
    "demo-infra__pr3-fix-b",
    "demo-infra__pr3-head",
    "demo-infra__pr4-head",
    "fx__intern__base",
    "fx__intern__head",
    "theseus__benchmark",
    "e4_pipeline__94766__fix-a",
]
DOOMED = [
    "demo-infra__pr1-base",
    "demo-infra__pr1-fix-a",
    "demo-infra__pr1-head",
    "demo-infra__pr2-base",
    "demo-infra__pr2-head",
]
STATES = {REPO: {1: "closed", 2: "merged", 3: "open"}}
BASE_MB, PER_GRAPH_MB, LIMIT_MB = 80.0, 0.8, 105.0


class FakeGitHub:
    def __init__(self, states: dict[str, dict[int, str]], error: Exception | None = None) -> None:
        self.states, self.error, self.asked = states, error, []

    def pull_states(self, repo: str) -> dict[int, str]:
        self.asked.append(repo)
        if self.error is not None:
            raise self.error
        return dict(self.states[repo])


class Setup:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        self.store = MemoryStore()
        for name in GRAPHS:
            self.store.load(name, GraphRows(nodes=[NodeRow(id="a", labels=["Node"], name="a")]))
        self.store.put_doc("review:acme/infra#1", "{}")
        self.github = FakeGitHub({repo: dict(states) for repo, states in STATES.items()})
        self.settings = Settings(_env_file=None, theseus_repos=REPO)
        self.install()

    def install(self) -> None:
        mp = self.monkeypatch
        mp.setattr(cli, "get_settings", lambda: self.settings)
        mp.setattr(cli, "get_client", lambda settings: object())
        mp.setattr(cli, "FalkorStore", lambda client: self.store)
        mp.setattr(cli, "GitHub", lambda settings: self.github)
        mp.setattr(cli, "memory", self.memory)

    def memory(self, db: Any) -> Memory:
        used = BASE_MB + PER_GRAPH_MB * len(self.store.list_graphs())
        return Memory(used_mb=used, limit_mb=LIMIT_MB)

    def run(self, *argv: str) -> int:
        return main(["prune", *argv])


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch) -> Setup:
    return Setup(monkeypatch)


def used(count: int) -> str:
    return f"{BASE_MB + PER_GRAPH_MB * count:.1f}"


def test_help_lists_prune() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "theseus", "--help"], capture_output=True, text=True, check=True
    )
    assert "prune" in out.stdout


def test_prune_is_a_dry_run_unless_told_otherwise(setup: Setup, capsys: pytest.CaptureFixture[str]) -> None:
    assert setup.run() == 0
    out = capsys.readouterr().out
    assert setup.store.list_graphs() == sorted(GRAPHS)
    for name in DOOMED:
        assert name in out
    assert "#1 closed" in out and "#2 merged" in out
    assert "5 graphs" in out and "about 4.0 MB" in out
    assert f"{used(len(GRAPHS))} MB used of {LIMIT_MB} MB" in out
    assert "Dry run" in out and "--yes" in out and "nothing was deleted" in out.lower()


def test_prune_lists_what_it_keeps_and_never_names_graphs_that_are_not_prs(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    assert setup.run() == 0
    out = capsys.readouterr().out
    assert "#3 open" in out and "#4" in out and "not in GitHub's list" in out
    for name in set(GRAPHS) - set(DOOMED):
        assert name not in out, f"{name} should not be listed for deletion"


def test_prune_with_yes_deletes_exactly_the_listed_graphs_and_prints_the_memory_before_and_after(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    assert setup.run("--yes") == 0
    out = capsys.readouterr().out
    assert setup.store.list_graphs() == sorted(set(GRAPHS) - set(DOOMED))
    assert [line.split()[-1] for line in out.splitlines() if line.startswith("deleted ")] == DOOMED
    assert "Deleted 5 graphs" in out
    assert f"{used(len(GRAPHS))} MB before" in out and f"{used(len(GRAPHS) - 5)} MB after" in out
    assert setup.store.get_doc("review:acme/infra#1") == "{}"  # the review survives


def test_prune_never_deletes_main_fixtures_the_documents_the_benchmark_or_an_open_prs_graphs(
    setup: Setup,
) -> None:
    setup.github.states[REPO] = dict.fromkeys(range(0, 100), "closed") | {3: "open"}
    assert setup.run("--yes") == 0
    assert setup.store.list_graphs() == sorted(
        [
            "demo-infra__main",
            "demo-infra__finding-ghsa-demo-0001",
            "demo-infra__pr3-base",
            "demo-infra__pr3-fix-a",
            "demo-infra__pr3-fix-b",
            "demo-infra__pr3-head",
            "fx__intern__base",
            "fx__intern__head",
            "theseus__benchmark",
            "e4_pipeline__94766__fix-a",
        ]
    )


def test_a_pr_open_in_any_repo_keeps_its_graphs(setup: Setup) -> None:
    setup.settings = Settings(_env_file=None, theseus_repos=f"{REPO},{OTHER}")
    setup.github.states[OTHER] = {1: "open", 2: "closed"}
    assert setup.run("--yes") == 0
    remaining = set(setup.store.list_graphs())
    assert {"demo-infra__pr1-base", "demo-infra__pr1-fix-a", "demo-infra__pr1-head"} <= remaining
    assert not remaining & {"demo-infra__pr2-base", "demo-infra__pr2-head"}
    assert sorted(setup.github.asked) == [REPO, OTHER]


def test_a_world_root_names_the_graphs_prune_considers(setup: Setup) -> None:
    setup.settings = Settings(_env_file=None, theseus_repos=REPO, theseus_world_root="other-world")
    assert setup.run("--yes") == 0
    assert setup.store.list_graphs() == sorted(GRAPHS)


def test_prune_with_yes_and_nothing_to_delete_says_so(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    setup.github.states[REPO] = {3: "open"}
    assert setup.run("--yes") == 0
    out = capsys.readouterr().out
    assert "Nothing to delete" in out
    assert setup.store.list_graphs() == sorted(GRAPHS)


def test_without_repos_prune_stops_before_it_asks_anyone(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    setup.settings = Settings(_env_file=None, theseus_repos="")
    assert setup.run("--yes") == 1
    assert "THESEUS_REPOS" in capsys.readouterr().err
    assert setup.github.asked == [] and setup.store.list_graphs() == sorted(GRAPHS)


def test_when_github_cannot_say_which_prs_are_closed_nothing_is_deleted(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    setup.github.error = GitHubError("GET /repos/acme/infra/pulls: 401 Bad credentials")
    assert setup.run("--yes") == 1
    assert "401" in capsys.readouterr().err
    assert setup.store.list_graphs() == sorted(GRAPHS)


def test_prune_refuses_to_run_without_falkordb(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unreachable(settings: object) -> None:
        raise GraphError("cannot reach FalkorDB at example:1")

    monkeypatch.setattr(cli, "get_client", unreachable)
    assert setup.run() == 1
    assert "cannot reach FalkorDB" in capsys.readouterr().err


def test_a_delete_that_fails_stops_the_run_and_says_how_far_it_got(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real: Callable[[str], None] = setup.store.delete

    def flaky(graph: str) -> None:
        if graph == "demo-infra__pr2-base":
            raise GraphError(f"cannot delete {graph}: out of memory")
        real(graph)

    monkeypatch.setattr(setup.store, "delete", flaky)
    assert setup.run("--yes") == 1
    out = capsys.readouterr()
    assert "cannot delete demo-infra__pr2-base" in out.err
    assert "deleted demo-infra__pr1-head" in out.out and "deleted demo-infra__pr2-head" not in out.out
    assert "demo-infra__pr2-head" in setup.store.list_graphs()


def test_a_server_that_cannot_report_its_memory_still_prunes(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def silent(db: Any) -> Memory:
        raise GraphError("cannot read the memory: INFO is disabled")

    monkeypatch.setattr(cli, "memory", silent)
    assert setup.run("--yes") == 0
    out = capsys.readouterr().out
    assert "Deleted 5 graphs" in out and "memory is not available" in out
    assert setup.store.list_graphs() == sorted(set(GRAPHS) - set(DOOMED))
