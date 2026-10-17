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
from theseus.api.contain import Contained
from theseus.api.github import GitHub
from theseus.config import Settings
from theseus.contracts.incident import Incident
from theseus.contracts.posture import PostureReport
from theseus.contracts.result import AnalysisResult
from theseus.engine.pipeline import run_posture
from theseus.errors import GitHubError
from theseus.graph.store import MemoryStore

TOKEN = "theseus-token-not-real"
REPO = "demo-org/theseus"
SHA = "c" * 40
# What the status feeds report in these tests: Secrets Manager down where the demo world runs, and EC2
# somewhere it doesn't.
FEED = [
    Incident(provider="aws", service="ec2", region="us-east-1", title="Increased Error Rates", source="feed"),
    Incident(
        provider="aws",
        service="secretsmanager",
        region="eu-west-1",
        title="Secrets Manager outage",
        source="feed",
    ),
]
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
    contained: list[str] = []

    def contain(
        gh: GitHub, repo: str, sha: str, finding: AnalysisResult, page: str | None
    ) -> Contained | None:
        finding_id = (finding.finding or {})["id"]
        contained.append(finding_id)
        if finding_id == "GHSA-broken":
            raise GitHubError("POST /repos/demo-org/theseus/pulls: 422 Validation Failed")
        pr = f"https://github.com/{REPO}/pull/201"
        return Contained(
            finding=finding_id,
            pr=pr,
            pr_number=201,
            issue=f"https://github.com/{REPO}/issues/301",
            opened=True,
        )

    app.dependency_overrides[routes.get_containment] = lambda: contain
    checks: list[int] = []

    def feeds() -> tuple[list[Incident], list[str]]:
        checks.append(1)
        return FEED, ["github: could not be read"]

    app.dependency_overrides[routes.get_status] = lambda: feeds
    with TestClient(app) as c:
        c.asked = asked  # type: ignore[attr-defined]
        c.contained = contained  # type: ignore[attr-defined]
        c.checks = checks  # type: ignore[attr-defined]
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


def test_a_finding_s_containment_pr_and_rotate_issue_show_on_the_dashboard(
    client: TestClient, settings: Settings
) -> None:
    body = send(client).json()
    assert client.contained == ["GHSA-demo-0001"]  # type: ignore[attr-defined]
    assert body["contained"] == [
        {
            "finding": "GHSA-demo-0001",
            "pr": f"https://github.com/{REPO}/pull/201",
            "issue": f"https://github.com/{REPO}/issues/301",
            "opened": True,
        }
    ]
    [finding] = dashboard(client, settings).json()["findings"]
    assert finding["containment"]["pr_number"] == 201 and finding["fix"] == {
        "id": "K",
        "verdict": "pass",
        "title": "Trust the role only from the workflows that need it",
    }


def test_a_containment_that_fails_leaves_the_posture_kept_and_says_why(
    client: TestClient, settings: Settings, store: MemoryStore
) -> None:
    broken = {**ADVISORY, "id": "GHSA-broken"}
    routes_posture = client.app.dependency_overrides[routes.get_posture]()  # type: ignore[attr-defined]

    def both(gh: GitHub, repo: str, sha: str, plan: dict[str, Any]) -> PostureReport:
        report = routes_posture(gh, repo, sha, plan)
        extra = report.findings[0].model_copy(
            update={"finding": {**report.findings[0].finding, "id": broken["id"]}}
        )
        return report.model_copy(update={"findings": [*report.findings, extra]})

    client.app.dependency_overrides[routes.get_posture] = lambda: both  # type: ignore[attr-defined]
    body = send(client).json()
    assert [f["finding"] for f in body["contained"]] == ["GHSA-demo-0001"]
    assert body["containment_failed"][0]["finding"] == "GHSA-broken"
    assert store.get_doc(reviews.posture_key(REPO)) is not None


