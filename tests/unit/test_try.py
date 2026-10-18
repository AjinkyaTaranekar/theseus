"""The Try-it page and `POST /try/{preset}` (task S4): each preset runs the real engine with the models
replayed, the rate limit trips, and the page serves only what it should. The store is in memory, so nothing
touches the network."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from theseus.api import reviews, routes
from theseus.api.app import build_try, create_app
from theseus.config import get_settings
from theseus.contracts.result import AnalysisResult, compare, project
from theseus.errors import GraphError, IngestError
from theseus.graph.store import MemoryStore

ROOT = Path(__file__).resolve().parents[2]
PRESETS = ["code-pr", "intern", "public-bucket"]
KEYS = ["opened", "closed", "unchanged", "requirements", "changes", "intent"]


def expected(name: str) -> dict:
    return json.loads((ROOT / "fixtures" / name / "expected.json").read_text(encoding="utf-8"))


def stub(preset: str) -> AnalysisResult:
    return AnalysisResult(mode="pr", scenario=preset, headline=f"stub {preset}")


@pytest.fixture(scope="module")
def engine() -> routes.Try:
    """The real engine on an in-memory store; the server's mode is `live` to show the page forces replay."""
    settings = get_settings().model_copy(update={"theseus_mode": "live", "llm_api_key": None})
    return build_try(MemoryStore(), settings)


def client_for(runner: routes.Try, **limiter: object) -> Iterator[TestClient]:
    app = create_app(connect=lambda: object())
    with TestClient(app) as c:
        app.dependency_overrides[routes.get_try] = lambda: runner
        if limiter:
            app.state.try_limiter = routes.RateLimit(**limiter)  # type: ignore[arg-type]
        yield c


@pytest.fixture
def client(engine: routes.Try) -> Iterator[TestClient]:
    yield from client_for(engine)


@pytest.fixture
def fast() -> Iterator[TestClient]:
    yield from client_for(stub)


# The presets ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("preset", PRESETS)
def test_each_preset_returns_a_valid_result_that_matches_its_answer_key(
    client: TestClient, preset: str
) -> None:
    res = client.post(f"/try/{preset}")
    assert res.status_code == 200, res.text
    result = AnalysisResult.model_validate(res.json())
    assert result.scenario == preset and result.mode == "pr" and result.headline
    assert compare(project(result), expected(preset), keys=KEYS) == []


def test_the_intern_headline_names_the_database_it_reaches(client: TestClient) -> None:
    assert "customer-db" in client.post("/try/intern").json()["headline"]


def test_a_preset_runs_with_the_models_replayed_even_when_the_server_is_live(client: TestClient) -> None:
    """No key is set and the mode is `live`: a recording is the only way these answers can exist."""
    assert client.post("/try/intern").status_code == 200


def test_a_preset_can_be_run_again_and_gives_the_same_answer(client: TestClient) -> None:
    first = project(AnalysisResult.model_validate(client.post("/try/intern").json()))
    second = project(AnalysisResult.model_validate(client.post("/try/intern").json()))
    assert first == second


def test_the_presets_are_the_pr_fixtures_and_only_those() -> None:
    assert sorted(routes.presets()) == PRESETS
    assert all(routes.presets()[p] for p in PRESETS), "every preset has a description for its button"


@pytest.mark.parametrize("name", ["nope", "compromised-action", "unused-grant", "sample", "Intern"])
def test_a_name_that_is_not_a_pr_preset_is_a_404(fast: TestClient, name: str) -> None:
    res = fast.post(f"/try/{name}")
    assert res.status_code == 404
    assert "preset" in res.json()["detail"]


@pytest.mark.parametrize("name", ["..%2Fintern", "intern%00", "%2e%2e", "a b"])
def test_a_name_that_is_not_a_slug_never_reaches_the_filesystem(fast: TestClient, name: str) -> None:
    assert fast.post(f"/try/{name}").status_code in {404, 405}


def test_an_engine_failure_answers_without_a_traceback(fast: TestClient) -> None:
    def broken(preset: str) -> AnalysisResult:
        raise IngestError("secret detail at /srv/theseus/fixtures")

    fast.app.dependency_overrides[routes.get_try] = lambda: broken  # type: ignore[attr-defined]
    res = fast.post("/try/intern")
    assert res.status_code == 502
    assert "secret detail" not in res.text and "/srv" not in res.text


