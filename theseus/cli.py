"""Command line: `python -m theseus analyze | finding | scan | posture | incident | check | prune | serve`.

`serve` runs the API (F3); `analyze`, `finding` and `scan` print a PR, finding or scan fixture's
AnalysisResult as JSON (E3, FM3, C3); `posture` prints a world's posture report (O1 to O3), and
`incident` an outage's blast radius on it; `check` reviews the working tree's change against `main` before
there is a PR, also as a Claude Code hook; `prune` lists, and with `--yes` deletes, the graphs closed and
merged PRs left behind. All of them need FalkorDB (rule 3). A composition root
(docs/spec/08-core-and-adapters.md): with api/app.py, the only place that picks adapters.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import uvicorn
import yaml

from theseus import __version__
from theseus.adapters.aws.adapter import AwsAdapter
from theseus.adapters.github.adapter import GithubAdapter
from theseus.adapters.python.adapter import PythonAdapter
from theseus.adapters.terraform.adapter import TerraformAdapter
from theseus.adapters.terraform.runner import plan_json
from theseus.agent.render import check_text, verdict
from theseus.api.github import GitHub
from theseus.config import Settings, get_settings
from theseus.contracts.adapters import Adapters
from theseus.contracts.engine import Deps, GraphStore
from theseus.contracts.incident import Incident
from theseus.contracts.posture import PostureReport
from theseus.contracts.result import AnalysisResult
from theseus.engine.incident import blast, read_incident
from theseus.engine.pipeline import run_finding, run_posture, run_pr, run_scan
from theseus.engine.pr_graphs import PrunePlan, merge_states, plan_prune, world_name
from theseus.errors import GraphError, TheseusError
from theseus.graph.client import Memory, get_client, memory
from theseus.graph.load import delete_graph
from theseus.graph.store import FalkorStore
from theseus.importer.world import load_world

log = logging.getLogger(__name__)


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
    posture = commands.add_parser("posture", help="who reaches what, single points of failure, cost")
    posture.add_argument("world", help="a world root with theseus.yaml, e.g. fixtures/unused-grant/base")
    posture.add_argument("plan", help="its Terraform plan JSON, e.g. fixtures/unused-grant/base.plan.json")
    posture.add_argument("--advisories", default=None, help="the advisory feed folder (THESEUS_ADVISORIES)")
    outage = commands.add_parser("incident", help="what an outage of one service breaks in a world")
    outage.add_argument("world", help="a world root with theseus.yaml, e.g. fixtures/unused-grant/base")
    outage.add_argument("plan", help="its Terraform plan JSON")
    outage.add_argument("headline", nargs="?", default="", help='e.g. "AWS Lambda is down in eu-west-1"')
    outage.add_argument("--provider", help="instead of a headline: aws or github")
    outage.add_argument("--service", help="instead of a headline: a service code, e.g. lambda")
    outage.add_argument("--region", help="a region code; every region when left out")
    outage.add_argument("--degraded", action="store_true", help="degraded rather than down")
    pruning = commands.add_parser(
        "prune", help="delete the graphs of closed and merged PRs; a dry run unless --yes"
    )
    pruning.add_argument(
        "--yes", action="store_true", help="delete exactly the graphs listed; without it, only list them"
    )
    checking = commands.add_parser(
        "check", help="review the working tree's change against main, before there is a PR"
    )
    checking.add_argument("--base", default=None, help="the commit to compare with: origin/main, else main")
    checking.add_argument("--world", default=None, help="the world root; THESEUS_WORLD_ROOT by default")
    checking.add_argument("--intent", default="", help="what the change is for, in a sentence")
    checking.add_argument(
        "--with-models", action="store_true", help="also read the intent and design a fix with the LLM"
    )
    checking.add_argument("--json", action="store_true", help="print the AnalysisResult as JSON")
    checking.add_argument(
        "--hook", action="store_true", help="run as a Claude Code PreToolUse hook, reading its JSON on stdin"
    )
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
    if args.command == "posture":
        return posture(Path(args.world), Path(args.plan), args.advisories)
    if args.command == "incident":
        return incident(Path(args.world), Path(args.plan), args)
    if args.command == "check":
        return check(args)
    if args.command == "prune":
        return prune(args.yes)
    print(f"theseus {args.command}: not implemented yet", file=sys.stderr)
    return 2


def adapters_for(root: Path) -> Adapters:
    """AWS, Terraform, GitHub Actions and Python, configured from the world root's theseus.yaml."""
    config = yaml.safe_load((root / "theseus.yaml").read_text(encoding="utf-8"))
    return Adapters(
        iac=TerraformAdapter(config), cloud=AwsAdapter(config), ci=GithubAdapter(), code=PythonAdapter()
    )


