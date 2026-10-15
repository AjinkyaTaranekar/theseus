from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from theseus import __version__
from theseus.api.app import create_app, falkordb_version
from theseus.api.stub import result_from_expected
from theseus.contracts.result import AnalysisResult, compare, project

SAMPLE = Path("tests/data/stub_expected.json")
ROUTES = {"pr": "/analyze", "finding": "/finding", "scan": "/scan"}
FIXTURES = sorted(Path("fixtures").glob("*/expected.json"))


def client_with(version: str | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[falkordb_version] = lambda: version
    return TestClient(app)


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield client_with("4.22.0")


def test_health_reports_falkordb_and_the_version() -> None:
    res = client_with("4.22.0").get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "falkordb": "4.22.0", "version": __version__}


def test_health_is_degraded_without_falkordb() -> None:
    res = client_with(None).get("/health")
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


def test_a_repo_request_is_not_built_yet(client: TestClient) -> None:
    res = client.post("/analyze", json={"repo": "owner/theseus", "pr_number": 1})
    assert res.status_code == 501


def test_the_stub_projects_back_to_its_expected_json() -> None:
    expected = json.loads(SAMPLE.read_text(encoding="utf-8"))
    result = result_from_expected(expected)
    assert compare(project(result), expected) == []
    assert result.opened[0].steps[0].type == "MEMBER_OF"
    assert result.opened[0].steps[-1].type == "UNLOCKS"
    assert [c.id for c in result.candidates if c.recommended] == ["B"]