def test_a_store_that_does_not_answer_is_a_503(fast: TestClient) -> None:
    def down(preset: str) -> AnalysisResult:
        raise GraphError("cannot reach FalkorDB at example:1")

    fast.app.dependency_overrides[routes.get_try] = lambda: down  # type: ignore[attr-defined]
    res = fast.post("/try/intern")
    assert res.status_code == 503 and "example:1" not in res.text


def test_the_engine_is_not_ready_before_startup_has_built_it() -> None:
    app = create_app(connect=lambda: object())
    with TestClient(app) as c:
        del app.state.try_preset
        assert c.post("/try/intern").status_code == 503


def test_missing_recordings_fail_the_visit_and_never_the_startup(tmp_path: Path) -> None:
    runner = build_try(MemoryStore(), get_settings(), recordings=tmp_path)  # builds without reading anything
    for c in client_for(runner):
        res = c.post("/try/intern")
        assert res.status_code == 502 and str(tmp_path) not in res.text


# The rate limit --------------------------------------------------------------------------------------------


def test_the_eleventh_request_in_a_minute_from_one_address_is_refused(fast: TestClient) -> None:
    assert [fast.post("/try/intern").status_code for _ in range(10)] == [200] * 10
    res = fast.post("/try/intern")
    assert res.status_code == 429
    assert 1 <= int(res.headers["Retry-After"]) <= 60


def test_another_address_has_its_own_allowance(fast: TestClient) -> None:
    for _ in range(11):
        fast.post("/try/intern", headers={"X-Forwarded-For": "203.0.113.1"})
    assert fast.post("/try/intern", headers={"X-Forwarded-For": "203.0.113.2"}).status_code == 200


def test_a_forged_first_forwarded_address_does_not_buy_a_new_allowance(fast: TestClient) -> None:
    """The proxy appends the address it saw, so only the last entry is trusted."""
    codes = [
        fast.post("/try/intern", headers={"X-Forwarded-For": f"10.0.0.{i}, 198.51.100.7"}).status_code
        for i in range(12)
    ]
    assert codes[:10] == [200] * 10 and codes[10:] == [429, 429]


def test_a_refused_request_does_not_run_the_engine() -> None:
    calls: list[str] = []

    def counting(preset: str) -> AnalysisResult:
        calls.append(preset)
        return stub(preset)

    for c in client_for(counting, limit=2):
        statuses = [c.post("/try/intern").status_code for _ in range(4)]
    assert statuses == [200, 200, 429, 429] and calls == ["intern", "intern"]


def test_the_allowance_comes_back_when_the_minute_is_over() -> None:
    now = [0.0]
    limiter = routes.RateLimit(limit=2, window=60, clock=lambda: now[0])
    assert [limiter.take("a") for _ in range(3)] == [None, None, 60]
    now[0] = 30.0
    assert limiter.take("a") == 30
    now[0] = 61.0
    assert limiter.take("a") is None


def test_the_limiter_forgets_addresses_that_have_gone_quiet() -> None:
    now = [0.0]
    limiter = routes.RateLimit(limit=1, window=60, clock=lambda: now[0], max_clients=100)
    for i in range(100):
        limiter.take(f"ip{i}")
    now[0] = 120.0
    limiter.take("fresh")
    assert len(limiter.hits) == 1


def test_a_flood_of_addresses_cannot_grow_the_limiter_without_bound() -> None:
    limiter = routes.RateLimit(limit=1, window=60, clock=lambda: 0.0, max_clients=50)
    for i in range(500):
        limiter.take(f"ip{i}")
    assert len(limiter.hits) <= 50


def test_clearing_quiet_clients_never_evicts_busy_ones() -> None:
    """Dropping the quiet ones can bring the table under its cap: nobody else may be dropped then."""
    now = [0.0]
    limiter = routes.RateLimit(limit=1, window=60, clock=lambda: now[0], max_clients=50)
    for i in range(11):
        limiter.take(f"quiet{i}")
    now[0] = 100.0
    for i in range(40):
        limiter.take(f"busy{i}")
    limiter.take("one-more")
    assert all(limiter.take(f"busy{i}") is not None for i in range(40)), "a busy client got a new allowance"


# The page --------------------------------------------------------------------------------------------------


def test_the_page_has_a_button_for_each_preset_and_its_description(fast: TestClient) -> None:
    res = fast.get("/")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/html")
    for preset, text in routes.presets().items():
        assert f'data-preset="{preset}"' in res.text
        assert text.rstrip(".") in res.text.replace("&#39;", "'")


