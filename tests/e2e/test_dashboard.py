"""`POST /posture` keeps main's posture, and the organisation dashboard reads it with every review and finding
from the store (O1 to O5). The posture runs on the demo world's main offline: the store is in memory, Jev
replays, and the GitHub stand-in only answers which repos Theseus acts on."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.golden.conftest import deps_for, world
from theseus.api import reviews, routes
from theseus.api.app import create_app
from theseus.api.github import GitHub
from theseus.config import Settings
from theseus.contracts.posture import PostureReport
from theseus.engine.pipeline import run_posture
from theseus.graph.store import MemoryStore

TOKEN = "theseus-token-not-real"
REPO = "demo-org/theseus"
SHA = "c" * 40
ADVISORY = json.loads(Path("advisories/GHSA-demo-0001.json").read_text(encoding="utf-8"))


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, theseus_token=TOKEN, theseus_repos=REPO, domain="theseus.example")


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def client(settings: Settings, store: MemoryStore) -> Iterator[TestClient]:
    deps = deps_for("unused-grant")
    deps = type(deps)(store=store, adapters=deps.adapters, llm=None, jev=deps.jev, settings=settings)
    asked: list[tuple[str, str]] = []

    def posture(gh: GitHub, repo: str, sha: str, plan: dict[str, Any]) -> PostureReport:
        asked.append((repo, sha))
        return run_posture(world("unused-grant", "base"), deps, [ADVISORY])

    app = create_app(connect=lambda: object())
    app.dependency_overrides[routes.get_settings] = lambda: settings
    app.dependency_overrides[routes.get_store] = lambda: store
    app.dependency_overrides[routes.get_github] = lambda: GitHub(settings)
    app.dependency_overrides[routes.get_posture] = lambda: posture
    with TestClient(app) as c:
        c.asked = asked  # type: ignore[attr-defined]
        yield c


def send(client: TestClient, token: str | None = TOKEN, **changes: Any):
    body = {"repo": REPO, "sha": SHA, "plan": {}, "trigger": "schedule", **changes}
    headers = {"X-Theseus-Token": token} if token is not None else {}
    return client.post("/posture", json=body, headers=headers)


def dashboard(client: TestClient, settings: Settings, k: str | None = None):
    k = reviews.sign(settings, reviews.dashboard_key(REPO)) if k is None else k
    return client.get(f"/dashboard/{REPO}/data?k={k}")


def test_a_posture_run_is_kept_and_its_dashboard_link_comes_back(
    client: TestClient, store: MemoryStore
) -> None:
    res = send(client)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["findings"] == ["GHSA-demo-0001"] and body["single_points"] > 0 and body["monthly_usd"] > 0
    assert res.headers["x-theseus-page"].startswith(f"https://theseus.example/dashboard/{REPO}?k=")
    assert client.asked == [(REPO, SHA)]  # type: ignore[attr-defined]
    doc = json.loads(store.get_doc(reviews.posture_key(REPO)) or "{}")
    assert (doc["sha"], doc["trigger"], doc["findings"]) == (SHA, "schedule", ["GHSA-demo-0001"])
    assert store.get_doc(reviews.finding_key("GHSA-demo-0001")) is not None


def test_the_dashboard_shows_the_posture_the_reviews_and_the_findings(
    client: TestClient, settings: Settings, store: MemoryStore
) -> None:
    assert send(client).status_code == 200
    review = json.loads(store.get_doc(reviews.finding_key("GHSA-demo-0001")) or "{}")["result"]
    review = {**review, "mode": "pr", "finding": None, "repo": REPO, "pr_number": 85}
    store.put_doc(
        reviews.key(REPO, 85),
        json.dumps(
            {
                "repo": REPO,
                "number": 85,
                "title": "Add Priya to support-engineers",
                "head_sha": "a" * 40,
                "updated_at": "2026-10-17T00:00:00+00:00",
                "verdict": {
                    "level": "blocked",
                    "conclusion": "failure",
                    "heading": "🔴 Merge blocked",
                    "title": "x",
                },
                "result": review,
            }
        ),
    )
    res = dashboard(client, settings)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["repo"] == REPO and data["posture"]["sha"] == SHA
    assert data["main_graph"]["name"] == data["posture"]["scan"]["graphs"]["main"]
    assert data["main_graph"]["nodes"] > 0 and data["main_graph"]["edges"] > 0
    [pr] = data["reviews"]
    assert (pr["number"], pr["title"], pr["verdict"]["level"]) == (
        85,
        "Add Priya to support-engineers",
        "blocked",
    )
    assert pr["url"].startswith(f"https://theseus.example/reviews/{REPO}/85?k=")
    [finding] = data["findings"]
    assert finding["id"] == "GHSA-demo-0001" and finding["rotate"] and finding["url"]
    assert all(step["done"] for step in data["onboarding"])
    assert data["posture"]["posture"]["single_points"] and data["posture"]["posture"]["articulation"]


def test_a_dashboard_before_any_scan_says_what_is_missing(client: TestClient, settings: Settings) -> None:
    data = dashboard(client, settings).json()
    assert data["posture"] is None and data["reviews"] == [] and data["findings"] == []
    assert [step["done"] for step in data["onboarding"]] == [False, False, False, False]


@pytest.mark.parametrize("k", ["", "0123456789abcdef0123456789abcdef"])
def test_a_dashboard_without_the_right_signature_is_a_404(
    client: TestClient, settings: Settings, k: str
) -> None:
    assert dashboard(client, settings, k).status_code == 404
    assert client.get(f"/dashboard/{REPO}?k={k}").status_code == 404


def test_a_dashboard_of_a_repo_theseus_does_not_act_on_is_a_404(
    client: TestClient, settings: Settings
) -> None:
    k = reviews.sign(settings, reviews.dashboard_key("someone/else"))
    assert client.get(f"/dashboard/someone/else/data?k={k}").status_code == 404


def test_the_dashboard_page_is_served_with_the_signed_link(client: TestClient, settings: Settings) -> None:
    k = reviews.sign(settings, reviews.dashboard_key(REPO))
    page = client.get(f"/dashboard/{REPO}?k={k}")
    assert page.status_code == 200 and "<title>Theseus dashboard</title>" in page.text


@pytest.mark.parametrize(
    ("token", "changes", "status"),
    [
        (None, {}, 401),
        ("wrong", {}, 401),
        (TOKEN, {"repo": "someone/else"}, 403),
        (TOKEN, {"sha": "main"}, 422),
        (TOKEN, {"trigger": "pull_request"}, 422),
    ],
)
def test_a_posture_request_is_checked_before_anything_runs(
    client: TestClient, token: str | None, changes: dict[str, Any], status: int
) -> None:
    assert send(client, token, **changes).status_code == status
    assert client.asked == []  # type: ignore[attr-defined]


def test_a_finding_s_urgency_is_shown_as_jev_s_probability(
    client: TestClient, settings: Settings, store: MemoryStore
) -> None:
    assert send(client).status_code == 200
    key = reviews.finding_key("GHSA-demo-0001")
    doc = json.loads(store.get_doc(key) or "{}")
    doc["result"]["finding"]["urgency"] = {"p": 0.93, "source": "jev"}
    store.put_doc(key, json.dumps(doc))
    [finding] = dashboard(client, settings).json()["findings"]
    assert finding["urgency"] == 0.93
