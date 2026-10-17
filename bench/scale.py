"""Five-sample VM measurements over reproducible worlds with exact non-FLOW edge counts."""

from __future__ import annotations

import argparse
import json
import logging
import platform
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from pydantic import Field

from bench.run import OwnedStore, benchmark_lock, code_provenance
from theseus.cli import adapters_for
from theseus.config import get_settings
from theseus.contracts.adapters import IacResource
from theseus.contracts.engine import CandidateDraft, FlowResult, GraphDelta, GraphState, GraphStore, World
from theseus.contracts.result import Candidate, Contract, NodeRow, PatchOp, Requirement
from theseus.engine.analyze import analyze
from theseus.engine.mincut import capacities
from theseus.engine.simulate import candidate_graph, simulate
from theseus.errors import GraphError, IngestError, TheseusError
from theseus.graph.client import get_client, server_version
from theseus.graph.load import load_graph
from theseus.graph.store import FalkorStore
from theseus.importer.build import build_rows

log = logging.getLogger(__name__)


class Measurement(Contract):
    samples_ns: list[int]
    median_ms: float


class ScaleResult(Contract):
    edges: int
    nodes: int
    actors: int = 1
    sinks: int
    routes: int
    path_depth: int = 2
    flow_pairs: int
    measurements: dict[str, Measurement] = Field(default_factory=dict)


def measure[T](
    operation: Callable[[], T],
    validate: Callable[[T], None],
    *,
    prepare: Callable[[], None] = lambda: None,
    clock: Callable[[], int] = time.perf_counter_ns,
) -> Measurement:
    """Return five samples and their median, after one validated warmup."""
    samples = []
    for iteration in range(6):
        prepare()
        start = clock()
        result = operation()
        elapsed = clock() - start
        if elapsed < 0:
            raise IngestError("measurement clock moved backwards")
        validate(result)
        if iteration:
            samples.append(elapsed)
    return Measurement(samples_ns=samples, median_ms=statistics.median(samples) / 1_000_000)


