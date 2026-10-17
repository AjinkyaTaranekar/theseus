"""The review page reads give the same answers from FalkorDB as from MemoryStore (page_doc and fix_graph),
including for a graph that was deleted.

Against the FalkorDB in .env, or CI's pinned container. Every graph and document this test makes is deleted.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import pytest

from theseus.api import reviews
from theseus.config import get_settings
from theseus.contracts.result import EdgeRow, GraphRows, NodeRow
from theseus.graph.client import get_client
from theseus.graph.store import DOCS, FalkorStore, MemoryStore

pytestmark = pytest.mark.falkordb

PREFIX = f"reviewreads__{os.getpid()}__"
KEY = reviews.key(f"a9-test/pid-{os.getpid()}", 7)
BASE, HEAD, FIX_B = f"{PREFIX}pr7-base", f"{PREFIX}pr7-head", f"{PREFIX}pr7-fix-b"


def rows(*ids: str) -> GraphRows:
    nodes = [NodeRow(id=i, labels=["Node"], name=i) for i in ids]
    edges = [
        EdgeRow(eid=f"e{n}", type="MEMBER_OF", src=a, dst=b, kind="configured")
        for n, (a, b) in enumerate(zip(ids, ids[1:], strict=False))
    ]
    return GraphRows(nodes=nodes, edges=edges)


DOC = json.dumps(
    {
        "repo": "a9-test/pid",
        "number": 7,
        "result": {
            "graphs": {"head": HEAD, "base": BASE},
            "candidates": [{"id": "B", "verdict": "pass", "title": "Tighten", "ops": []}],
        },
    }
)


@pytest.fixture(scope="module")
def stores() -> Iterator[tuple[FalkorStore, MemoryStore]]:
    falkor = FalkorStore(get_client(get_settings()))
    memory = MemoryStore()
    for store in (falkor, memory):
        store.load(BASE, rows("user:a", "role:b"))
        store.load(HEAD, rows("user:a", "role:b", "db:c"))
        store.load(FIX_B, rows("user:a", "db:c"))
        store.put_doc(KEY, DOC)
    yield falkor, memory
    for name in (BASE, HEAD, FIX_B):
        falkor.delete(name)
    falkor.db.select_graph(DOCS).query("MATCH (d:Doc {key: $key}) DELETE d", {"key": KEY})


def test_the_page_is_the_same_from_both_stores(stores: tuple[FalkorStore, MemoryStore]) -> None:
    falkor, memory = stores
    from_falkor, from_memory = reviews.page_doc(falkor, KEY), reviews.page_doc(memory, KEY)
    assert from_falkor is not None and from_memory is not None
    assert list(from_falkor["graphs"]) == list(from_memory["graphs"]) == ["head", "base"]
    assert from_falkor == from_memory


def test_a_fix_is_the_same_from_both_stores(stores: tuple[FalkorStore, MemoryStore]) -> None:
    falkor, memory = stores
    from_falkor, from_memory = reviews.fix_graph(falkor, KEY, "B"), reviews.fix_graph(memory, KEY, "B")
    assert from_falkor is not None and from_falkor == from_memory
    assert reviews.fix_graph(falkor, KEY, "Z") is None and reviews.fix_graph(memory, KEY, "Z") is None


def test_a_deleted_graph_gives_the_same_answer_from_both_stores() -> None:
    falkor, memory = FalkorStore(get_client(get_settings())), MemoryStore()
    name = f"{PREFIX}gone"
    gone_key = reviews.key(f"a9-test/pid-{os.getpid()}", 8)
    doc = json.dumps(
        {
            "result": {
                "graphs": {"head": f"{name}-head", "base": BASE},
                "candidates": [{"id": "B", "verdict": "pass", "title": "t", "ops": []}],
            }
        }
    )
    try:
        for store in (falkor, memory):
            store.load(BASE, rows("user:a"))
            store.put_doc(gone_key, doc)
        for store in (falkor, memory):
            page = reviews.page_doc(store, gone_key)
            assert page is not None and list(page["graphs"]) == ["base"]
            assert reviews.fix_graph(store, gone_key, "B") is None
    finally:
        falkor.delete(BASE)
        falkor.db.select_graph(DOCS).query("MATCH (d:Doc {key: $key}) DELETE d", {"key": gone_key})