def models(settings: Settings) -> tuple[Any, Any]:
    """The LLM and Jev the commands use. In replay, those that look recordings up by what they were asked
    (task S4), as the Try-it page does: the demo world grew after A1 and A2 recorded, so its requests no
    longer hash to their keys. In live and record, the real clients."""
    if settings.theseus_mode == "replay":
        from theseus.agent.replayed import ReplayedIntent, ReplayedJev

        return ReplayedIntent(), ReplayedJev(settings)
    from theseus.agent.jev import Jev
    from theseus.agent.llm import Llm

    llm = Llm(settings)
    return llm, Jev(settings, llm=llm)


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
    settings = get_settings()
    try:
        store = FalkorStore(get_client(settings))
        result = scan_fixture(fixture, store, models(settings)[1], settings)
    except (TheseusError, OSError) as e:
        print(f"theseus scan: {e}", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2, by_alias=True))
    return 0


def analyze(fixture: Path) -> int:
    """Print the fixture's AnalysisResult as JSON, or exit 1 when FalkorDB or the inputs fail (rule 3)."""
    settings = get_settings()
    try:
        store = FalkorStore(get_client(settings))
        llm, jev = models(settings)
        result = analyze_fixture(fixture, store, jev, settings, llm)
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
    settings = get_settings()
    try:
        store = FalkorStore(get_client(settings))
        result = finding_fixture(fixture, store, models(settings)[1], settings)
    except (TheseusError, OSError) as e:
        print(f"theseus finding: {e}", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2, by_alias=True))
    return 0


def load_advisories(folder: Path) -> list[dict[str, Any]]:
    """The advisory feed: one JSON object per file in `folder`, by file name. A file that is not one is
    skipped with a warning, so one bad entry never stops a scan; no folder means no advisories."""
    found: list[dict[str, Any]] = []
    if not folder.is_dir():
        log.info("no advisory feed at %s", folder)
        return found
    for path in sorted(folder.glob("*.json")):
        try:
            advisory = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("advisory %s cannot be read: %s", path.name, e)
            continue
        if not isinstance(advisory, dict) or not {"id", "action"} <= advisory.keys():
            log.warning("advisory %s needs at least an id and an action; skipped", path.name)
            continue
        found.append(advisory)
    return found


def posture_world(
    world_root: Path,
    plan: Path,
    store: GraphStore,
    jev: Any,
    settings: Settings,
    advisories: list[dict[str, Any]],
) -> PostureReport:
    """The posture of a world root on disk and its plan, with this store and Jev."""
    adapters = adapters_for(world_root)
    world = load_world(world_root, json.loads(plan.read_text(encoding="utf-8")), adapters)
    deps = Deps(store=store, adapters=adapters, llm=None, jev=jev, settings=settings)
    return run_posture(world, deps, advisories)


def posture(world_root: Path, plan: Path, feed: str | None) -> int:
    """Print the world's posture report as JSON, or exit 1 when FalkorDB or the inputs fail (rule 3)."""
    settings = get_settings()
    try:
        store = FalkorStore(get_client(settings))
        advisories = load_advisories(Path(feed or settings.theseus_advisories))
        jev = models(settings)[1]
        report = posture_world(world_root, plan, store, jev, settings, advisories)
    except (TheseusError, OSError) as e:
        print(f"theseus posture: {e}", file=sys.stderr)
        return 1
    print(report.model_dump_json(indent=2, by_alias=True))
    return 0