def keep_review(store: MemoryStore, number: int, level: str, title: str) -> None:
    """A kept PR review, shaped as /analyze keeps it, from the posture's finding result."""
    review = json.loads(store.get_doc(reviews.finding_key("GHSA-demo-0001")) or "{}")["result"]
    review = {**review, "mode": "pr", "finding": None, "repo": REPO, "pr_number": number}
    verdict = {"level": level, "conclusion": "failure", "heading": "x", "title": "x"}
    doc = {
        "repo": REPO,
        "number": number,
        "title": title,
        "head_sha": "a" * 40,
        "updated_at": "",
        "verdict": verdict,
    }
    store.put_doc(reviews.key(REPO, number), json.dumps({**doc, "result": review}))


def test_each_posture_run_adds_to_the_history(client: TestClient, settings: Settings) -> None:
    for trigger in ("push", "schedule"):
        assert send(client, trigger=trigger).status_code == 200
    runs = dashboard(client, settings).json()["history"]
    assert [r["trigger"] for r in runs] == ["push", "schedule"]
    assert runs[-1]["dangerous"] > 0 and runs[-1]["findings"] == 1 and runs[-1]["monthly_usd"] > 0


def test_reviews_are_paged_filtered_and_searched_on_the_server(
    client: TestClient, settings: Settings, store: MemoryStore
) -> None:
    assert send(client).status_code == 200
    for n in range(1, 31):
        keep_review(store, n, "blocked" if n % 3 == 0 else "clear", f"Change {n}")
    k = reviews.sign(settings, reviews.dashboard_key(REPO))
    page = client.get(f"/dashboard/{REPO}/reviews?k={k}&limit=10&offset=10").json()
    assert page["total"] == 30 and [r["number"] for r in page["reviews"]] == list(range(20, 10, -1))
    blocked = client.get(f"/dashboard/{REPO}/reviews?k={k}&verdict=blocked").json()
    assert blocked["total"] == 10 and all(r["number"] % 3 == 0 for r in blocked["reviews"])
    found = client.get(f"/dashboard/{REPO}/reviews?k={k}&q=change 27").json()
    assert [r["number"] for r in found["reviews"]] == [27]
    assert client.get(f"/dashboard/{REPO}/reviews?k={k}&verdict=maybe").status_code == 422
    assert client.get(f"/dashboard/{REPO}/reviews?k={k}&limit=0").status_code == 422
    assert client.get(f"/dashboard/{REPO}/reviews?k=wrong").status_code == 404


def test_the_organisation_adds_up_its_repositories(
    client: TestClient, settings: Settings, store: MemoryStore
) -> None:
    assert send(client).status_code == 200
    keep_review(store, 85, "blocked", "Add Priya")
    k = reviews.sign(settings, reviews.org_key("demo-org"))
    data = client.get(f"/org/demo-org/data?k={k}").json()
    [row] = data["repos"]
    assert (
        row["repo"] == REPO and row["scanned"] and row["url"].startswith("https://theseus.example/dashboard/")
    )
    assert data["totals"]["repos"] == 1 and data["totals"]["blocked"] == 1
    assert data["totals"]["dangerous"] == row["dangerous"] > 0 and row["top"]
    assert client.get(f"/org/demo-org?k={k}").status_code == 200
    assert client.get("/org/demo-org/data?k=wrong").status_code == 404
    other = reviews.sign(settings, reviews.org_key("someone"))
    assert client.get(f"/org/someone/data?k={other}").status_code == 404
    repo = dashboard(client, settings).json()
    assert repo["org"] == "demo-org" and repo["org_url"].startswith("https://theseus.example/org/demo-org?k=")


def test_the_graph_view_reads_main_s_whole_graph_from_the_store(
    client: TestClient, settings: Settings, store: MemoryStore
) -> None:
    k = reviews.sign(settings, reviews.dashboard_key(REPO))
    assert client.get(f"/dashboard/{REPO}/graph?k={k}").status_code == 404  # before the first scan
    assert send(client).status_code == 200
    graph = client.get(f"/dashboard/{REPO}/graph?k={k}").json()
    assert graph == {"name": graph["name"], **store.view(graph["name"])} and graph["nodes"] and graph["edges"]
    assert {"FLOW"}.isdisjoint({e["type"] for e in graph["edges"]})
    assert client.get(f"/dashboard/{REPO}/graph?k=wrong").status_code == 404