def build_world(root: Path, edge_count: int) -> tuple[GraphState, CandidateDraft, list[Requirement]]:
    """Return a sourced fan-out world, a narrowing fix and a preserved public-data requirement."""
    if edge_count < 6:
        raise IngestError("synthetic world needs at least six edges")
    prefixes = ["public/", *(f"private-{index:05d}/" for index in range(edge_count - 4))]
    locations = [
        {"id": f"s3://s2-scale-data/{prefix}", "bucket": "s2-scale-data", "prefix": prefix}
        for prefix in prefixes
    ]
    config = {
        "account": "111122223333",
        "region": "eu-west-1",
        "data_locations": locations,
        "sensitive_overrides": {
            location["id"]: "internal" if index == 0 else "confidential"
            for index, location in enumerate(locations)
        },
        "requirements": [
            {
                "id": "R1",
                "principal": "user:scale-reader",
                "access": "read",
                "resource": "s3://s2-scale-data/public/",
            }
        ],
    }
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "TrustAccount",
                "Effect": "Allow",
                "Action": "sts:AssumeRole",
                "Principal": {"AWS": "arn:aws:iam::111122223333:root"},
            }
        ],
    }
    assume = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AssumeScale",
                "Effect": "Allow",
                "Action": "sts:AssumeRole",
                "Resource": "arn:aws:iam::111122223333:role/scale-read",
            }
        ],
    }
    grants = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadLocations",
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": "arn:aws:s3:::s2-scale-data/*",
            }
        ],
    }
    resources = [
        IacResource(
            address="aws_s3_bucket.scale",
            type="aws_s3_bucket",
            name="scale",
            provider="aws",
            values={"bucket": "s2-scale-data"},
        ),
        IacResource(
            address="aws_iam_user.reader",
            type="aws_iam_user",
            name="reader",
            provider="aws",
            values={"name": "scale-reader"},
        ),
        IacResource(
            address="aws_iam_role.reader",
            type="aws_iam_role",
            name="reader",
            provider="aws",
            values={"name": "scale-read", "assume_role_policy": json.dumps(trust, sort_keys=True)},
        ),
        IacResource(
            address="aws_iam_user_policy.assume",
            type="aws_iam_user_policy",
            name="assume",
            provider="aws",
            values={
                "name": "scale-assume",
                "user": "scale-reader",
                "policy": json.dumps(assume, sort_keys=True),
            },
        ),
        IacResource(
            address="aws_iam_role_policy.read",
            type="aws_iam_role_policy",
            name="read",
            provider="aws",
            values={"name": "scale-read", "role": "scale-read", "policy": json.dumps(grants, sort_keys=True)},
        ),
    ]
    resources.sort(key=lambda resource: resource.address)
    source = (
        "\n\n".join(
            f'resource "{resource.type}" "{resource.name}" {{\n'
            + "\n".join(f"  {key} = {json.dumps(value)}" for key, value in sorted(resource.values.items()))
            + "\n}"
            for resource in resources
        )
        + "\n"
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / "terraform").mkdir(exist_ok=True)
    (root / "terraform/scale.tf").write_text(source, encoding="utf-8")
    (root / "theseus.yaml").write_text(yaml.safe_dump(config, sort_keys=True), encoding="utf-8")
    world = World(
        root=str(root),
        iac="terraform",
        resources=resources,
        iac_files={"terraform/scale.tf": source},
        config=config,
    )
    rows = build_rows(world, {}, adapters_for(root))
    if len(rows.edges) != edge_count or rows.unknowns:
        raise IngestError(f"synthetic graph validation failed: {len(rows.edges)} edges; {rows.unknowns}")
    state = GraphState(name=f"s2-scale-{edge_count}__head", world=world, rows=rows)
    draft = CandidateDraft(
        id="S",
        source="rule",
        proposed_by="theseus",
        title="Keep public reads only",
        ops=[
            PatchOp(
                provider="aws",
                op="set_statement_resources",
                args={
                    "policy_address": "aws_iam_role_policy.read",
                    "sid": "ReadLocations",
                    "resources": ["arn:aws:s3:::s2-scale-data/public/*"],
                },
            ),
        ],
    )
    requirements = [Requirement(**raw, source="config") for raw in config["requirements"]]
    return state, draft, requirements


def run_scale(
    backing: GraphStore, root: Path, edges: int, *, check_owner: Callable[[], None] = lambda: None
) -> ScaleResult:
    """Return validated timings for paths, copy, database max flow and a real simulation."""
    state, draft, requirements = build_world(root, edges)
    adapters = adapters_for(root)
    scoped = OwnedStore(backing, f"s2-scale-{edges}__", check_owner)
    source = ["user:scale-reader"]
    try:
        load_graph(scoped, state)
        original = scoped.view(state.name)
        analysis = analyze(scoped, state, requirements, source)
        if len(analysis.dangerous) != edges - 4 or any(
            r.status != "satisfied" for r in analysis.requirements
        ):
            raise GraphError("synthetic analysis disagrees with its construction")
        caps = capacities(state.rows, analysis, requirements)
        sinks = sorted({path.target for path in analysis.dangerous})
        assumed = next(edge for edge in state.rows.edges if edge.type == "CAN_ASSUME")
        expected_routes = sorted([assumed.eid, edge.eid] for edge in state.rows.edges if edge.type == "CAN")
        result = ScaleResult(
            edges=edges,
            nodes=len(state.rows.nodes),
            sinks=len(sinks),
            routes=len(expected_routes),
            flow_pairs=len(caps),
        )

        def unchanged() -> None:
            if scoped.view(state.name) != original:
                raise GraphError("benchmark mutated its source graph")

        def paths_valid(routes: list[list[str]]) -> None:
            if sorted(routes) != expected_routes:
                raise GraphError("path query returned incorrect routes")
            unchanged()

        copy_name = f"s2-scale-{edges}__copy"

        def copy_setup() -> None:
            load_graph(scoped, state)
            scoped._reserve(copy_name)

        def copy_valid(_: None) -> None:
            if scoped.view(copy_name) != original:
                raise GraphError("GRAPH.COPY changed the rows")
            scoped.apply_delta(
                copy_name,
                GraphDelta(
                    add_nodes=[
                        NodeRow(
                            id="user:copy-probe", name="copy-probe", labels=["Node", "User", "Principal"]
                        ),
                    ]
                ),
            )
            unchanged()
            scoped.delete(copy_name)

        def flow_valid(flow: FlowResult) -> None:
            capacities_by_eids = {tuple(row.eids): row for row in caps}
            balances: dict[str, float] = {}
            seen = set()
            for edge in flow.flows:
                identity = tuple(edge.eids)
                row = capacities_by_eids.get(identity)
                if row is None or identity in seen or not 0 <= edge.flow <= row.capacity:
                    raise GraphError("database returned infeasible edge flow")
                seen.add(identity)
                balances[row.src] = balances.get(row.src, 0) - edge.flow
                balances[row.dst] = balances.get(row.dst, 0) + edge.flow
            if flow.value != len(sinks) or balances.get(source[0], 0) != -flow.value:
                raise GraphError("database returned incorrect max flow")
            if sum(balances.get(sink, 0) for sink in sinks) != flow.value:
                raise GraphError("database flow does not reach its sinks")
            if any(value != 0 for node, value in balances.items() if node not in {*source, *sinks}):
                raise GraphError("database flow violates conservation")
            unchanged()

        def simulation_valid(candidate: Candidate) -> None:
            if candidate.verdict != "pass":
                raise GraphError(f"synthetic fix did not pass: {candidate.verdict}")
            unchanged()
            scoped.delete(candidate_graph(state.name, draft.id))

        def setup() -> None:
            load_graph(scoped, state)

        result.measurements["paths"] = measure(
            lambda: scoped.paths(state.name, source[0]), paths_valid, prepare=setup
        )
        result.measurements["copy"] = measure(
            lambda: backing.copy(state.name, copy_name), copy_valid, prepare=copy_setup
        )
        # Deliberately call the store, not algos.max_flow: a database failure cannot become a Python timing.
        result.measurements["max_flow_with_setup"] = measure(
            lambda: scoped.max_flow(state.name, source, sinks, caps), flow_valid, prepare=setup
        )
        result.measurements["simulation"] = measure(
            lambda: simulate(scoped, state, draft, source, requirements, adapters),
            simulation_valid,
            prepare=setup,
        )
        return result
    finally:
        scoped.cleanup()


def render_timings(results: list[ScaleResult], provenance: dict[str, str]) -> str:
    """Return medians, raw samples and the measurement environment as Markdown."""
    lines = [
        "# Scaling measurements",
        "",
        "Measured from the VM client to the configured FalkorDB instance.",
        "One warmup, five measured samples; sparse fan-out, two-edge paths, one actor reaches all locations.",
        "Not a claim about dense graphs or total review time. Max flow includes FLOW setup.",
        "",
        "| Edges | Nodes | Routes | Sinks | Operation | Median ms | Samples ns |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in sorted(results, key=lambda item: item.edges):
        for operation, timing in sorted(result.measurements.items()):
            lines.append(
                f"| {result.edges} | {result.nodes} | {result.routes} | {result.sinks} | {operation} | "
                f"{timing.median_ms:.6f} | {', '.join(map(str, timing.samples_ns))} |"
            )
    lines.extend(["", "Environment:", ""])
    lines.extend(f"- {key}: {value}" for key, value in sorted(provenance.items()))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Return the status after explicit VM-only measurements, without modifying product graphs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vm", action="store_true", required=True, help="attest execution is on the measurement VM"
    )
    parser.add_argument(
        "--environment",
        required=True,
        help="CPU/RAM, DB placement, transport and thread settings; no secrets",
    )
    parser.add_argument("--output", type=Path, default=Path("bench/scale-results.json"))
    parser.add_argument("--report", type=Path, default=Path("bench/report.md"))
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
        database = get_client(settings)
        provenance = {
            "environment": args.environment,
            "python": platform.python_version(),
            "os": platform.system(),
            "falkordb": server_version(database),
            "tls": str(settings.falkordb_tls),
        }
        provenance.update(code_provenance())
        with benchmark_lock(database) as check_owner:
            with TemporaryDirectory(prefix="theseus-scale-") as directory:
                results = [
                    run_scale(
                        FalkorStore(database), Path(directory) / str(size), size, check_owner=check_owner
                    )
                    for size in (1000, 10000)
                ]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {"provenance": provenance, "results": [result.model_dump() for result in results]},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        previous = args.report.read_text(encoding="utf-8") if args.report.exists() else ""
        comparison = previous.partition("\n<!-- S2 scaling -->")[0].rstrip()
        args.report.write_text(
            comparison + "\n\n<!-- S2 scaling -->\n" + render_timings(results, provenance), encoding="utf-8"
        )
        return 0
    except (TheseusError, OSError, ValueError) as exc:
        log.error("Scale measurements could not complete: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