def test_the_page_pins_its_one_library_and_sets_a_policy(fast: TestClient) -> None:
    res = fast.get("/")
    scripts = re.findall(r"<script[^>]*src=\"([^\"]+)\"[^>]*>", res.text)
    external = [s for s in scripts if s.startswith("http")]
    assert len(external) == 1 and re.fullmatch(
        r"https://cdnjs\.cloudflare\.com/ajax/libs/mermaid/\d+\.\d+\.\d+/mermaid\.min\.js", external[0]
    )
    assert re.search(r'integrity="sha512-[A-Za-z0-9+/=]+"', res.text)
    policy = res.headers["content-security-policy"]
    assert "default-src 'self'" in policy and "https://cdnjs.cloudflare.com" in policy
    assert res.headers["cache-control"] == "no-store"
    assert not re.search(r"\son\w+=", res.text), "no inline event handlers: the policy forbids them"


@pytest.mark.parametrize(("name", "kind"), [("app.js", "javascript"), ("style.css", "text/css")])
def test_the_page_serves_its_script_and_its_style(fast: TestClient, name: str, kind: str) -> None:
    res = fast.get(f"/web/{name}")
    assert res.status_code == 200 and kind in res.headers["content-type"] and res.text


@pytest.mark.parametrize(
    "name", ["review.html", "index.html", "..%2Fapp.py", "nope.js", "%2e%2e%2fconfig.py"]
)
def test_the_page_serves_nothing_else_from_web(fast: TestClient, name: str) -> None:
    assert fast.get(f"/web/{name}").status_code == 404


def test_the_script_reads_a_result_only_through_text_never_html() -> None:
    """A result's strings come from files and models: the page must never put them in as markup."""
    js = (ROOT / "theseus/web/app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "document.write" not in js
    assert 'securityLevel: "strict"' in js


def test_the_front_page_names_every_way_in_and_links_the_live_dashboard(fast: TestClient) -> None:
    """With a public hostname, a token and a repository, the page links the first repository's dashboard
    by its signed link; every surface is introduced, and the Try-it presets stay on the page."""
    settings = get_settings().model_copy(
        update={
            "domain": "theseus.example",
            "theseus_token": SecretStr("t" * 32),
            "theseus_repos": "acme/infra",
        }
    )
    fast.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    try:
        res = fast.get("/")
    finally:
        fast.app.dependency_overrides.pop(get_settings)  # type: ignore[attr-defined]
    link = reviews.dashboard_url(settings, "acme/infra")
    assert link and f'href="{link}"' in res.text
    assert 'href="https://github.com/acme/infra"' in res.text
    for surface in ("GitHub agent", "Website", "Claude Code plugin", "MCP server", "CLI", "The graph"):
        assert f"</svg>{surface}</h3>" in res.text
    assert "System One" in res.text and "System Two" in res.text and 'id="presets"' in res.text


def test_without_a_signed_link_the_front_page_still_works(fast: TestClient) -> None:
    settings = get_settings().model_copy(update={"domain": "", "theseus_repos": ""})
    fast.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    try:
        res = fast.get("/")
    finally:
        fast.app.dependency_overrides.pop(get_settings)  # type: ignore[attr-defined]
    assert res.status_code == 200 and "/dashboard/" not in res.text and "Live dashboard" not in res.text


@pytest.mark.parametrize(
    ("name", "media"),
    [
        ("logo.svg", "image/svg+xml"),
        ("shot-review.jpg", "image/jpeg"),
        ("shot-comment.jpg", "image/jpeg"),
        ("shot-fixes.jpg", "image/jpeg"),
        ("shot-incident.jpg", "image/jpeg"),
        ("shot-graph.jpg", "image/jpeg"),
    ],
)
def test_the_front_page_serves_its_logo_and_real_screens(fast: TestClient, name: str, media: str) -> None:
    res = fast.get(f"/web/{name}")
    assert res.status_code == 200 and res.headers["content-type"].startswith(media)
    assert f'src="/web/{name}"' in fast.get("/").text


def test_the_front_page_shows_what_the_app_does_and_how_agents_use_it(fast: TestClient) -> None:
    """The GitHub App's review, suggested change and apply, and the steps for the plugin, skill and MCP."""
    text = fast.get("/").text
    assert "Reviews" in text and "Suggests" in text and "Applies" in text and "/theseus apply" in text
    assert "suggested a change" in text
    for step in ("/plugin install theseus", "THESEUS_PYTHON", "/theseus:check", "/theseus:investigate"):
        assert step in text
    assert "python -m theseus.mcp.server --repo ." in text and "skill" in text
