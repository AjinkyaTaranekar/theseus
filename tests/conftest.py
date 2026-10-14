"""Shared test setup: marked tests run only when their environment is available."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip `falkordb` tests without FALKORDB_HOST and `live` tests unless THESEUS_LIVE=1."""
    no_falkordb = pytest.mark.skip(reason="needs FALKORDB_HOST (the FalkorDB Cloud settings in .env)")
    no_live = pytest.mark.skip(reason="real model calls; set THESEUS_LIVE=1 to run")
    for item in items:
        if "falkordb" in item.keywords and not os.environ.get("FALKORDB_HOST"):
            item.add_marker(no_falkordb)
        if "live" in item.keywords and os.environ.get("THESEUS_LIVE") != "1":
            item.add_marker(no_live)
