"""`tools/purge_test_graphs.py`: lists, and with `--yes` deletes, the graphs earlier `pytest -m falkordb` runs
leaked on a shared FalkorDB. The server is a fake, so nothing here touches a network.

The script is the one thing that deletes graphs it did not make, on an instance other people use, so most
of these tests are about what it must never select.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from redis.exceptions import ResponseError

from theseus.errors import GraphError

ROOT = Path(__file__).resolve().parents[2]


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("purge_test_graphs", ROOT / "tools/purge_test_graphs.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = load_tool()

# The prefixes issue #141 names: one per test that saves graphs under its own process id.
PREFIXES = [
    "e4_pipeline",
    "fm3_parity",
    "fm4_parity",
    "e4_parity",
    "parity",
    "smoke",
    "c3_scan",
    "reviewreads",
    "a6_mcp",
]
# What a real instance holds that is not a leaked test graph: the product's graphs, the fixtures the Try-it
# page and the MCP tests read, and the shared documents and benchmark graphs.
NOT_LEAKED = [
    "demo-infra__main",
    "demo-infra__main-fix-u",
    "demo-infra__base",
    "demo-infra__base-fix-k",
    "demo-infra__pr85-base",
    "demo-infra__pr85-fix-a",
    "demo-infra__pr85-head",
    "demo-infra__finding-ghsa-demo-0001",
    "fx__intern__base",
    "fx__intern__fix-a",
    "fx__code-pr__head",
    "fx__compromised-action__base-fix-k",
    "theseus__docs",
    "theseus__benchmark",
]
# Names that look like a leak at a glance and are not: the whole name must be `<prefix>__<digits>__<tail>`.
NEAR_MISSES = [
    "e4_pipeline__fix-a",  # no process id
    "e4_pipeline__x1__fix-a",  # the id is not a number
    "parity__12",  # nothing after the id
    "parity__12__",  # an empty tail
    "my_parity__12__a",  # not at the start
    "demo-infra__parity__12__a",  # not at the start
    "PARITY__12__a",  # the case differs
    "parity__٣٤__a",  # Arabic-Indic digits are not a process id
    "parity__12__a\n",  # a trailing newline must not slip past an end anchor
    "unknown__12__a",  # not one of the tests' prefixes
    "",
]


class FakeGraph:
    def __init__(self, db: FakeDb, name: str) -> None:
        self.db, self.name = db, name

    def delete(self) -> None:
        if self.name in self.db.refuse:
            raise ResponseError("command not allowed when used memory > 'maxmemory'")
        self.db.names.discard(self.name)
        self.db.deleted.append(self.name)


class FakeConnection:
    def __init__(self, db: FakeDb) -> None:
        self.db = db

    def info(self, section: str) -> dict[str, Any]:
        assert section == "memory"
        used = self.db.base_mb + self.db.graph_mb * len(self.db.names)
        return {"used_memory": int(used * 1e6), "maxmemory": int(self.db.limit_mb * 1e6)}


class FakeDb:
    """A FalkorDB that holds graph names and reports memory as a base plus 0.8 MB for each of them."""

    def __init__(self, *names: str, base_mb: float = 60.0, limit_mb: float = 104.8576) -> None:
        self.names = set(names)
        self.base_mb, self.graph_mb, self.limit_mb = base_mb, 0.8, limit_mb
        self.deleted: list[str] = []
        self.refuse: set[str] = set()
        self.connection = FakeConnection(self)

    def list_graphs(self) -> list[str]:
        return sorted(self.names)

    def select_graph(self, name: str) -> FakeGraph:
        return FakeGraph(self, name)


LEAKED = [
    "e4_pipeline__94766__fix-a",
    "e4_pipeline__94766__fix-c",
    "fm3_parity__3840__base-fix-k",
    "parity__21806__base",
]


def instance(*extra: str) -> FakeDb:
    return FakeDb(*LEAKED, *NOT_LEAKED, *extra)


# Which graphs it selects -------------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", PREFIXES)
def test_a_graph_a_test_left_under_its_process_id_is_selected(prefix: str) -> None:
    assert tool.is_leaked(f"{prefix}__94766__fix-a")
    assert tool.is_leaked(f"{prefix}__3840__base-fix-k")


@pytest.mark.parametrize("name", NOT_LEAKED)
def test_a_graph_that_is_not_a_leaked_test_graph_is_never_selected(name: str) -> None:
    assert not tool.is_leaked(name)


@pytest.mark.parametrize("name", NEAR_MISSES)
def test_a_name_that_only_looks_like_a_leak_is_not_selected(name: str) -> None:
    assert not tool.is_leaked(name)


def test_the_selection_is_sorted_and_leaves_everything_else_out() -> None:
    names = [*NOT_LEAKED, "parity__21806__head", *LEAKED, *NEAR_MISSES]
    assert tool.leaked_graphs(names) == sorted([*LEAKED, "parity__21806__head"])


def test_the_selection_of_an_instance_that_holds_none_is_empty() -> None:
    assert tool.leaked_graphs(NOT_LEAKED + NEAR_MISSES) == []
    assert tool.leaked_graphs([]) == []


def test_the_49_graphs_issue_141_counts_are_the_ones_selected() -> None:
    pids = [3840, 11120, 21806, 25975, 33949, 38139, 44672, 53008, 56561, 67070, 79258, 91575]
    leaked = [f"e4_pipeline__{pid}__fix-{fix}" for pid in pids for fix in "acd"]  # 36
    leaked += [f"fm3_parity__{pid}__base-fix-k" for pid in pids[:8]]  # 8
    leaked += [f"parity__21806__{name}" for name in ("base", "head", "fix-a", "fix-b", "copy")]  # 5
    assert len(leaked) == 49
    assert tool.leaked_graphs([*NOT_LEAKED, *leaked]) == sorted(leaked)


# The dry run -------------------------------------------------------------------------------------------


def test_a_dry_run_lists_the_graphs_and_the_memory_and_deletes_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    db = instance()
    before = sorted(db.names)
    assert tool.purge(db, "cloud.example:6380", yes=False) == 0
    out = capsys.readouterr().out
    for name in LEAKED:
        assert f"  {name}\n" in out
    assert "demo-infra__main" not in out and "fx__intern__base" not in out
    assert "cloud.example:6380" in out
    assert "4 graphs, about 3.2 MB" in out
    assert "MB used of 104.9 MB" in out
    assert "Dry run: nothing was deleted" in out and "--yes" in out
    assert db.deleted == [] and sorted(db.names) == before


def test_a_dry_run_says_there_is_nothing_to_delete_on_a_clean_instance(
    capsys: pytest.CaptureFixture[str],
) -> None:
    db = FakeDb(*NOT_LEAKED)
    assert tool.purge(db, "localhost:6379", yes=False) == 0
    out = capsys.readouterr().out
    assert "Nothing to delete" in out
    assert db.deleted == []


# Deleting ----------------------------------------------------------------------------------------------


def test_yes_deletes_exactly_the_leaked_graphs_by_name_and_prints_the_memory_before_and_after(
    capsys: pytest.CaptureFixture[str],
) -> None:
    db = instance()
    assert tool.purge(db, "cloud.example:6380", yes=True) == 0
    out = capsys.readouterr().out
    assert db.deleted == sorted(LEAKED)
    assert sorted(db.names) == sorted(NOT_LEAKED)
    for name in LEAKED:
        assert f"deleted {name}\n" in out
    assert "Deleted 4 graphs." in out
    before, after = 60.0 + 0.8 * (len(LEAKED) + len(NOT_LEAKED)), 60.0 + 0.8 * len(NOT_LEAKED)
    assert f"Memory: {before:.1f} MB before, {after:.1f} MB after (104.9 MB limit)." in out
    assert "Dry run" not in out


def test_yes_on_a_clean_instance_deletes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    db = FakeDb(*NOT_LEAKED)
    assert tool.purge(db, "localhost:6379", yes=True) == 0
    assert db.deleted == []
    assert "Nothing to delete" in capsys.readouterr().out


def test_a_graph_that_looks_like_a_leak_but_is_not_complete_survives_yes() -> None:
    db = instance(*NEAR_MISSES[:-1])  # the empty name cannot be a graph
    tool.purge(db, "localhost:6379", yes=True)
    assert set(NEAR_MISSES[:-1]) <= db.names


def test_the_deleter_refuses_a_name_that_is_not_a_leaked_test_graph_before_it_deletes_anything() -> None:
    db = instance()
    with pytest.raises(ValueError, match="demo-infra__main"):
        tool.delete_graphs(db, [LEAKED[0], "demo-infra__main", LEAKED[1]])
    assert db.deleted == []
    assert "demo-infra__main" in db.names and LEAKED[0] in db.names


def test_a_delete_the_server_refuses_stops_the_run_and_says_which_graph_and_how_many_went(
    capsys: pytest.CaptureFixture[str],
) -> None:
    db = instance()
    db.refuse = {"fm3_parity__3840__base-fix-k"}
    assert tool.purge(db, "cloud.example:6380", yes=True) == 1
    captured = capsys.readouterr()
    assert db.deleted == ["e4_pipeline__94766__fix-a", "e4_pipeline__94766__fix-c"]
    assert "fm3_parity__3840__base-fix-k" in captured.err
    assert "2 of 4" in captured.err
    assert "Deleted 4 graphs." not in captured.out
    assert set(NOT_LEAKED) <= db.names


# The command -------------------------------------------------------------------------------------------


class Settings:
    falkordb_host, falkordb_port = "cloud.example", 6380


def test_the_command_is_a_dry_run_unless_asked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = instance()
    monkeypatch.setattr(tool, "get_settings", Settings)
    monkeypatch.setattr(tool, "get_client", lambda settings: db)
    assert tool.main([]) == 0
    assert db.deleted == []
    assert "Dry run" in capsys.readouterr().out
    assert tool.main(["--yes"]) == 0
    assert db.deleted == sorted(LEAKED)


def test_the_command_exits_1_with_the_reason_when_it_cannot_reach_the_server(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(settings: object) -> None:
        raise GraphError("cannot reach FalkorDB at cloud.example:6380: ConnectionError")

    monkeypatch.setattr(tool, "get_settings", Settings)
    monkeypatch.setattr(tool, "get_client", refuse)
    assert tool.main(["--yes"]) == 1
    captured = capsys.readouterr()
    assert "cannot reach FalkorDB at cloud.example:6380" in captured.err
    assert captured.out == ""


def test_the_command_reports_a_server_that_will_not_say_its_memory(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = instance()
    monkeypatch.setattr(db.connection, "info", lambda section: {"redis_version": "8"})
    monkeypatch.setattr(tool, "get_settings", Settings)
    monkeypatch.setattr(tool, "get_client", lambda settings: db)
    assert tool.main(["--yes"]) == 0
    out = capsys.readouterr().out
    assert db.deleted == sorted(LEAKED)
    assert "memory is not available" in out