def incident(world_root: Path, plan: Path, args: argparse.Namespace) -> int:
    """Print an outage's blast radius on the world as JSON: its posture first, then the incident a headline
    names (or the one given with --provider and --service). Exit 1 when FalkorDB or the inputs fail, and 2
    when the headline names no service Theseus maps."""
    settings = get_settings()
    try:
        store = FalkorStore(get_client(settings))
        jev = models(settings)[1]
        basis = posture_world(world_root, plan, store, jev, settings, []).posture.outage
    except (TheseusError, OSError) as e:
        print(f"theseus incident: {e}", file=sys.stderr)
        return 1
    found: Incident | None
    if args.headline.strip():
        found = read_incident(args.headline, basis.terms, basis.regions)
    else:
        term = next(
            (t for t in basis.terms if (t.provider, t.service) == (args.provider, args.service)), None
        )
        found = (
            None
            if term is None
            else Incident(provider=term.provider, service=term.service, title=term.name, source="picker")
        )
    if found is None:
        names = ", ".join(sorted(f"{t.provider}/{t.service}" for t in basis.terms))
        print(f"theseus incident: name a service Theseus maps: {names}", file=sys.stderr)
        return 2
    update: dict[str, Any] = {"region": args.region or found.region}
    if args.degraded:
        update["severity"] = "degraded"
    report = blast(basis, found.model_copy(update=update))
    print(report.model_dump_json(indent=2))
    return 0


# The check before a PR ------------------------------------------------------------------------------------

# The commands a check runs before, as a hook: those that commit, push or open a pull request.
SHIPS = re.compile(r"\b(git\s+(commit|push)|gh\s+pr\s+create)\b")
SKIP_COPY = shutil.ignore_patterns(".terraform", "*.tfstate*", "tfplan", "__pycache__", ".theseus")
AGAIN = (
    "\n\nTell the person what this change opens and offer the fix. Run the command again only if they still"
    " want it as it is."
)


