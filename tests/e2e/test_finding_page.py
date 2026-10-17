"""`POST /finding` with the token runs finding mode for real on a fixture (FM3, FM4) and keeps it for its
signed page, which reads the result and the graph from the store. The store is in memory and Jev replays."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.golden.conftest import RecordedJev
from theseus.api import reviews, routes
from theseus.api.app import build_finder, create_app
from theseus.config import Settings
from theseus.graph.store import MemoryStore

TOKEN = "theseus-token-not-real"
ID = "GHSA-demo-0001"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None, theseus_token=TOKEN, theseus_repos="demo-org/theseus", domain="theseus.example"
    )


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def client(settings: Settings, store: MemoryStore) -> Iterator[TestClient]:
    app = create_app(connect=lambda: object())
    app.dependency_overrides[routes.get_settings] = lambda: settings
    app.dependency_overrides[routes.get_store] = lambda: store
    app.dependency_overrides[routes.get_finder] = lambda: build_finder(store, RecordedJev(), settings)
    with TestClient(app) as c:
        yield c


def run(client: TestClient, fixture: str = "compromised-action", token: str | None = TOKEN):
    headers = {"X-Theseus-Token": token} if token is not None else {}
    return client.post("/finding", json={"fixture": fixture}, headers=headers)


def test_with_the_token_the_engine_runs_and_the_page_link_comes_back(
    client: TestClient, store: MemoryStore
) -> None:
    res = run(client)
    assert res.status_code == 200, res.text
    result = res.json()
    assert result["mode"] == "finding" and result["rotate"] == ["secret:prod-db-credentials"]
    assert result["finding"]["workflows"] == [
        "workflow:demo-org/docs-site/preview.yml",
        "workflow:demo-org/website/lint.yml",
    ]
    link = res.headers["x-theseus-page"]
    assert link.startswith(f"https://theseus.example/findings/{ID}?k=")

    path = link.removeprefix("https://theseus.example")
    page = client.get(path)
    assert page.status_code == 200 and "<title>Theseus review</title>" in page.text
    route, _, query = path.partition("?")
    data = client.get(f"{route}/data?{query}").json()
    assert (data["kind"], data["id"], data["world_root"]) == (
        "finding",
        ID,
        "fixtures/compromised-action/base",
    )
    base = data["graphs"]["base"]
    assert base == {"name": base["name"], **store.view(base["name"])} and base["nodes"]
    [cut] = data["result"]["min_cut"]["cut"]
    assert (cut["src"], cut["type"], cut["dst"]) == (
        "workflow:demo-org/docs-site/preview.yml",
        "TRUSTS",
        "role:github-deploy",
    )


def test_without_the_token_the_stub_answers_and_nothing_is_kept(
    client: TestClient, store: MemoryStore
) -> None:
    res = run(client, token=None)
    assert res.status_code == 200 and "x-theseus-page" not in res.headers
    assert store.get_doc(reviews.finding_key(ID)) is None


def test_a_wrong_token_or_a_pr_fixture_is_refused(client: TestClient) -> None:
    assert run(client, token="wrong").status_code == 401
    assert run(client, fixture="intern").status_code == 400
    assert run(client, fixture="../etc").status_code == 400


@pytest.mark.parametrize("query", ["", "?k=", "?k=0123456789abcdef0123456789abcdef"])
def test_a_finding_page_without_the_right_signature_is_a_404(client: TestClient, query: str) -> None:
    assert run(client).status_code == 200
    for route in (f"/findings/{ID}", f"/findings/{ID}/data"):
        assert client.get(f"{route}{query}").status_code == 404


def test_a_finding_never_run_has_no_page(client: TestClient, settings: Settings) -> None:
    k = reviews.sign(settings, reviews.finding_key("GHSA-none"))
    assert client.get(f"/findings/GHSA-none/data?k={k}").status_code == 404
