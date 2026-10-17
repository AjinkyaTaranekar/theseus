"""`POST /scan` runs the real scan of a scan fixture (task C3); the in-memory store and recorded Jev stand in
for FalkorDB and the live models, so nothing touches the network."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.golden.conftest import RecordedJev
from theseus.api.app import build_scan, create_app
from theseus.config import get_settings
from theseus.contracts.result import AnalysisResult
from theseus.errors import IngestError
from theseus.graph.store import MemoryStore


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(connect=lambda: object())) as c:
        c.app.state.scan = build_scan(MemoryStore(), RecordedJev(), get_settings())  # type: ignore[attr-defined]
        yield c


def test_a_fixture_request_runs_the_real_scan(client: TestClient) -> None:
    res = client.post("/scan", json={"fixture": "unused-grant"})
    assert res.status_code == 200
    result = AnalysisResult.model_validate(res.json())
    assert result.mode == "scan" and result.graphs == {"main": "fx__unused-grant__main"}
    assert result.headline != "stub"
    assert [(g.workload, g.resource, g.access) for g in result.unused_grants] == [
        ("workload:invoice-mailer", "secret:payments-api-key", "read"),
        ("workload:receipt-renderer", "secret:payments-api-key", "read"),
        ("workload:support-portal", "secret:prod-db-credentials", "read"),
    ]
    assert [(c.id, c.verdict, c.recommended) for c in result.candidates] == [("U", "pass", True)]
    assert result.min_cut is not None and result.min_cut.value == 2


def test_a_fixture_that_is_not_a_scan_is_refused(client: TestClient) -> None:
    assert client.post("/scan", json={"fixture": "intern"}).status_code == 400


def test_a_repo_scan_waits_for_apply(client: TestClient) -> None:
    assert client.post("/scan", json={"repo": "demo-org/theseus"}).status_code == 501


def test_a_scan_that_cannot_finish_says_so(client: TestClient) -> None:
    def broken(fixture: str) -> AnalysisResult:
        raise IngestError("no plan")

    client.app.state.scan = broken  # type: ignore[attr-defined]
    res = client.post("/scan", json={"fixture": "unused-grant"})
    assert res.status_code == 500 and "no plan" in res.json()["detail"]


def test_without_an_engine_the_route_is_unavailable() -> None:
    with TestClient(create_app(connect=lambda: object())) as c:
        c.app.state.scan = None  # type: ignore[attr-defined]
        assert c.post("/scan", json={"fixture": "unused-grant"}).status_code == 503