def git(repo: Path, *args: str) -> bytes:
    """Run git in `repo`. A failure is a TheseusError with git's own message."""
    try:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    except FileNotFoundError:
        raise TheseusError("git is not installed or not on PATH") from None
    if done.returncode != 0:
        raise TheseusError(f"git {args[0]}: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def base_ref(repo: Path, wanted: str | None = None) -> str:
    """The commit to compare with: `wanted`, else origin/main, else main."""
    for ref in [wanted] if wanted else ["origin/main", "main"]:
        try:
            git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        except TheseusError:
            continue
        return ref
    raise TheseusError(f"no commit to compare with: {wanted or 'origin/main or main'} does not exist")


def world_changed(repo: Path, ref: str, world_root: str) -> bool:
    """Whether the working tree's world root differs from `ref`'s, committed or not, new files included."""
    if git(repo, "diff", "--name-only", ref, "--", world_root).strip():
        return True
    return bool(git(repo, "ls-files", "--others", "--exclude-standard", "--", world_root).strip())


def prepare_change(
    repo: Path,
    ref: str,
    world_root: str,
    folder: Path,
    plan: Callable[[Path], dict[str, Any]],
    intent: str = "",
) -> Path:
    """The working tree's change as a PR fixture in `folder` (`fixtures/local-<world>/`): `base/` as `ref`
    has the world root, `head/` as the working tree has it, both plans (`plan` turns a Terraform folder into
    its plan JSON), and `pr.md` holding the intent."""
    fixture = folder / "fixtures" / f"local-{Path(world_root).name}"
    fixture.mkdir(parents=True)
    archive = git(repo, "archive", "--format=tar", ref, "--", world_root)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(folder / "archive", filter="data")
    shutil.move(folder / "archive" / world_root, fixture / "base")
    shutil.copytree(repo / world_root, fixture / "head", ignore=SKIP_COPY)
    for side in ("base", "head"):
        planned = plan(fixture / side / "terraform")
        (fixture / f"{side}.plan.json").write_text(json.dumps(planned), encoding="utf-8")
    (fixture / "scenario.yaml").write_text("mode: pr\n", encoding="utf-8")
    (fixture / "pr.md").write_text(f"# {intent.strip() or 'A local change'}\n", encoding="utf-8")
    return fixture


def check_change(
    repo: Path,
    ref: str,
    world_root: str,
    store: GraphStore,
    settings: Settings,
    intent: str = "",
    with_models: bool = False,
    plan: Callable[[Path], dict[str, Any]] | None = None,
) -> AnalysisResult:
    """The working tree's change against `ref`, reviewed as a PR would be, then its graphs deleted. The LLM
    reads the intent and designs a fix only `with_models`; otherwise the check is the engine and Jev alone."""
    llm, jev = models(settings)
    with tempfile.TemporaryDirectory(prefix="theseus-check-") as tmp:
        fixture = prepare_change(repo, ref, world_root, Path(tmp), plan or planner(repo), intent)
        result = analyze_fixture(fixture, store, jev, settings, llm if with_models else None)
    drop_graphs(store, result.graphs["head"])
    return result


def planner(repo: Path) -> Callable[[Path], dict[str, Any]]:
    """Terraform plans for a local check, cached in the repo's `.theseus/plans`."""
    cache = repo / ".theseus" / "plans"
    return lambda terraform: plan_json(terraform, cache)


def drop_graphs(store: GraphStore, graph: str) -> None:
    """Delete a local check's graphs: its two sides and every candidate's copy share `graph`'s prefix."""
    prefix = graph.rsplit("__", 1)[0] + "__"
    for name in store.list_graphs():
        if name.startswith(prefix):
            delete_graph(store, name)


def _hook_reply(decision: str, reason: str) -> str:
    output = {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }
    return json.dumps({"hookSpecificOutput": output})


def hook(event: dict[str, Any], run: Callable[[Path], AnalysisResult | None], seen: Path) -> str:
    """What the PreToolUse hook answers for one tool call: nothing for a command that does not commit, push
    or open a PR, or for a clear change; `deny` with the check the first time a change would be blocked, so
    the agent explains it and offers the fix; `ask` with it after that, or when the change needs a look.
    `run` returns None when the world root did not change. `seen` keeps the changes already denied once."""
    command = str((event.get("tool_input") or {}).get("command", ""))
    if event.get("tool_name") != "Bash" or not SHIPS.search(command):
        return ""
    result = run(Path(str(event.get("cwd") or ".")))
    if result is None:
        return ""
    level = verdict(result).level
    if level == "clear":
        return ""
    reason = check_text(result)
    key = hashlib.sha256(reason.encode()).hexdigest()[:16]
    denied = set(seen.read_text(encoding="utf-8").split()) if seen.is_file() else set()
    if level == "blocked" and key not in denied:
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text("\n".join(sorted(denied | {key})) + "\n", encoding="utf-8")
        return _hook_reply("deny", reason + AGAIN)
    return _hook_reply("ask", reason)


def check(args: argparse.Namespace) -> int:
    """Print the check of the working tree's change: exit 0 when clear or it needs a look, 2 when it would be
    blocked, 1 when it cannot be checked. As a hook, read the tool call on stdin, answer on stdout and always
    exit 0: a check that cannot run never stops the command (the reason goes to stderr)."""
    # The check has arrows in it; a Windows pipe or console would otherwise print in its code page.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = get_settings()
    world_root = args.world or settings.theseus_world_root

    def run(repo: Path) -> AnalysisResult | None:
        root = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip())
        ref = base_ref(root, args.base)
        if args.hook and not world_changed(root, ref, world_root):
            return None
        store = FalkorStore(get_client(settings))
        return check_change(root, ref, world_root, store, settings, args.intent, args.with_models)

    if args.hook:
        try:
            event = json.loads(sys.stdin.read() or "{}")
            reply = hook(event, run, Path(str(event.get("cwd") or ".")) / ".theseus" / "denied")
        except (TheseusError, OSError, ValueError) as e:
            print(f"theseus check: {e}; the command runs unchecked", file=sys.stderr)
            return 0
        if reply:
            print(reply)
        return 0
    try:
        result = run(Path.cwd())
    except (TheseusError, OSError) as e:
        print(f"theseus check: {e}", file=sys.stderr)
        return 1
    if result is None:
        print("theseus check: the world root has no change against the base")
        return 0
    print(result.model_dump_json(indent=2, by_alias=True) if args.json else check_text(result))
    return 2 if verdict(result).level == "blocked" else 0


