"""Closing a PR deletes the same graphs from FalkorDB as from MemoryStore, and `prune` plans the same
deletions on both. Also the memory `prune` prints before and after.

Against the FalkorDB in .env, or CI's pinned container. Every graph this test makes is deleted.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import pytest

from theseus.api import reviews
from theseus.config import get_settings
from theseus.contracts.result import EdgeRow, GraphRows, NodeRow
from theseus.engine import pr_graphs
from theseus.graph.client import get_client, memory
from theseus.graph.store import FalkorStore, MemoryStore

pytestmark = pytest.mark.falkordb

WORLD = f"hygiene{os.getpid()}"
REPO = f"hygiene-test/pid-{os.getpid()}"
KEY = reviews.key(REPO, 7)
SEVEN = [f"{WORLD}__pr7-base", f"{WORLD}__pr7-fix-a", f"{WORLD}__pr7-fix-c", f"{WORLD}__pr7-head"]
OTHERS = [f"{WORLD}__main", f"{WORLD}__pr70-head", f"{WORLD}__pr8-head", f"{WORLD}__pr8-fix-a"]


def rows() -> GraphRows:
    return GraphRows(
        nodes=[
            NodeRow(id="user:a", labels=["Node"], name="a"),
            NodeRow(id="db:b", labels=["Node"], name="b"),
        ],
        edges=[EdgeRow(eid="e1", type="MEMBER_OF", src="user:a", dst="db:b", kind="configured")],
    )


@pytest.fixture
def stores() -> Iterator[tuple[FalkorStore, MemoryStore]]:
    falkor = FalkorStore(get_client(get_settings()))
    local = MemoryStore()
    try:
        for store in (falkor, local):
            for name in (*SEVEN, *OTHERS):
                store.load(name, rows())
        yield falkor, local
    finally:
        for name in falkor.list_graphs():
            if name.startswith(f"{WORLD}__"):
                falkor.delete(name)


def mine(store: FalkorStore | MemoryStore) -> list[str]:
    return [n for n in store.list_graphs() if n.startswith(f"{WORLD}__")]


def test_closing_a_pr_deletes_the_same_graphs_from_both_stores(
    stores: tuple[FalkorStore, MemoryStore],
) -> None:
    falkor, local = stores
    assert mine(falkor) == mine(local) == sorted([*SEVEN, *OTHERS])
    from_falkor = pr_graphs.delete_pr_graphs(falkor, WORLD, 7)
    from_memory = pr_graphs.delete_pr_graphs(local, WORLD, 7)
    assert from_falkor == from_memory == SEVEN
    assert mine(falkor) == mine(local) == sorted(OTHERS)
    assert pr_graphs.delete_pr_graphs(falkor, WORLD, 7) == []  # already gone: no error


def test_the_review_survives_the_close_and_says_its_graphs_are_gone(
    stores: tuple[FalkorStore, MemoryStore],
) -> None:
    falkor, local = stores
    doc = json.dumps(
        {
            "repo": REPO,
            "number": 7,
            "result": {"graphs": {"head": SEVEN[3], "base": SEVEN[0]}, "candidates": []},
        }
    )
    try:
        for store in (falkor, local):
            store.put_doc(KEY, doc)
        reviews._cache.clear(KEY)
        before = reviews.page_doc(falkor, KEY)
        assert before is not None and sorted(before["graphs"]) == ["base", "head"]
        for store in (falkor, local):
            reviews.drop_graphs(store, WORLD, REPO, 7)
        after_falkor, after_memory = reviews.page_doc(falkor, KEY), reviews.page_doc(local, KEY)
        assert after_falkor is not None and after_falkor == after_memory
        assert after_falkor["graphs"] == {} and after_falkor["graphs_removed"] == ["base", "head"]
    finally:
        falkor.db.select_graph("theseus__docs").query("MATCH (d:Doc {key: $key}) DELETE d", {"key": KEY})


def test_prune_plans_the_same_deletions_from_both_stores(stores: tuple[FalkorStore, MemoryStore]) -> None:
    falkor, local = stores
    states = {7: "closed", 8: "open"}
    plans = [pr_graphs.plan_prune(store.list_graphs(), WORLD, states) for store in (falkor, local)]
    assert plans[0] == plans[1]
    assert plans[0].names == SEVEN
    assert [(g.number, g.state) for g in plans[0].keep] == [(8, "open"), (70, "unknown")]


def test_the_memory_prune_prints_is_a_number_from_the_server() -> None:
    db = get_client(get_settings())
    reading = memory(db)
    assert reading.used_mb > 0
    assert reading.limit_mb is None or reading.limit_mb >= reading.used_mb
