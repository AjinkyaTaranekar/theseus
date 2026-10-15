"""Shared test setup: marked tests run only when their environment is available."""

from __future__ import annotations

import os

import pytest


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