# What one review graph costs on FalkorDB Cloud, on average: the 49 graphs leaked by tests took about 40 MB. A
# graph's own size cannot be read (`GRAPH.MEMORY USAGE` says 0), so the dry run estimates, and `--yes`
# measures with the server's memory before and after.
GRAPH_MB = 0.8


def _read_memory(db: Any) -> Memory | None:
    """The server's memory, or None (with a warning) when it will not say: pruning does not need it."""
    try:
        return memory(db)
    except GraphError as e:
        log.warning("%s", e)
        return None


def _memory_line(reading: Memory | None) -> str:
    if reading is None:
        return "FalkorDB's memory is not available."
    limit = f" of {reading.limit_mb:.1f} MB" if reading.limit_mb else ""
    return f"{reading.used_mb:.1f} MB used{limit}"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def describe_prune(world: str, repos: list[str], plan: PrunePlan, reading: Memory | None) -> str:
    """What `prune` found, to read before running it with `--yes`: each closed or merged PR with its graphs
    named, what it keeps (counts only), and the memory."""
    asked = ", ".join(repos)
    lines = [f"World {world}; asking GitHub about {asked}.", f"FalkorDB: {_memory_line(reading)}", ""]
    if plan.delete:
        lines.append("Graphs of closed and merged PRs:")
        for group in plan.delete:
            lines.append(f"  #{group.number} {group.state}")
            lines.extend(f"    {name}" for name in group.graphs)
        total = len(plan.names)
        lines.append(f"That is {_count(total, 'graph')}, about {total * GRAPH_MB:.1f} MB.")
    else:
        lines.append("Nothing to delete: no closed or merged PR has graphs.")
    if plan.keep:
        lines += ["", "Kept:"]
        for group in plan.keep:
            why = "not in GitHub's list" if group.state == "unknown" else group.state
            lines.append(f"  #{group.number} {why}: {_count(len(group.graphs), 'graph')}")
    return "\n".join(lines)


def prune(yes: bool) -> int:
    """List the graphs of closed and merged PRs, and with `yes` delete exactly those, by name, printing the
    memory before and after. Exit 1 when THESEUS_REPOS, FalkorDB or GitHub fail: nothing is deleted then. The
    PRs' states come from GitHub in this run, so a PR reopened since an earlier dry run keeps its graphs."""
    settings = get_settings()
    try:
        if not settings.repos:
            raise TheseusError("THESEUS_REPOS lists no repository to ask which PRs are closed")
        db = get_client(settings)
        store = FalkorStore(db)
        gh = GitHub(settings)
        states = merge_states(gh.pull_states(repo) for repo in settings.repos)
        world = world_name(settings.theseus_world_root)
        plan = plan_prune(store.list_graphs(), world, states)
        before = _read_memory(db)
        print(describe_prune(world, settings.repos, plan, before))
        print()
        if not yes:
            print("Dry run: nothing was deleted. Run it again with --yes to delete the graphs listed above.")
            return 0
        for name in plan.names:
            delete_graph(store, name)
            print(f"deleted {name}")
        after = _read_memory(db)
    except (TheseusError, OSError) as e:
        print(f"theseus prune: {e}", file=sys.stderr)
        return 1
    print(f"Deleted {_count(len(plan.names), 'graph')}.")
    if before is not None and after is not None:
        limit = f" ({after.limit_mb:.1f} MB limit)" if after.limit_mb else ""
        print(f"Memory: {before.used_mb:.1f} MB before, {after.used_mb:.1f} MB after{limit}.")
    else:
        print("Memory: the server's memory is not available, so there is no before and after.")
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
