"""Shared test setup: marked tests run only when their environment is available."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from tests.falkordb_guard import GraphLedger, drop_unused_docs_graph


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep the default run offline.

    `falkordb` tests run when asked for with `-m falkordb` (they read the FalkorDB settings from .env) or when
    FALKORDB_HOST is set, as in CI. `live` tests run only with THESEUS_LIVE=1.
    """
    asked = "falkordb" in (config.getoption("markexpr") or "")
    no_falkordb = pytest.mark.skip(reason="talks to FalkorDB; run `pytest -m falkordb`, which reads .env")
    no_live = pytest.mark.skip(reason="real model calls; set THESEUS_LIVE=1 to run")
    for item in items:
        if "falkordb" in item.keywords and not (asked or os.environ.get("FALKORDB_HOST")):
            item.add_marker(no_falkordb)
        if "live" in item.keywords and os.environ.get("THESEUS_LIVE") != "1":
            item.add_marker(no_live)


@pytest.fixture(scope="module", autouse=True)
def no_graphs_left_behind(request: pytest.FixtureRequest) -> Iterator[None]:
    """Fail a module whose FalkorDB tests leave a graph on the instance, and delete it by its exact name.

    The shared Cloud instance has a 100 MB cap with no eviction, so leaked graphs break later runs. This
    fixture is set up first in its module, so it is torn down after the module's own fixtures, and anything
    still there then is a leak. It does nothing when no FalkorDB test in the module will run."""
    module = request.node
    runs = [
        item
        for item in request.session.items
        if item.getparent(pytest.Module) is module
        and "falkordb" in item.keywords
        and item.get_closest_marker("skip") is None
    ]
    if not runs:
        yield
        return
    from theseus.config import get_settings
    from theseus.graph.client import get_client

    db = get_client(get_settings())
    before = db.list_graphs()
    ledger = GraphLedger()
    with pytest.MonkeyPatch.context() as patch:
        ledger.install(patch)
        yield
    left = ledger.left_behind(before, db.list_graphs())
    for name in left:
        db.select_graph(name).delete()
    drop_unused_docs_graph(db, before)
    if left:
        pytest.fail(
            f"{module.nodeid} left {len(left)} graph(s) on FalkorDB, now deleted: {', '.join(left)}. "
            "Delete every graph a test makes in a finally block or a fixture teardown.",
            pytrace=False,
        )
