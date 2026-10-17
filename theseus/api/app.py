"""The FastAPI app: health and the analysis routes. A composition root (docs/spec/08-core-and-adapters.md).

`uvicorn theseus.api.app:app` serves it. Importing it connects to nothing; starting it connects to FalkorDB
and fails if it cannot, so the API never runs without FalkorDB however it is launched (rule 3).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.gzip import GZipMiddleware

from theseus import __version__
from theseus.adapters.aws import health
from theseus.adapters.aws.adapter import AwsAdapter
from theseus.adapters.github import status as github_status
from theseus.adapters.github.adapter import GithubAdapter
from theseus.adapters.python.adapter import PythonAdapter
from theseus.adapters.terraform.adapter import TerraformAdapter
from theseus.agent.jev import Jev
from theseus.agent.llm import Llm, load_client
from theseus.agent.replayed import RECORDINGS, ReplayedIntent, ReplayedJev
from theseus.api import contain, routes, status, webhooks
from theseus.api.github import GitHub
from theseus.cli import analyze_fixture, load_advisories
from theseus.config import Settings, get_settings
from theseus.contracts.adapters import Adapters
from theseus.contracts.engine import Deps, GraphStore
from theseus.contracts.posture import PostureReport
from theseus.contracts.result import AnalysisResult, PatchOp
from theseus.engine.pipeline import run_finding, run_posture, run_pr, run_scan
from theseus.errors import GraphError, IngestError, PatchError, TheseusError
from theseus.graph.client import get_client, server_version
from theseus.graph.store import FalkorStore
from theseus.importer.world import load_world, load_world_from_files

log = logging.getLogger(__name__)


def adapters_for(config: dict[str, Any]) -> Adapters:
    """AWS, Terraform, GitHub Actions and Python, configured from the world's theseus.yaml."""
    return Adapters(
        iac=TerraformAdapter(config), cloud=AwsAdapter(config), ci=GithubAdapter(), code=PythonAdapter()
    )


def build_review(store: GraphStore, llm: Any, jev: Any, settings: Settings) -> routes.Review:
    """The real review behind `/analyze` (task A5): the world root at the PR's base and head commits, the
    Action's plans for them, then `run_pr`. The files are laid out as `<world>/pr<N>/<side>`, so the graphs
    get spec 03's names (`demo-infra__pr42-base`) and requirement lines in theseus.yaml stay citable."""

    def review(
        gh: GitHub,
        repo: str,
        number: int,
        head_sha: str,
        pr: dict[str, Any],
        base_plan: dict[str, Any],
        head_plan: dict[str, Any],
    ) -> AnalysisResult:
        base_files = gh.world_files(repo, pr["base"]["sha"])
        head_files = gh.world_files(repo, head_sha)
        if "theseus.yaml" not in head_files:
            raise IngestError(f"no {settings.theseus_world_root}/theseus.yaml at {head_sha[:7]}")
        adapters = adapters_for(yaml.safe_load(head_files["theseus.yaml"]) or {})
        deps = Deps(store=store, adapters=adapters, llm=llm, jev=jev, settings=settings)
        with TemporaryDirectory(prefix="theseus-review-") as tmp:
            root = Path(tmp) / settings.theseus_world_root / f"pr{number}"
            base = load_world_from_files(base_files, base_plan, adapters, root / "base")
            head = load_world_from_files(head_files, head_plan, adapters, root / "head")
            result = run_pr(base, head, pr.get("title") or "", pr.get("body") or "", deps)
        return result.model_copy(update={"repo": repo, "pr_number": number})

    return review