def outage(client: TestClient, settings: Settings, k: str | None = None, **params: str):
    k = reviews.sign(settings, reviews.dashboard_key(REPO)) if k is None else k
    return client.get(f"/dashboard/{REPO}/incident", params={"k": k, **params})


def test_an_outage_picked_on_the_dashboard_is_answered_from_the_kept_basis(
    client: TestClient, settings: Settings
) -> None:
    assert send(client).status_code == 200
    res = outage(client, settings, provider="aws", service="lambda", region="eu-west-1")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["incident"]["source"] == "picker"
    assert body["headline"].startswith("AWS Lambda down in eu-west-1: 6 down,")
    assert {m["id"] for m in body["matched"]} >= {"workload:billing-api", "workload:invoice-mailer"}
    typed = outage(client, settings, text="Secrets Manager is down in Ireland").json()
    assert typed["incident"]["region"] == "eu-west-1" and typed["incident"]["source"] == "text"
    assert any(b["dependency"]["resource"] == "db:customer-db" for b in typed["broken"])
    data = dashboard(client, settings).json()
    assert "outage" not in data["posture"]["posture"]  # the page gets the picker's terms, not the basis
    services = {s["service"]: s["here"] for s in data["outage"]["services"]}
    assert (
        services["lambda"] == 6
        and services["actions"] == 5
        and data["outage"]["world_regions"] == ["eu-west-1"]
    )


def test_an_outage_naming_nothing_known_or_with_a_bad_signature_is_refused(
    client: TestClient, settings: Settings
) -> None:
    assert outage(client, settings, provider="aws", service="lambda").status_code == 404  # no posture yet
    assert send(client).status_code == 200
    assert outage(client, settings, text="the coffee machine is down").status_code == 422
    assert outage(client, settings, provider="aws", service="mainframe").status_code == 422
    assert outage(client, settings, provider="aws", service="lambda", region="mars-1").status_code == 422
    assert outage(client, settings, k="0" * 32, provider="aws", service="lambda").status_code == 404


def test_the_token_route_answers_a_headline(client: TestClient) -> None:
    assert send(client).status_code == 200
    body = {"repo": REPO, "text": "GitHub Actions is down"}
    assert client.post("/incident", json=body).status_code == 401
    res = client.post("/incident", json=body, headers={"X-Theseus-Token": TOKEN})
    assert res.status_code == 200, res.text
    assert res.json()["headline"] == "GitHub Actions down: 5 down, 3 of 25 dependencies break."


def test_a_feed_check_keeps_each_incident_s_blast_radius_for_the_dashboard(
    client: TestClient, settings: Settings, store: MemoryStore
) -> None:
    assert send(client).status_code == 200
    body = {"repo": REPO, "trigger": "schedule"}
    assert client.post("/incidents/check", json=body).status_code == 401
    res = client.post("/incidents/check", json=body, headers={"X-Theseus-Token": TOKEN})
    assert res.status_code == 200, res.text
    found = res.json()
    assert (found["incidents"], found["reaching_main"]) == (2, 1)
    assert found["errors"] == ["github: could not be read"]
    assert found["headlines"][0].startswith("AWS Secrets Manager down in eu-west-1:")
    live = dashboard(client, settings).json()["outage"]["live"]
    assert live["trigger"] == "schedule" and [r["incident"]["service"] for r in live["reports"]] == [
        "secretsmanager",
        "ec2",
    ]
    k = reviews.sign(settings, reviews.dashboard_key(REPO))
    again = client.post(f"/dashboard/{REPO}/incidents/check?k={k}")
    assert again.status_code == 200 and again.json()["trigger"] == "workflow_dispatch"
    assert client.post(f"/dashboard/{REPO}/incidents/check?k={'0' * 32}").status_code == 404
    assert len(client.checks) == 2  # type: ignore[attr-defined]


def compromise(client: TestClient, settings: Settings, node: str, k: str | None = None):
    k = reviews.sign(settings, reviews.dashboard_key(REPO)) if k is None else k
    return client.get(f"/dashboard/{REPO}/compromise", params={"k": k, "node": node})


