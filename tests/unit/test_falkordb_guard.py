"""The guard that fails a FalkorDB test module when it leaves a graph on the shared instance."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests.falkordb_guard import GraphLedger, drop_unused_docs_graph
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
