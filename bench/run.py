"""Generate benchmark inputs and compare actual engine results with human answer keys."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import platform
import re
import shutil
import socket
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from typing import Any

import yaml
from pydantic import Field
from redis.exceptions import RedisError

from bench.checkov import (
    CheckovComparison,
    CheckovError,
    CheckovReport,
    ScanFailure,
    check_version,
    compare_reports,
    scan,
)
from theseus.agent.jev import Jev
from theseus.agent.llm import Llm, LlmReply
from theseus.agent.render import escape, verdict
from theseus.cli import adapters_for
from theseus.config import Settings, get_settings
from theseus.contracts.engine import Deps, FlowResult, FlowRow, GraphDelta, GraphStore
from theseus.contracts.result import AnalysisResult, Contract, GraphRows, compare, project
from theseus.engine.pipeline import run_pr
from theseus.errors import GraphError, IngestError, ModelError, TheseusError
from theseus.graph.client import get_client, server_version
from theseus.graph.store import FalkorStore
from theseus.importer.world import load_world
from tools.make_fixture import (
    COPY_IGNORE,
    PUBLIC_ACCESS_BLOCK,
    SCENARIOS,
    Edit,
    Scenario,
    _publish,
    _RecoveryError,
    apply_changes,
    plan_world,
    resolve_bash,
)

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]*\Z")


@contextmanager
def benchmark_lock(database: Any) -> Iterator[Callable[[], None]]:
    """Yield during an exclusive graph-backed session, without Redis key-write permissions."""
    # The empty coordination graph persists like theseus__docs. Its transient owner is not a result ID.
    # No automatic expiry: a crashed run leaves a visible lock instead of letting another run overwrite it.
    graph = database.select_graph("theseus__benchmark")
    try:
        with TemporaryDirectory(prefix="theseus-benchmark-owner-") as directory:
            owner = socket.gethostname() + ":" + Path(directory).name
            rows = graph.query(
                "MERGE (l:Node {id: 'entry:benchmark-lock'}) ON CREATE SET l.owner = $owner RETURN l.owner",
                {"owner": owner},
            ).result_set
            if rows != [[owner]]:
                raise GraphError("another benchmark owns theseus__benchmark; inspect any abandoned run")
            try:
                yield lambda: None
            finally:
                graph.query(
                    "MATCH (l:Node {id: 'entry:benchmark-lock'}) WHERE l.owner = $owner DELETE l",
                    {"owner": owner},
                )
    except RedisError as exc:
        raise GraphError("could not acquire or retain the exclusive benchmark lock") from exc


class CaseSpec(Contract):
    id: str
    scenario: Scenario


class Case(Contract):
    id: str
    root: Path
    expected: dict[str, Any]


class Observation(Contract):
    matches: bool
    differences: list[str]
    certain_paths: int
    unknown_paths: int
    code_uses: int
    product_verdict: str
    expected_paths: int | None = None
    expected_code_uses: int | None = None


class RunRecord(Contract):
    case: str
    inputs: dict[str, str]
    result: AnalysisResult | None = None
    observation: Observation | None = None
    checkov: CheckovComparison | None = None
    incomplete_scans: dict[str, CheckovReport | ScanFailure] = Field(default_factory=dict)
    recordings: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, str] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class OwnedStore:
    """A graph-store proxy that refuses to overwrite or delete another run's graphs."""

    def __init__(
        self, store: GraphStore, prefix: str, check_owner: Callable[[], None] = lambda: None
    ) -> None:
        self.store = store
        self.prefix = prefix
        self.owned: set[str] = set()
        self.check_owner = check_owner

    def __getattr__(self, name: str) -> Any:
        if name not in {
            "list_graphs",
            "view",
            "paths",
            "betweenness",
            "workflows_using",
            "unused_grants",
            "calls",
        }:
            raise GraphError(f"benchmark does not delegate store operation {name}")
        return getattr(self.store, name)

    def _reserve(self, graph: str) -> None:
        self.check_owner()
        if not graph.startswith(self.prefix):
            raise GraphError(f"benchmark cannot write outside {self.prefix}: {graph}")
        if graph not in self.owned and graph in self.store.list_graphs():
            raise GraphError(f"refusing to replace existing graph {graph}")
        self.owned.add(graph)  # A partially successful load/copy must be cleaned up too.

    def load(self, graph: str, rows: GraphRows) -> None:
        self._reserve(graph)
        self.store.load(graph, rows)

    def copy(self, src: str, dst: str) -> None:
        if src not in self.owned:
            raise GraphError(f"benchmark does not own copy source {src}")
        self._reserve(dst)
        self.store.copy(src, dst)

    def apply_delta(self, graph: str, delta: GraphDelta) -> None:
        self.check_owner()
        if graph not in self.owned:
            raise GraphError(f"benchmark does not own {graph}")
        self.store.apply_delta(graph, delta)

    def max_flow(self, graph: str, sources: list[str], sinks: list[str], rows: list[FlowRow]) -> FlowResult:
        self.check_owner()
        if graph not in self.owned:
            raise GraphError(f"benchmark does not own {graph}")
        return self.store.max_flow(graph, sources, sinks, rows)

    def delete(self, graph: str) -> None:
        self.check_owner()
        if graph not in self.owned:
            raise GraphError(f"benchmark does not own {graph}")
        self.store.delete(graph)
        self.owned.remove(graph)

    def cleanup(self) -> None:
        """Remove all owned graphs, reporting every failed deletion."""
        errors = []
        for graph in sorted(self.owned):
            try:
                self.delete(graph)
            except GraphError as exc:
                errors.append(f"{graph}: {exc}")
        if errors:
            raise GraphError("benchmark cleanup failed: " + "; ".join(errors))


