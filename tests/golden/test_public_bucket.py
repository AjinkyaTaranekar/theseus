"""The public prefix remains available while sensitive objects are closed."""

from __future__ import annotations

from tests.golden.conftest import expected
from tests.golden.test_intern import analyze
from theseus.contracts.result import compare, project


def test_public_bucket_scope_down_is_recommended() -> None:
    assert (
        compare(
            project(analyze("public-bucket")), expected("public-bucket"), keys=["candidates", "recommended"]
        )
        == []
    )
