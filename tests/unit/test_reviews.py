"""The review page's reads from the store: concurrent graph reads, one fewer round trip per fix, and a short
process-local cache that a new save clears."""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from collections.abc import Iterator
from typing import Any

import pytest

from theseus.api import reviews
from theseus.contracts.result import GraphRows, NodeRow
from theseus.errors import GraphError
from theseus.graph.store import GraphView, MemoryStore

KEY = reviews.key("acme/infra", 7)
BASE, HEAD, FIX_B = "acme__pr7-base", "acme__pr7-head", "acme__pr7-fix-b"


def rows(*ids: str) -> GraphRows:
    return GraphRows(nodes=[NodeRow(id=i, labels=["Node"], name=i) for i in ids])


class SpyStore(MemoryStore):
    """A MemoryStore that counts each read, and can make `view` wait for its twin to prove they overlap."""

    def __init__(self, meet: bool = False) -> None:
        super().__init__()
        self.calls: Counter[str] = Counter()
        self.threads: set[int] = set()
        self._barrier = threading.Barrier(2, timeout=5) if meet else None

    def get_doc(self, key: str) -> str | None:
        self.calls["get_doc"] += 1
        return super().get_doc(key)

    def list_graphs(self) -> list[str]:
        self.calls["list_graphs"] += 1
        return super().list_graphs()

    def view(self, graph: str) -> GraphView:
        self.calls["view"] += 1
        self.threads.add(threading.get_ident())
        if self._barrier is not None and graph in (BASE, HEAD):
            self._barrier.wait()  # only returns once the other graph's read is also under way
        return super().view(graph)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(reviews, "_cache", reviews.ReadCache(clock=fake))
    return fake


def doc(graphs: dict[str, str] | None = None) -> str:
    graphs = {"head": HEAD, "base": BASE} if graphs is None else graphs
    result = {
        "graphs": graphs,
        "candidates": [{"id": "B", "verdict": "pass", "title": "Tighten", "recommended": True, "ops": []}],
    }
    return json.dumps({"repo": "acme/infra", "number": 7, "result": result})


def seeded(meet: bool = False) -> SpyStore:
    store = SpyStore(meet=meet)
    store.load(BASE, rows("a"))
    store.load(HEAD, rows("a", "b"))
    store.load(FIX_B, rows("a", "c"))
    store.put_doc(KEY, doc())
    return store


def reset(store: SpyStore) -> None:
    store.calls.clear()
    store.threads.clear()


def test_both_graphs_are_returned_in_the_results_order(clock: Clock) -> None:
    store = seeded()
    page = reviews.page_doc(store, KEY)
    assert page is not None
    assert list(page["graphs"]) == ["head", "base"]
    assert page["graphs"]["head"] == {"name": HEAD, **store.view(HEAD)}
    assert page["graphs"]["base"] == {"name": BASE, **store.view(BASE)}


def test_the_two_graphs_are_read_at_the_same_time(clock: Clock) -> None:
    store = seeded(meet=True)  # a sequential read would time out on the barrier
    page = reviews.page_doc(store, KEY)
    assert page is not None and set(page["graphs"]) == {"head", "base"}
    assert len(store.threads) == 2


def test_a_page_costs_one_document_read_and_one_view_per_graph(clock: Clock) -> None:
    store = seeded()
    reviews.page_doc(store, KEY)
    assert dict(store.calls) == {"get_doc": 1, "view": 2}


def test_a_fix_costs_a_document_read_and_a_view_not_a_listing(clock: Clock) -> None:
    store = seeded()
    fix = reviews.fix_graph(store, KEY, "B")
    assert fix is not None and fix["name"] == FIX_B and fix["recommended"] is True
    assert {n["id"] for n in fix["nodes"]} == {"a", "c"}
    assert dict(store.calls) == {"get_doc": 1, "view": 1}


def test_a_deleted_graph_is_left_out_of_the_page(clock: Clock) -> None:
    store = seeded()
    store.delete(BASE)
    page = reviews.page_doc(store, KEY)
    assert page is not None and list(page["graphs"]) == ["head"]


def test_a_review_with_no_graphs_has_an_empty_page(clock: Clock) -> None:
    store = seeded()
    store.put_doc(KEY, doc({}))
    page = reviews.page_doc(store, KEY)
    assert page is not None and page["graphs"] == {}


def test_a_missing_review_is_none_and_is_not_cached(clock: Clock) -> None:
    store = SpyStore()
    assert reviews.page_doc(store, KEY) is None
    store.put_doc(KEY, doc())
    store.load(HEAD, rows("a"))
    assert reviews.page_doc(store, KEY) is not None


def test_a_deleted_fix_graph_is_none_not_an_error(clock: Clock) -> None:
    store = seeded()
    store.delete(FIX_B)
    assert reviews.fix_graph(store, KEY, "B") is None