def _scenario(description: str, *, edits: list[Edit] | None = None, addition: str = "") -> Scenario:
    return Scenario(
        mode="pr",
        description=description,
        title=description,
        body="Synthetic benchmark change; review the resulting access.",
        edits=edits or [],
        file="terraform/people.tf" if addition else "",
        addition=addition,
    )


def _policy(statements: list[dict[str, Any]]) -> str:
    document = json.dumps({"Version": "2012-10-17", "Statement": statements}, sort_keys=True)
    return (
        '\nresource "aws_iam_user_policy" "benchmark_priya" {\n'
        '  name = "benchmark-priya"\n  user = "priya-intern"\n'
        f"  policy = {json.dumps(document)}\n}}\n"
    )


def case_specs() -> list[CaseSpec]:
    """Return the twenty source mutations, without computed outcomes or answer keys."""
    secret = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:prod-db-credentials-*"
    invoices = "arn:aws:s3:::demo-company-files/invoices/*"
    secret_allow: dict[str, Any] = {
        "Sid": "ReadSecret",
        "Effect": "Allow",
        "Action": "secretsmanager:GetSecretValue",
        "Resource": secret,
    }
    pinned = (
        "StringEquals = {\n"
        '          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"\n'
        '          "token.actions.githubusercontent.com:sub" = "repo:demo-org/infra:environment:production"\n'
        "        }"
    )
    wide = (
        'StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }\n'
        '        StringLike = { "token.actions.githubusercontent.com:sub" = "repo:demo-org/*" }'
    )
    public = SCENARIOS["public-bucket"]
    legacy = (
        'resource "aws_iam_role_policy" "support_portal" {\n'
        '  name = "support-portal"\n  role = "support-portal"\n  policy = jsonencode({\n'
        '    Version = "2012-10-17"\n    Statement = [{\n'
        "      # Kept for the Postgres migration; remove after billing-api owns every database request.\n"
        '      Sid      = "LegacyDbSecret"\n      Effect   = "Allow"\n'
        '      Action   = "secretsmanager:GetSecretValue"\n'
        f'      Resource = "{secret}"\n    }}]\n  }})\n}}\n'
    )
    raw_policy = public.addition.replace("company_files_public", "data_lake_public").replace(
        "demo-company-files", "demo-data-lake"
    )
    block = PUBLIC_ACCESS_BLOCK.replace("company_files", "data_lake").replace(
        "aws_s3_bucket.company_files", "aws_s3_bucket.data_lake"
    )
    specifications = [
        ("01-intern-membership", SCENARIOS["intern"].model_copy(deep=True)),
        ("02-public-invoices", public.model_copy(deep=True)),
        (
            "03-analyst-raw",
            _scenario(
                "Allow analysts to read raw data",
                edits=[
                    Edit(
                        file="terraform/policies.tf",
                        find='Resource = "arn:aws:s3:::demo-data-lake/curated/*"',
                        replace='Resource = "arn:aws:s3:::demo-data-lake/*"',
                    )
                ],
            ),
        ),
        (
            "04-public-raw",
            Scenario(
                mode="pr",
                description="Make raw data public",
                title="Make raw data public",
                body="Publish exports.",
                file="terraform/data.tf",
                addition=raw_policy,
                edits=[
                    Edit(
                        file="terraform/platform.tf",
                        find=block.replace("{policy}", "true"),
                        replace=block.replace("{policy}", "false"),
                    )
                ],
            ),
        ),
        (
            "05-secret-wildcard",
            _scenario(
                "Give Priya secret access",
                addition=_policy(
                    [
                        {**secret_allow, "Resource": "*"},
                    ]
                ),
            ),
        ),
        (
            "06-shared-policy-wildcard",
            _scenario(
                "Broaden shared log access",
                edits=[
                    Edit(
                        file="terraform/policies.tf",
                        find='Resource = ["arn:aws:s3:::demo-app-logs/*", "arn:aws:s3:::demo-app-logs"]',
                        replace='Resource = "*"',
                    )
                ],
            ),
        ),
        (
            "07-oidc-no-sub",
            _scenario(
                "Remove the apply subject restriction",
                edits=[
                    Edit(
                        file="terraform/ci.tf",
                        find=pinned,
                        replace='StringEquals = { "token.actions.githubusercontent.com:aud"'
                        ' = "sts.amazonaws.com" }',
                    )
                ],
            ),
        ),
        (
            "08-oidc-wide-sub",
            _scenario(
                "Widen the apply subject restriction",
                edits=[
                    Edit(
                        file="terraform/ci.tf",
                        find=pinned,
                        replace=wide,
                    )
                ],
            ),
        ),
        ("09-code-export", SCENARIOS["code-pr"].model_copy(deep=True)),
        (
            "10-support-raw-grant",
            _scenario(
                "Add support access to raw data",
                edits=[
                    Edit(
                        file="terraform/roles.tf",
                        find='        Sid      = "ReadInvoices"',
                        replace='        Sid      = "ReadRaw"\n        Effect = "Allow"\n'
                        '        Action = "s3:GetObject"\n'
                        '        Resource = "arn:aws:s3:::demo-data-lake/raw/*"\n      },\n      {\n'
                        '        Sid      = "ReadInvoices"',
                    )
                ],
            ),
        ),
        (
            "11-public-prefix-only",
            public.model_copy(
                update={
                    "addition": public.addition.replace(
                        "demo-company-files/*", "demo-company-files/public/*"
                    ),
                    "description": "Publish only the public prefix",
                },
                deep=True,
            ),
        ),
        (
            "12-intern-logs-only",
            _scenario(
                "Give Priya app log access",
                addition=_policy(
                    [
                        {
                            "Sid": "ReadLogs",
                            "Effect": "Allow",
                            "Action": "s3:GetObject",
                            "Resource": "arn:aws:s3:::demo-app-logs/*",
                        }
                    ]
                ),
            ),
        ),
        (
            "13-equivalent-curated",
            _scenario(
                "Keep curated access equivalent",
                edits=[
                    Edit(
                        file="terraform/policies.tf",
                        find='Action   = "s3:GetObject"\n'
                        '      Resource = "arn:aws:s3:::demo-data-lake/curated/*"',
                        replace='Action   = ["s3:GetObject"]\n'
                        '      Resource = ["arn:aws:s3:::demo-data-lake/curated/*"]',
                    )
                ],
            ),
        ),
        (
            "14-remove-unused-secret",
            _scenario(
                "Remove unused portal secret access",
                edits=[
                    Edit(
                        file="terraform/services.tf",
                        find=legacy,
                        replace="",
                    )
                ],
            ),
        ),
        (
            "15-pin-deploy-trust",
            _scenario(
                "Pin the release workflow subject",
                edits=[
                    Edit(
                        file="terraform/ci.tf",
                        find='StringLike = { "token.actions.githubusercontent.com:sub" = "repo:demo-org/*" }',
                        replace='StringLike = { "token.actions.githubusercontent.com:sub" = '
                        '"repo:demo-org/infra:ref:refs/heads/main" }',
                    )
                ],
            ),
        ),
        (
            "16-unconditional-deny",
            _scenario(
                "Deny invoice reads",
                addition=_policy(
                    [
                        {
                            "Sid": "AllowInvoices",
                            "Effect": "Allow",
                            "Action": "s3:GetObject",
                            "Resource": invoices,
                        },
                        {
                            "Sid": "DenyInvoices",
                            "Effect": "Deny",
                            "Action": "s3:GetObject",
                            "Resource": invoices,
                        },
                    ]
                ),
            ),
        ),
        (
            "17-conditional-secret",
            _scenario(
                "Restrict secret access by source IP",
                addition=_policy(
                    [
                        {**secret_allow, "Condition": {"IpAddress": {"aws:SourceIp": "192.0.2.0/24"}}},
                    ]
                ),
            ),
        ),
        (
            "18-notaction",
            _scenario(
                "Use a NotAction policy",
                addition=_policy(
                    [
                        {
                            "Sid": "ExceptDelete",
                            "Effect": "Allow",
                            "NotAction": "secretsmanager:DeleteSecret",
                            "Resource": secret,
                        }
                    ]
                ),
            ),
        ),
        (
            "19-notresource",
            _scenario(
                "Use a NotResource policy",
                addition=_policy(
                    [
                        {
                            "Sid": "ExceptPayments",
                            "Effect": "Allow",
                            "Action": "secretsmanager:GetSecretValue",
                            "NotResource": "arn:aws:secretsmanager:eu-west-1:111122223333:"
                            "secret:payments-api-key-*",
                        }
                    ]
                ),
            ),
        ),
        (
            "20-permission-boundary",
            _scenario(
                "Add a permission boundary and secret grant",
                edits=[
                    Edit(
                        file="terraform/people.tf",
                        find='  name = "priya-intern"',
                        replace='  name = "priya-intern"\n'
                        "  permissions_boundary = aws_iam_policy.app_logs_read.arn",
                    )
                ],
                addition=_policy([secret_allow]),
            ),
        ),
    ]
    return [CaseSpec(id=identifier, scenario=scenario) for identifier, scenario in specifications]


