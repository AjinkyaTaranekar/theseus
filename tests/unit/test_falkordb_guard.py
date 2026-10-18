"""The guard that fails a FalkorDB test module when it leaves a graph on the shared instance."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests import falkordb_guard as guard
from tests.falkordb_guard import (
    FULL_RUN_MB,
    GraphLedger,
    drop_unused_docs_graph,
    headroom_problem,
    refuse_a_full_instance,
)
from theseus.errors import GraphError
from theseus.graph.store import DOCS


class FakeGraph:
    def __init__(self, db: FakeClient, name: str) -> None:
        self.db, self.name = db, name

    def query(self, cypher: str) -> SimpleNamespace:
        self.db.names.add(self.name)
        return SimpleNamespace(result_set=[[self.db.docs]])

    def copy(self, clone: str) -> FakeGraph:
        self.db.names.add(clone)
        return FakeGraph(self.db, clone)

    def delete(self) -> None:
        self.db.names.discard(self.name)


class FakeClient:
    def __init__(self, *names: str, docs: int = 0) -> None:
        self.names = set(names)
        self.docs = docs

    def select_graph(self, graph_id: str) -> FakeGraph:
        return FakeGraph(self, graph_id)

    def list_graphs(self) -> list[str]:
        return sorted(self.names)


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> GraphLedger:
    ledger = GraphLedger()
    ledger.install(monkeypatch, FakeClient, FakeGraph)
    return ledger


def leaked(ledger: GraphLedger, db: FakeClient, before: list[str]) -> list[str]:
    return ledger.left_behind(before, db.list_graphs())


def test_a_graph_the_test_made_and_kept_is_left_behind(ledger: GraphLedger) -> None:
    db = FakeClient()
    db.select_graph("mine__head").query("CREATE ()")
    db.select_graph("mine__head-fix-a").query("CREATE ()")
    assert leaked(ledger, db, before=[]) == ["mine__head", "mine__head-fix-a"]


def test_a_graph_made_by_copy_is_left_behind_though_it_was_never_selected(ledger: GraphLedger) -> None:
    db = FakeClient("src")
    db.select_graph("src").copy("dst")
    assert leaked(ledger, db, before=["src"]) == ["dst"]


def test_a_graph_the_test_deleted_is_not_left_behind(ledger: GraphLedger) -> None:
    db = FakeClient()
    db.select_graph("mine").query("CREATE ()")
    db.select_graph("mine").delete()
    assert leaked(ledger, db, before=[]) == []


def test_a_graph_another_run_made_is_not_ours(ledger: GraphLedger) -> None:
    db = FakeClient()
    db.select_graph("mine").query("CREATE ()")
    db.names.add("theirs")  # it appears while the module runs, but this process never touched it
    db.select_graph("mine").delete()
    assert leaked(ledger, db, before=[]) == []


def test_a_graph_that_was_already_there_is_not_left_behind(ledger: GraphLedger) -> None:
    db = FakeClient("old")
    db.select_graph("old").query("MATCH (n) RETURN n")
    assert leaked(ledger, db, before=["old"]) == []


def test_the_documents_graph_is_a_shared_graph_the_product_makes_itself(ledger: GraphLedger) -> None:
    db = FakeClient()
    db.select_graph(DOCS).query("MERGE (d:Doc)")
    assert leaked(ledger, db, before=[]) == []


def test_the_patch_is_undone_when_the_test_ends() -> None:
    original: Any = FakeClient.select_graph
    ledger = GraphLedger()
    with pytest.MonkeyPatch.context() as patch:
        ledger.install(patch, FakeClient, FakeGraph)
        assert FakeClient.select_graph is not original
    assert FakeClient.select_graph is original
    FakeClient().select_graph("after")
    assert ledger.touched == set()


def test_a_documents_graph_this_run_made_and_emptied_is_dropped() -> None:
    db = FakeClient(DOCS, docs=0)
    assert drop_unused_docs_graph(db, before=[]) is True
    assert db.list_graphs() == []


def test_a_documents_graph_that_was_already_there_stays() -> None:
    db = FakeClient(DOCS, docs=0)
    assert drop_unused_docs_graph(db, before=[DOCS]) is False
    assert db.list_graphs() == [DOCS]


def test_a_documents_graph_that_holds_a_document_stays() -> None:
    db = FakeClient(DOCS, docs=1)
    assert drop_unused_docs_graph(db, before=[]) is False
    assert db.list_graphs() == [DOCS]


def test_there_is_nothing_to_drop_when_no_documents_graph_exists() -> None:
    db = FakeClient("other")
    assert drop_unused_docs_graph(db, before=[]) is False
    assert db.list_graphs() == ["other"]


# The room a full run needs ---------------------------------------------------------------------------------


class FakeConnection:
    def __init__(self, info: dict[str, Any] | Exception) -> None:
        self.result = info
        self.asked = 0

    def info(self, section: str) -> dict[str, Any]:
        self.asked += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeServer:
    """A FalkorDB that reports the memory it is given, as `INFO memory` does."""

    def __init__(self, used_mb: float, limit_mb: float | None = 104.8576) -> None:
        info: dict[str, Any] = {"used_memory": int(used_mb * 1e6)}
        if limit_mb is not None:
            info["maxmemory"] = int(limit_mb * 1e6)
        self.connection = FakeConnection(info)


def test_an_instance_with_room_for_a_full_run_is_not_refused() -> None:
    assert headroom_problem(FakeServer(used_mb=60.0), "cloud.example:6380") is None


def test_an_instance_a_few_megabytes_short_is_refused_with_the_numbers() -> None:
    problem = headroom_problem(FakeServer(used_mb=96.1, limit_mb=104.9), "cloud.example:6380")
    assert problem is not None
    assert "cloud.example:6380" in problem
    assert "96.1 of 104.9 MB used" in problem and "8.8 MB free" in problem
    assert f"about {FULL_RUN_MB:.0f} MB" in problem


def test_the_refusal_says_what_to_do_about_it() -> None:
    problem = headroom_problem(FakeServer(used_mb=99.0), "cloud.example:6380")
    assert problem is not None
    assert "python tools/purge_test_graphs.py" in problem and "--yes" in problem
    assert "python -m theseus prune" in problem
    assert "AGENTS.md" in problem and "your own machine" in problem
    assert "no test was run" in problem


def test_exactly_the_room_a_full_run_needs_is_enough() -> None:
    assert headroom_problem(FakeServer(used_mb=90.0, limit_mb=90.0 + FULL_RUN_MB), "x:1") is None
    assert headroom_problem(FakeServer(used_mb=90.0, limit_mb=90.0 + FULL_RUN_MB - 0.1), "x:1") is not None


def test_a_server_with_no_memory_limit_is_never_refused() -> None:
    assert headroom_problem(FakeServer(used_mb=5000.0, limit_mb=None), "localhost:6379") is None
    assert headroom_problem(FakeServer(used_mb=5000.0, limit_mb=0), "localhost:6379") is None


def test_a_server_that_will_not_say_its_memory_is_not_refused_but_the_log_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = FakeServer(used_mb=0)
    server.connection = FakeConnection({"redis_version": "8.0"})
    with caplog.at_level("WARNING"):
        assert headroom_problem(server, "cloud.example:6380") is None
    assert "cannot read the memory of FalkorDB" in caplog.text


def test_the_room_is_measured_against_a_full_run_not_a_graph() -> None:
    assert FULL_RUN_MB == 11.0


class FakeItem:
    def __init__(self, *keywords: str, skip: bool = False) -> None:
        self.keywords = dict.fromkeys(keywords, 1)
        self.skip = skip

    def get_closest_marker(self, name: str) -> object | None:
        return object() if name == "skip" and self.skip else None


class FakeSession:
    def __init__(self, *items: FakeItem, collect_only: bool = False) -> None:
        self.items = list(items)
        self.config = SimpleNamespace(option=SimpleNamespace(collectonly=collect_only))


class Connections:
    """Stands in for `get_client`: hands out `server` (or raises it) and counts the connections made."""

    def __init__(self) -> None:
        self.server: Any = FakeServer(used_mb=99.0)
        self.opened = 0

    def __call__(self, settings: object) -> Any:
        self.opened += 1
        if isinstance(self.server, Exception):
            raise self.server
        return self.server


@pytest.fixture
def connects(monkeypatch: pytest.MonkeyPatch) -> Connections:
    connections = Connections()
    where = SimpleNamespace(falkordb_host="cloud.example", falkordb_port=6380)
    monkeypatch.setattr(guard, "get_client", connections)
    monkeypatch.setattr(guard, "get_settings", lambda: where)
    return connections


def test_a_run_that_will_use_a_nearly_full_instance_stops_before_its_first_test(
    connects: Connections,
) -> None:
    with pytest.raises(pytest.exit.Exception) as stopped:
        refuse_a_full_instance(FakeSession(FakeItem("falkordb")))
    assert "cloud.example:6380" in stopped.value.msg
    assert "no test was run" in stopped.value.msg
    assert stopped.value.returncode == 2


def test_a_run_with_room_goes_ahead(connects: Connections) -> None:
    connects.server = FakeServer(used_mb=50.0)
    refuse_a_full_instance(FakeSession(FakeItem("falkordb")))
    assert connects.opened == 1


def test_a_default_run_never_connects(connects: Connections) -> None:
    refuse_a_full_instance(FakeSession(FakeItem(), FakeItem("falkordb", skip=True), FakeItem("live")))
    refuse_a_full_instance(FakeSession())
    assert connects.opened == 0


def test_listing_the_tests_never_connects(connects: Connections) -> None:
    refuse_a_full_instance(FakeSession(FakeItem("falkordb"), collect_only=True))
    assert connects.opened == 0


def test_an_instance_that_cannot_be_reached_is_left_to_the_tests_to_report(
    connects: Connections, caplog: pytest.LogCaptureFixture
) -> None:
    connects.server = GraphError("cannot reach FalkorDB at cloud.example:6380")
    with caplog.at_level("WARNING"):
        refuse_a_full_instance(FakeSession(FakeItem("falkordb")))
    assert "cannot reach FalkorDB" in caplog.text