def build_render() -> webhooks.Render:
    """The renderer behind `/theseus apply` (task A9): the IaC adapter, configured from the head's own
    theseus.yaml as the review was, writes the fix's ops as verified edits on the head's files."""

    def render(files: dict[str, str], ops: list[PatchOp]) -> dict[str, str]:
        try:
            config = yaml.safe_load(files.get("theseus.yaml") or "") or {}
        except yaml.YAMLError as e:
            raise PatchError("theseus.yaml at the head cannot be read") from e
        if not isinstance(config, dict):
            raise PatchError("theseus.yaml at the head is not a mapping")
        return adapters_for(config).iac.render(files, ops)

    return render


def build_try(store: GraphStore, settings: Settings, recordings: Path = RECORDINGS) -> routes.Try:
    """The engine behind `/try/{preset}` (task S4): `analyze_fixture` on the preset's fixture folder in this
    store, with the models replayed whatever mode the server runs in, so a visit costs no LLM or Jev call. One
    run at a time: a fixture's graphs have fixed names, and two visitors must not load them at once. The
    recordings are read on the first visit, so missing ones fail that visit and never the server's startup.

    A run takes tens of seconds against FalkorDB Cloud, so each preset's result is kept: its fixtures and
    recordings change only with a deploy, which restarts the server, so a kept answer is the one a new run
    would give, and a visitor gets it at once."""
    replay = settings.model_copy(update={"theseus_mode": "replay"})
    lock = threading.Lock()
    models: list[tuple[ReplayedIntent, ReplayedJev]] = []
    kept: dict[str, AnalysisResult] = {}

    def run(preset: str) -> AnalysisResult:
        with lock:
            if preset in kept:
                return kept[preset]
            if not models:
                models.append((ReplayedIntent(recordings), ReplayedJev(replay, recordings)))
            llm, jev = models[0]
            result = analyze_fixture(routes.FIXTURES / preset, store, jev, replay, llm)
            kept[preset] = result
            return result

    return run


def warm_try(run: routes.Try) -> None:
    """Runs every preset once, so the first visitor after a deploy doesn't wait. A failure is logged and
    left for that preset's first visit to report."""
    for preset in sorted(routes.presets()):
        try:
            run(preset)
            log.info("try: %s is ready", preset)
        except TheseusError as e:
            log.warning("try: %s could not be computed ahead: %s", preset, e)


def build_scan(store: GraphStore, jev: Any, settings: Settings) -> routes.Scan:
    """The real scan behind `/scan` (task C3): a scan fixture's world, its plan, then `run_scan`."""

    def scan(fixture: str) -> AnalysisResult:
        root = routes.FIXTURES / fixture
        config = yaml.safe_load((root / "base" / "theseus.yaml").read_text(encoding="utf-8")) or {}
        adapters = adapters_for(config)
        plan = json.loads((root / "base.plan.json").read_text(encoding="utf-8"))
        deps = Deps(store=store, adapters=adapters, llm=None, jev=jev, settings=settings)
        return run_scan(load_world(root / "base", plan, adapters), deps)

    return scan


def build_posture(store: GraphStore, jev: Any, settings: Settings) -> routes.PostureRun:
    """The posture run behind `/posture` (O1 to O3): the world root at `main`'s commit, the workflow's plan of
    it, then `run_posture` with the advisory feed. The files are laid out as `<world>/`, so the graph is
    `demo-infra__main` and is replaced on every run."""

    def run(gh: GitHub, repo: str, sha: str, plan: dict[str, Any]) -> PostureReport:
        files = gh.world_files(repo, sha)
        if "theseus.yaml" not in files:
            raise IngestError(f"no {settings.theseus_world_root}/theseus.yaml at {sha[:7]}")
        adapters = adapters_for(yaml.safe_load(files["theseus.yaml"]) or {})
        deps = Deps(store=store, adapters=adapters, llm=None, jev=jev, settings=settings)
        advisories = load_advisories(Path(settings.theseus_advisories))
        with TemporaryDirectory(prefix="theseus-posture-") as tmp:
            world = load_world_from_files(files, plan, adapters, Path(tmp) / settings.theseus_world_root)
            report = run_posture(world, deps, advisories)
        return report.model_copy(update={"scan": report.scan.model_copy(update={"repo": repo})})

    return run