def generate_case(spec: CaseSpec, source: Path, output: Path, *, bash: str) -> None:
    """Generate one case through the plan tool, preserving all human-owned files."""
    source, output = source.resolve(), output.resolve()
    if not IDENTIFIER.fullmatch(spec.id):
        raise IngestError("invalid case identifier")
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise IngestError("benchmark output and source must be separate")
    if output.is_relative_to(ROOT / "fixtures") or output.is_relative_to(ROOT / "demo-infra"):
        raise IngestError("benchmark generation cannot write product fixtures or demo source")
    target = output / spec.id
    if target.is_symlink():
        raise IngestError("benchmark case cannot be a symlink")
    output.mkdir(parents=True, exist_ok=True)
    # The existing publisher backs up only generated inputs; expected.json is never among its owned paths.
    staging = Path(mkdtemp(prefix=f".{spec.id}-", dir=output))
    preserve = False
    try:
        shutil.copytree(source, staging / "base", ignore=COPY_IGNORE)
        shutil.copytree(staging / "base", staging / "head")
        apply_changes(spec.scenario, staging / "head")
        for side in ("base", "head"):
            plan_world(staging / side, staging / f"{side}.plan.json", bash=bash)
        (staging / "scenario.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": spec.id,
                    "mode": "pr",
                    "world": "demo-infra",
                    "description": spec.scenario.description,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (staging / "pr.md").write_text(f"# {spec.scenario.title}\n\n{spec.scenario.body}\n", encoding="utf-8")
        target.mkdir(exist_ok=True)
        _publish(staging, target)
    except _RecoveryError:
        preserve = True
        raise
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise IngestError(f"could not generate {spec.id}: {type(exc).__name__}") from exc
    finally:
        if not preserve:
            shutil.rmtree(staging)


def read_case(root: Path) -> Case:
    """Return a complete PR case with a nonempty human-written comparison key."""
    identifier = root.name
    if not IDENTIFIER.fullmatch(identifier):
        raise IngestError(f"invalid case ID: {identifier}")
    key = root / "expected.json"
    if not key.is_file():
        raise IngestError(f"{identifier}: human-owned expected.json is missing")
    try:
        expected = json.loads(key.read_text(encoding="utf-8"))
        if not isinstance(expected, dict) or not expected:
            raise IngestError(f"{identifier}: expected.json is empty or not an object")
        unknown = sorted(expected.keys() - project(AnalysisResult(mode="pr")).keys())
        if unknown:
            raise IngestError(f"{identifier}: unknown comparison keys: {unknown}")
        metadata = yaml.safe_load((root / "scenario.yaml").read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or metadata.get("mode") != "pr":
            raise IngestError(f"{identifier}: benchmark requires a PR scenario")
        if metadata.get("name") != identifier:
            raise IngestError(f"{identifier}: scenario name must match its case directory")
        for name in ("base", "head"):
            if not (root / name / "theseus.yaml").is_file() or not (root / name / "terraform").is_dir():
                raise IngestError(f"{identifier}: incomplete {name} world")
            plan = json.loads((root / f"{name}.plan.json").read_text(encoding="utf-8"))
            if not isinstance(plan, dict) or not isinstance(plan.get("planned_values"), dict):
                raise IngestError(f"{identifier}: incomplete {name} plan")
        if not (root / "pr.md").is_file():
            raise IngestError(f"{identifier}: pr.md is missing")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise IngestError(f"{identifier}: cannot read case inputs") from exc
    return Case(id=identifier, root=root.resolve(), expected=expected)


def evaluate(result: AnalysisResult, expected: dict[str, Any]) -> Observation:
    """Return full projection differences and certain/uncertain observations separately."""
    differences = sorted(compare(project(result), expected))
    return Observation(
        matches=not differences,
        differences=differences,
        certain_paths=sum(not path.unknown for path in result.opened),
        unknown_paths=sum(path.unknown for path in result.opened),
        code_uses=len(result.use_beyond_intent),
        product_verdict=verdict(result).level,
        expected_paths=len(expected["opened"]) if isinstance(expected.get("opened"), list) else None,
        expected_code_uses=len(expected["use_beyond_intent"])
        if isinstance(expected.get("use_beyond_intent"), list)
        else None,
    )


class AuditedLlm:
    """Call the standard wrapper while retaining errors the optional fixer may catch."""

    def __init__(self, llm: Llm) -> None:
        self.llm = llm
        self.errors: list[str] = []

    def call(self, purpose: str, *args: Any, **kwargs: Any) -> LlmReply:
        try:
            return self.llm.call(purpose, *args, **kwargs)
        except ModelError as exc:
            self.errors.append(f"{purpose}: {exc}")
            raise


def input_hashes(root: Path) -> dict[str, str]:
    """Return content digests of case inputs, excluding previous observations and tool caches."""
    files = [
        root / name
        for name in ("scenario.yaml", "pr.md", "base.plan.json", "head.plan.json", "expected.json")
    ]
    for side in ("base", "head"):
        files.extend(
            p
            for p in (root / side).rglob("*")
            if p.is_file()
            and not any(part in {"__pycache__", ".terraform", ".git"} for part in p.relative_to(root).parts)
        )
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def code_provenance() -> dict[str, str]:
    """Return revision and source digest, including local code that has not been committed yet."""
    paths = [
        *ROOT.joinpath("theseus").rglob("*.py"),
        *ROOT.joinpath("bench").glob("*.py"),
        ROOT / "tools/make_fixture.py",
        ROOT / "tools/plan.sh",
        ROOT / "pyproject.toml",
    ]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise IngestError("cannot identify benchmark source revision") from exc
    return {"commit": revision, "source_sha256": digest.hexdigest(), "python": platform.python_version()}


def run_case(
    case: Case,
    backing: GraphStore,
    settings: Settings,
    recordings: Path,
    *,
    check_owner: Callable[[], None] = lambda: None,
    record_models: bool = False,
) -> RunRecord:
    """Return the actual engine/checker observations and errors for one isolated case."""
    hashes = input_hashes(case.root)
    record = RunRecord(case=case.id, inputs=hashes)
    record.provenance = code_provenance()
    mode = "record" if record_models else "replay"
    record.provenance.update(
        {
            "configured_llm_model": settings.llm_model,
            "configured_jev_model": settings.jev_model,
            "model_mode": mode,
        }
    )
    scoped = OwnedStore(backing, f"s2-{case.id}__", check_owner)
    client_settings = settings.model_copy(update={"theseus_mode": mode})
    llm = AuditedLlm(Llm(client_settings, recordings=recordings / "llm"))
    try:
        with TemporaryDirectory(prefix="theseus-bench-") as directory:
            world_root = Path(directory) / f"s2-{case.id}" / "pr1"
            world_root.mkdir(parents=True)
            for side in ("base", "head"):
                shutil.copytree(case.root / side, world_root / side, ignore=COPY_IGNORE)
            adapters = adapters_for(world_root / "head")
            worlds = [
                load_world(
                    world_root / side,
                    json.loads((case.root / f"{side}.plan.json").read_text(encoding="utf-8")),
                    adapters,
                )
                for side in ("base", "head")
            ]
            deps = Deps(
                store=scoped,
                adapters=adapters,
                settings=client_settings,
                llm=llm,
                jev=Jev(client_settings, recordings=recordings / "jev"),
            )
            title, _, body = (case.root / "pr.md").read_text(encoding="utf-8").partition("\n")
            result = run_pr(worlds[0], worlds[1], title.removeprefix("# ").strip(), body.strip(), deps)
            # The validated input supplies this metadata; engine-derived facts are kept verbatim.
            record.result = result.model_copy(update={"scenario": case.id})
            record.observation = evaluate(record.result, case.expected)
    except (TheseusError, OSError, ValueError) as exc:
        record.errors.append(f"engine: {type(exc).__name__}: {exc}")
    finally:
        record.errors.extend(llm.errors)
        try:
            scoped.cleanup()
        except GraphError as exc:
            record.errors.append(str(exc))
    reports: dict[str, CheckovReport | ScanFailure] = {}
    for side in ("base", "head"):
        try:
            reports[side] = scan(case.root / side / "terraform")
        except CheckovError as exc:
            reports[side] = exc.failure
            record.errors.append(f"checkov {side}: {exc}")
        except TheseusError as exc:
            reports[side] = ScanFailure(reason=str(exc))
            record.errors.append(f"checkov {side}: {exc}")
    base, head = reports["base"], reports["head"]
    if isinstance(base, CheckovReport) and isinstance(head, CheckovReport):
        record.checkov = compare_reports(base, head)
    else:
        record.incomplete_scans = reports
    if hashes != input_hashes(case.root):
        record.errors.append("case inputs changed during execution; observation is not reproducible")
    record.recordings = {
        path.relative_to(recordings).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(recordings.glob("*/*.json"))
    }
    record.errors = sorted(set(record.errors))
    return record


def _cell(value: object) -> str:
    return str(escape(" ".join(str(value).split())))


def render_report(
    rows: list[tuple[str, Observation | None, CheckovComparison | None, str]],
) -> str:
    """Return a sorted table of observations without inventing risk labels or Checkov relevance."""
    lines = [
        "# Benchmark observations",
        "",
        "Self-authored synthetic cases from one demo world; not a held-out accuracy estimate.",
        "",
        "Counts describe observations. Human keys determine projection correctness. Checkov risk relevance",
        "requires human review; new failed checks alone do not prove the planted risk was caught.",
        "",
        "| Case | Expected paths / code uses | Paths: certain / unknown; code uses | Key match | Verdict |"
        " Checkov: base / head / new | Errors |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    details: list[str] = []
    for identifier, observation, checker, error in sorted(rows, key=lambda row: row[0]):
        expected = "unavailable"
        if observation:
            expected = " / ".join(
                "not compared" if count is None else str(count)
                for count in (observation.expected_paths, observation.expected_code_uses)
            )
        found = (
            f"{observation.certain_paths} / {observation.unknown_paths} / {observation.code_uses}"
            if observation
            else "unavailable"
        )
        match = ("yes" if observation.matches else "NO") if observation else "unscored"
        checks = (
            f"{checker.base.failed} / {checker.head.failed} / {len(checker.introduced)}"
            if checker
            else "unavailable"
        )
        lines.append(
            "| "
            + " | ".join(
                map(
                    _cell,
                    [
                        identifier,
                        expected,
                        found,
                        match,
                        observation.product_verdict if observation else "unavailable",
                        checks,
                        error or "none",
                    ],
                )
            )
            + " |"
        )
        if observation and observation.differences:
            details.extend(["", f"Differences for {_cell(identifier)}:", ""])
            details.extend(f"- {_cell(difference)}" for difference in observation.differences)
    return "\n".join([*lines, *details]) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Return a failing status for missing inputs, tool errors or projection differences."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["generate", "validate", "run", "record"])
    parser.add_argument(
        "--confirm-model-calls",
        action="store_true",
        help="required for record: explicitly allow calls to configured model providers",
    )
    parser.add_argument("--cases", type=Path, default=ROOT / "bench/cases")
    parser.add_argument("--source", type=Path, default=ROOT / "demo-infra")
    parser.add_argument("--recordings", type=Path, default=ROOT / "recordings")
    parser.add_argument("--report", type=Path, default=ROOT / "bench/report.md")
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args(argv)
    specifications = {spec.id: spec for spec in case_specs()}
    selected = sorted(set(args.case) if args.case else specifications)
    try:
        if args.command == "record" and not args.confirm_model_calls:
            raise IngestError("record requires --confirm-model-calls; run/validate never call live models")
        if args.command != "record" and args.confirm_model_calls:
            raise IngestError("--confirm-model-calls is only valid with the record command")
        if set(selected) - specifications.keys():
            raise IngestError("unknown case ID")
        if args.command == "generate":
            bash = resolve_bash()
            for identifier in selected:
                generate_case(specifications[identifier], args.source, args.cases, bash=bash)
            return 0
        cases = [read_case(args.cases / identifier) for identifier in selected]
        if args.command == "validate":
            log.info("Validated %s PR cases; answer keys were not modified", len(cases))
            return 0
        check_version()
        settings = get_settings()
        database = get_client(settings)
        records = []
        # Shared by the runner and scale CLI so deterministic benchmark graph names cannot race.
        with benchmark_lock(database) as check_owner:
            for case in cases:
                record = run_case(
                    case,
                    FalkorStore(database),
                    settings,
                    args.recordings.resolve(),
                    check_owner=check_owner,
                    record_models=args.command == "record",
                )
                records.append(record)
                (case.root / "observed.json").write_text(
                    record.model_dump_json(indent=2) + "\n", encoding="utf-8"
                )
        report = render_report([(r.case, r.observation, r.checkov, "; ".join(r.errors)) for r in records])
        report += f"\nCases run: {len(cases)} of 20. FalkorDB: {server_version(database)}. Checkov: 3.3.29.\n"
        report += f"\nModel mode: {'record' if args.command == 'record' else 'replay'}.\n"
        report += "\nTiming results are generated separately by `python -m bench.scale` on the VM.\n"
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
        return int(any(r.errors or r.observation is None or not r.observation.matches for r in records))
    except (TheseusError, OSError, ValueError) as exc:
        log.error("Benchmark could not complete: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
