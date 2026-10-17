"""Command line: `python -m theseus analyze | finding | scan | serve`.

`serve` runs the API (F3); `analyze`, `finding` and `scan` print a PR, finding or scan fixture's
AnalysisResult as JSON (E3, FM3, C3). All of them need FalkorDB (rule 3). A composition root
(docs/spec/08-core-and-adapters.md): with api/app.py, the only place that picks adapters.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import uvicorn
import yaml

from theseus import __version__
from theseus.adapters.aws.adapter import AwsAdapter
from theseus.adapters.github.adapter import GithubAdapter
from theseus.adapters.python.adapter import PythonAdapter
from theseus.adapters.terraform.adapter import TerraformAdapter
from theseus.config import Settings, get_settings
from theseus.contracts.adapters import Adapters
from theseus.contracts.engine import Deps, GraphStore
from theseus.contracts.result import AnalysisResult
from theseus.engine.pipeline import run_finding, run_pr, run_scan
from theseus.errors import GraphError, TheseusError
from theseus.graph.client import get_client
from theseus.graph.store import FalkorStore
from theseus.importer.world import load_world


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for every command."""
    parser = argparse.ArgumentParser(prog="theseus", description="Review infrastructure changes as a graph.")
    parser.add_argument("--version", action="version", version=f"theseus {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    for name, text in (
        ("analyze", "analyze a PR fixture: base against head"),
        ("finding", "map the blast radius of an advisory fixture"),
        ("scan", "list dangerous paths and unused grants in main"),
    ):
        commands.add_parser(name, help=text).add_argument("fixture", help="a folder under fixtures/")
    commands.add_parser("serve", help="run the API on http://localhost:8000; needs FalkorDB")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its exit code."""
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return serve()
    if args.command == "analyze":
        return analyze(Path(args.fixture))
    if args.command == "finding":
        return finding(Path(args.fixture))
    if args.command == "scan":
        return scan(Path(args.fixture))
    print(f"theseus {args.command}: not implemented yet", file=sys.stderr)
    return 2


def adapters_for(root: Path) -> Adapters:
    """AWS, Terraform, GitHub Actions and Python, configured from the world root's theseus.yaml."""
    config = yaml.safe_load((root / "theseus.yaml").read_text(encoding="utf-8"))
    return Adapters(
        iac=TerraformAdapter(config), cloud=AwsAdapter(config), ci=GithubAdapter(), code=PythonAdapter()
    )


def analyze_fixture(
    fixture: Path, store: GraphStore, jev: Any, settings: Settings, llm: Any = None
) -> AnalysisResult:
    """PR mode on a fixture folder (`base/`, `head/`, their plans and `pr.md`) with this store and Jev."""
    scenario = yaml.safe_load((fixture / "scenario.yaml").read_text(encoding="utf-8")) or {}
    if scenario.get("mode") != "pr":
        raise TheseusError(f"{fixture} is a {scenario.get('mode')!r} fixture; analyze reads PR fixtures")
    adapters = adapters_for(fixture / "head")
    worlds = [
        load_world(
            fixture / side, json.loads((fixture / f"{side}.plan.json").read_text(encoding="utf-8")), adapters
        )
        for side in ("base", "head")
    ]
    title, _, body = (fixture / "pr.md").read_text(encoding="utf-8").partition("\n")
    deps = Deps(store=store, adapters=adapters, llm=llm, jev=jev, settings=settings)
    return run_pr(worlds[0], worlds[1], title.removeprefix("# ").strip(), body.strip(), deps)


def scan_fixture(fixture: Path, store: GraphStore, jev: Any, settings: Settings) -> AnalysisResult:
    """Scan mode on a fixture folder (`base/` and its plan, the state of `main`) with this store and Jev."""
    scenario = yaml.safe_load((fixture / "scenario.yaml").read_text(encoding="utf-8")) or {}
    if scenario.get("mode") != "scan":
        raise TheseusError(f"{fixture} is a {scenario.get('mode')!r} fixture; scan reads scan fixtures")
    adapters = adapters_for(fixture / "base")
    plan = json.loads((fixture / "base.plan.json").read_text(encoding="utf-8"))
    world = load_world(fixture / "base", plan, adapters)
    deps = Deps(store=store, adapters=adapters, llm=None, jev=jev, settings=settings)
    return run_scan(world, deps)


def scan(fixture: Path) -> int:
    """Print the fixture's scan result as JSON, or exit 1 when FalkorDB or the inputs fail (rule 3)."""
    from theseus.agent.jev import Jev
    from theseus.agent.llm import Llm

    settings = get_settings()
    try:
        store = FalkorStore(get_client(settings))
        result = scan_fixture(fixture, store, Jev(settings, llm=Llm(settings)), settings)
    except (TheseusError, OSError) as e:
        print(f"theseus scan: {e}", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2, by_alias=True))
    return 0


def analyze(fixture: Path) -> int:
    """Print the fixture's AnalysisResult as JSON, or exit 1 when FalkorDB or the inputs fail (rule 3)."""
    from theseus.agent.jev import Jev
    from theseus.agent.llm import Llm

    settings = get_settings()
    try:
        store = FalkorStore(get_client(settings))
        llm = Llm(settings)
        result = analyze_fixture(fixture, store, Jev(settings, llm=llm), settings, llm)
    except (TheseusError, OSError) as e:
        print(f"theseus analyze: {e}", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2, by_alias=True))
    return 0


def finding_fixture(fixture: Path, store: GraphStore, jev: Any, settings: Settings) -> AnalysisResult:
    """Finding mode on a fixture folder (`base/`, its plan and `advisory.json`) with this store and Jev."""
    scenario = yaml.safe_load((fixture / "scenario.yaml").read_text(encoding="utf-8")) or {}
    if scenario.get("mode") != "finding":
        raise TheseusError(f"{fixture} is a {scenario.get('mode')!r} fixture; finding reads finding fixtures")
    adapters = adapters_for(fixture / "base")
    plan = json.loads((fixture / "base.plan.json").read_text(encoding="utf-8"))
    advisory = json.loads((fixture / "advisory.json").read_text(encoding="utf-8"))
    deps = Deps(store=store, adapters=adapters, llm=None, jev=jev, settings=settings)
    return run_finding(load_world(fixture / "base", plan, adapters), advisory, deps)


def finding(fixture: Path) -> int:
    """Print the fixture's finding result as JSON, or exit 1 when FalkorDB or the inputs fail (rule 3)."""
    from theseus.agent.jev import Jev
    from theseus.agent.llm import Llm

    settings = get_settings()
    try:
        store = FalkorStore(get_client(settings))
        result = finding_fixture(fixture, store, Jev(settings, llm=Llm(settings)), settings)
    except (TheseusError, OSError) as e:
        print(f"theseus finding: {e}", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2, by_alias=True))
    return 0


def serve() -> int:
    """Run the API on localhost:8000, or exit 1 when FalkorDB cannot be reached (rule 3)."""
    try:
        get_client(get_settings())
    except GraphError as e:
        print(f"theseus serve: {e}", file=sys.stderr)
        return 1
    # Theseus's own messages, and each GitHub call httpx makes; uvicorn configures only its own loggers.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("theseus.api.app:app", host="127.0.0.1", port=8000)
    return 0


def run() -> None:
    """Console entry point."""
    sys.exit(main())