def build_finder(store: GraphStore, jev: Any, settings: Settings) -> routes.Finder:
    """Finding mode on a fixture folder (FM3 and FM4): its `base/` world and plan and its `advisory.json`,
    with live Jev for sensitivity and urgency. The advisory's text never becomes evidence."""

    def finder(fixture: Path) -> AnalysisResult:
        base = fixture / "base"
        try:
            config = yaml.safe_load((base / "theseus.yaml").read_text(encoding="utf-8")) or {}
            plan = json.loads((fixture / "base.plan.json").read_text(encoding="utf-8"))
            advisory = json.loads((fixture / "advisory.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError) as e:
            raise IngestError(f"cannot read the finding fixture {fixture.name}") from e
        adapters = adapters_for(config)
        deps = Deps(store=store, adapters=adapters, llm=None, jev=jev, settings=settings)
        return run_finding(load_world(base, plan, adapters), advisory, deps)

    return finder


# The public status feeds an incident check reads, and the adapter that reads each one.
STATUS_FEEDS: dict[str, tuple[str, status.Reader]] = {
    "aws": ("https://health.aws.amazon.com/public/currentevents", health.read_status),
    "github": ("https://www.githubstatus.com/api/v2/incidents/unresolved.json", github_status.read_status),
}


def connect_falkordb() -> Any:
    """A FalkorDB client from the environment and .env. Raises GraphError when it cannot connect."""
    return get_client(get_settings())


def falkordb_version(request: Request) -> str | None:
    """The version of the FalkorDB the app connected to at startup, or None if it stopped answering."""
    db = getattr(request.app.state, "falkordb", None)
    if db is None:
        return None
    try:
        return server_version(db)
    except GraphError as e:
        log.warning("FalkorDB stopped answering: %s", e)
        return None


def create_app(connect: Callable[[], Any] = connect_falkordb) -> FastAPI:
    """A new app with every route. `connect` runs at startup; tests pass a stand-in."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            app.state.falkordb = connect()
        except GraphError as e:
            log.error("not starting: %s", e)
            raise
        settings = get_settings()
        if settings.theseus_mode != "replay":
            load_client()
        llm = Llm(settings)
        app.state.store = FalkorStore(app.state.falkordb)
        jev = Jev(settings, llm=llm)
        app.state.review = build_review(app.state.store, llm, jev, settings)
        app.state.scan = build_scan(app.state.store, jev, settings)
        app.state.finder = build_finder(app.state.store, jev, settings)
        app.state.posture = build_posture(app.state.store, jev, settings)
        app.state.results = webhooks.Results()
        app.state.render = build_render()
        app.state.contain = lambda gh, repo, sha, result, page: contain.contain(
            gh, app.state.render, repo, sha, result, page
        )
        app.state.status_feeds = lambda: status.fetch_feeds(STATUS_FEEDS)
        app.state.try_preset = build_try(app.state.store, settings)
        if connect is connect_falkordb:  # a real server: compute the Try presets before anyone asks
            threading.Thread(target=warm_try, args=(app.state.try_preset,), daemon=True).start()
        app.state.try_limiter = routes.RateLimit()
        yield

    app = FastAPI(title="Theseus", version=__version__, lifespan=lifespan)
    # Graphs are JSON with much repetition; compressed, a review page's data is a tenth of its size.
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.include_router(routes.router)

    @app.get("/health")
    def health(response: Response, falkordb: str | None = Depends(falkordb_version)) -> dict[str, str]:
        """{status, falkordb, version}; status 503 while FalkorDB is unreachable."""
        if falkordb is None:
            response.status_code = 503
            return {"status": "degraded", "falkordb": "unreachable", "version": __version__}
        return {"status": "ok", "falkordb": falkordb, "version": __version__}

    return app


app = create_app()