def test_a_compromised_contractor_reaches_the_secrets_through_platform_admin_with_every_line(
    client: TestClient, settings: Settings
) -> None:
    assert send(client).status_code == 200
    res = compromise(client, settings, "user:casey-contractor")
    assert res.status_code == 200, res.text
    found = res.json()
    assert found["sensitive"] >= 6 and found["classes"]["regulated"] >= 5
    secret = next(r for r in found["reaches"] if r["target"] == "secret:prod-db-credentials")
    assert [(s["type"], s["to"]) for s in secret["steps"]] == [
        ("MEMBER_OF", "group:contractors"),
        ("CAN_ASSUME", "role:platform-admin"),
        ("CAN", "secret:prod-db-credentials"),
    ]
    first = secret["steps"][0]["proof"]
    assert first["file"] == "terraform/legacy.tf" and first["url"].endswith(f"legacy.tf#L{first['line']}")
    assert first["url"].startswith(f"https://github.com/{REPO}/blob/{SHA}/")
    # Cutting either of the first two links cuts every route to sensitive data.
    assert {(c["from"], c["to"]) for c in found["cut"]} == {
        ("user:casey-contractor", "group:contractors"),
        ("group:contractors", "role:platform-admin"),
    }
    group = compromise(client, settings, "group:contractors").json()
    assert {r["target"] for r in group["reaches"]} == {r["target"] for r in found["reaches"]}


def test_a_compromise_needs_a_known_node_and_the_signed_link(client: TestClient, settings: Settings) -> None:
    assert compromise(client, settings, "user:casey-contractor").status_code == 404  # no posture yet
    assert send(client).status_code == 200
    assert compromise(client, settings, "user:nobody").status_code == 404
    assert compromise(client, settings, "").status_code == 422
    assert compromise(client, settings, "user:casey-contractor", k="0" * 32).status_code == 404


def test_each_weak_point_comes_with_the_routes_that_all_pass_through_it(
    client: TestClient, settings: Settings
) -> None:
    assert send(client).status_code == 200
    data = dashboard(client, settings).json()
    weak = data["posture"]["weak_routes"]
    deps = weak["secret:prod-db-credentials"]
    assert deps and all(
        all("secret:prod-db-credentials" in route[1:-1] for route in d["routes"]) for d in deps
    )
    assert data["posture"]["blob"] == f"https://github.com/{REPO}/blob/{SHA}/demo-infra"


class Sources(GitHub):
    """The App's file reads, answered from the demo world on disk."""

    reads: list[tuple[str, str]] = []

    def read_file(self, repo: str, path: str, sha: str) -> str:
        Sources.reads.append((path, sha))
        if not path.startswith("demo-infra/"):
            raise GitHubError("outside the world root")
        file = Path(path)
        if not file.is_file():
            raise GitHubError("404 Not Found")
        return file.read_text(encoding="utf-8")


def test_the_lines_behind_a_claim_open_without_github_access(client: TestClient, settings: Settings) -> None:
    assert send(client).status_code == 200
    client.app.dependency_overrides[routes.get_github] = lambda: Sources(settings)  # type: ignore[attr-defined]
    k = reviews.sign(settings, reviews.dashboard_key(REPO))
    res = client.get(f"/dashboard/{REPO}/source", params={"k": k, "file": "terraform/legacy.tf", "line": 13})
    assert res.status_code == 200, res.text
    found = res.json()
    assert found["sha"] == SHA and found["start"] <= 13 <= found["start"] + len(found["lines"]) - 1
    line = next(x for x in found["lines"] if x["n"] == 13)
    assert "casey" in line["text"] or "contractors" in "".join(x["text"] for x in found["lines"])
    assert found["url"].endswith("/demo-infra/terraform/legacy.tf#L13")
    for bad in ("../.env", "/etc/passwd", "terraform/../../x"):
        assert client.get(f"/dashboard/{REPO}/source", params={"k": k, "file": bad}).status_code == 422
    assert (
        client.get(
            f"/dashboard/{REPO}/source", params={"k": "0" * 32, "file": "terraform/legacy.tf"}
        ).status_code
        == 404
    )
    reads = len(Sources.reads)
    client.get(f"/dashboard/{REPO}/source", params={"k": k, "file": "terraform/legacy.tf", "line": 24})
    assert len(Sources.reads) == reads  # a commit's file is read once
