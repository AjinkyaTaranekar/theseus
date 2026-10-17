from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from theseus import __version__
from theseus.api import app as app_module
from theseus.api.app import create_app, falkordb_version
from theseus.api.stub import result_from_expected
from theseus.contracts.result import AnalysisResult, compare, project
from theseus.errors import GraphError

SAMPLE = Path("tests/data/stub_expected.json")
ROUTES = {"pr": "/analyze", "finding": "/finding", "scan": "/scan"}
FIXTURES = sorted(Path("fixtures").glob("*/expected.json"))


def unreachable() -> object:
    raise GraphError("cannot reach FalkorDB at example:1")


def started(version: str | None) -> TestClient:
    """A client whose app has started (startup ran) with a stand-in FalkorDB of this version."""
    app = create_app(connect=lambda: object())
    app.dependency_overrides[falkordb_version] = lambda: version
    return TestClient(app)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with started("4.22.0") as c:
        yield c


def test_the_app_refuses_to_start_without_falkordb() -> None:
    """Rule 3 holds however the app is launched: `theseus serve`, or uvicorn straight from the image."""
    with pytest.raises(GraphError, match="cannot reach FalkorDB"):
        with TestClient(create_app(connect=unreachable)):
            pass


def test_importing_the_app_connects_to_nothing() -> None:
    assert not hasattr(app_module.app.state, "falkordb")


def test_health_reports_falkordb_and_the_version() -> None:
    with started("4.22.0") as c:
        res = c.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "falkordb": "4.22.0", "version": __version__}


def test_health_is_degraded_when_falkordb_stops_answering() -> None:
    with started(None) as c:
        res = c.get("/health")
    assert res.status_code == 503
    assert res.json() == {"status": "degraded", "falkordb": "unreachable", "version": __version__}


def test_analyze_returns_a_valid_stub_for_the_sample(client: TestClient) -> None:
    res = client.post("/analyze", json={"fixture": "sample"})
    assert res.status_code == 200
    body = res.json()
    assert "from" in body["opened"][0]["steps"][0]
    result = AnalysisResult.model_validate(body)
    assert result.headline == "stub"
    expected = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert compare(project(result), expected) == []


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.parent.name)
def test_every_fixture_with_an_expected_json_gets_a_valid_stub(client: TestClient, path: Path) -> None:
    expected = json.loads(path.read_text(encoding="utf-8"))
    if expected["mode"] == "scan":
        # /scan runs the real scan (C3); the answer key must still hold, here on an in-memory store.
        from tests.golden.conftest import RecordedJev
        from theseus.api.app import build_scan
        from theseus.config import get_settings
        from theseus.graph.store import MemoryStore

        client.app.state.scan = build_scan(MemoryStore(), RecordedJev(), get_settings())  # type: ignore[attr-defined]
    res = client.post(ROUTES[expected["mode"]], json={"fixture": path.parent.name})
    assert res.status_code == 200
    assert compare(project(AnalysisResult.model_validate(res.json())), expected) == []


@pytest.mark.parametrize("name", ["../etc", "..", "Intern", "intern/../../x", "", "a b"])
def test_a_fixture_name_must_be_a_plain_slug(client: TestClient, name: str) -> None:
    assert client.post("/analyze", json={"fixture": name}).status_code == 400


def test_an_unknown_fixture_is_not_found(client: TestClient) -> None:
    assert client.post("/analyze", json={"fixture": "no-such-scenario"}).status_code == 404


def test_a_fixture_must_match_the_route_mode(client: TestClient) -> None:
    assert client.post("/finding", json={"fixture": "sample"}).status_code == 400


def test_a_repo_request_without_the_action_s_token_is_refused() -> None:
    """F7 answers a request from the Action (tests/unit/test_github.py); without the token it does nothing."""
    from theseus.api import routes
    from theseus.config import Settings

    app = create_app(connect=lambda: object())
    app.dependency_overrides[routes.get_settings] = lambda: Settings(_env_file=None, theseus_token="t")
    with TestClient(app) as c:
        res = c.post("/analyze", json={"repo": "owner/theseus", "pr_number": 1, "head_sha": "a" * 40})
    assert res.status_code == 401


def test_the_stub_projects_back_to_its_expected_json() -> None:
    expected = json.loads(SAMPLE.read_text(encoding="utf-8"))
    result = result_from_expected(expected)
    assert compare(project(result), expected) == []
    assert result.opened[0].steps[0].type == "MEMBER_OF"
    assert result.opened[0].steps[-1].type == "UNLOCKS"
    assert [c.id for c in result.candidates if c.recommended] == ["B"]


@pytest.mark.parametrize(("mode", "loads"), [("live", True), ("record", True), ("replay", False)])
def test_the_llm_client_loads_before_the_api_takes_requests(
    monkeypatch: pytest.MonkeyPatch, mode: str, loads: bool
) -> None:
    """Loaded later, on a worker thread, LiteLLM's import races the event loop's logging (seen live)."""
    from theseus.api import app as app_module
    from theseus.config import Settings

    loaded: list[bool] = []
    monkeypatch.setattr(app_module, "get_settings", lambda: Settings(_env_file=None, theseus_mode=mode))
    monkeypatch.setattr(app_module, "load_client", lambda: loaded.append(True))
    with TestClient(create_app(connect=lambda: object())):
        assert loaded == ([True] if loads else [])