def test_an_unknown_candidate_or_review_is_none(clock: Clock) -> None:
    store = seeded()
    assert reviews.fix_graph(store, KEY, "Z") is None
    assert reviews.fix_graph(store, reviews.key("acme/infra", 99), "B") is None


def test_a_store_that_fails_for_another_reason_still_raises(clock: Clock) -> None:
    class Broken(SpyStore):
        def view(self, graph: str) -> GraphView:
            raise GraphError("cannot reach FalkorDB")

    store = Broken()
    store.load(HEAD, rows("a"))
    store.load(FIX_B, rows("a"))
    store.put_doc(KEY, doc())
    with pytest.raises(GraphError):
        reviews.fix_graph(store, KEY, "B")


def test_a_repeated_page_read_is_served_without_touching_the_store(clock: Clock) -> None:
    store = seeded()
    first = reviews.page_doc(store, KEY)
    reset(store)
    assert reviews.page_doc(store, KEY) == first
    assert not store.calls


def test_a_repeated_fix_read_is_served_without_touching_the_store(clock: Clock) -> None:
    store = seeded()
    first = reviews.fix_graph(store, KEY, "B")
    reset(store)
    assert reviews.fix_graph(store, KEY, "B") == first
    assert not store.calls


def test_the_cache_expires_after_thirty_seconds(clock: Clock) -> None:
    store = seeded()
    reviews.page_doc(store, KEY)
    reviews.fix_graph(store, KEY, "B")
    reset(store)
    clock.now += 29.9
    reviews.page_doc(store, KEY)
    reviews.fix_graph(store, KEY, "B")
    assert not store.calls
    clock.now += 0.2
    reviews.page_doc(store, KEY)
    reviews.fix_graph(store, KEY, "B")
    assert store.calls["view"] == 3  # two graphs and the fix again


def test_save_clears_that_prs_cached_reads(clock: Clock) -> None:
    from theseus.api import routes

    store = seeded()
    other = reviews.key("acme/infra", 8)
    store.put_doc(other, doc())
    reviews.page_doc(store, KEY)
    reviews.fix_graph(store, KEY, "B")
    reviews.page_doc(store, other)
    reset(store)

    result = routes.stub_for("sample", "pr")
    reviews.save(store, "acme/infra", 7, ("b" * 40, "h" * 40), "demo-infra", result)
    reset(store)

    page = reviews.page_doc(store, KEY)
    assert page is not None and page["head_sha"] == "h" * 40
    assert store.calls["get_doc"] == 1
    reviews.fix_graph(store, KEY, "B")
    store.calls.clear()
    reviews.page_doc(store, other)
    assert not store.calls  # PR 8 kept its entry


def test_each_candidate_is_cached_on_its_own(clock: Clock) -> None:
    store = seeded()
    both = json.loads(doc())
    both["result"]["candidates"].append({"id": "C", "verdict": "pass", "title": "Other", "ops": []})
    store.put_doc(KEY, json.dumps(both))
    store.load("acme__pr7-fix-c", rows("z"))
    b, c = reviews.fix_graph(store, KEY, "B"), reviews.fix_graph(store, KEY, "C")
    assert b is not None and c is not None and b["name"] != c["name"]


def test_the_cache_is_not_shared_between_stores(clock: Clock) -> None:
    one, two = seeded(), seeded()
    two.delete(BASE)
    first, second = reviews.page_doc(one, KEY), reviews.page_doc(two, KEY)
    assert first is not None and second is not None
    assert list(first["graphs"]) == ["head", "base"] and list(second["graphs"]) == ["head"]


def test_the_cache_holds_at_most_sixty_four_entries(clock: Clock) -> None:
    store = seeded()
    for n in range(100, 100 + 70):
        store.put_doc(reviews.key("acme/infra", n), doc())
        reviews.page_doc(store, reviews.key("acme/infra", n))
    assert len(reviews._cache) == 64
    reset(store)
    reviews.page_doc(store, reviews.key("acme/infra", 169))  # the newest stays
    assert not store.calls
    reviews.page_doc(store, reviews.key("acme/infra", 100))  # the oldest was dropped
    assert store.calls["get_doc"] == 1


def test_each_read_logs_its_elapsed_milliseconds(clock: Clock, caplog: pytest.LogCaptureFixture) -> None:
    store = seeded()
    with caplog.at_level(logging.INFO, logger="theseus.api.reviews"):
        reviews.page_doc(store, KEY)
        reviews.fix_graph(store, KEY, "B")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert " ms" in text and "page" in text and "fix B" in text


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(reviews, "_cache", reviews.ReadCache())
    yield


def test_the_default_clock_is_not_the_wall_clock() -> None:
    cache: Any = reviews.ReadCache()
    assert cache.clock.__name__ == "monotonic"
