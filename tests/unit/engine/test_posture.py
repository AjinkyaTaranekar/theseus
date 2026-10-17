"""The posture of main (O1 to O3): single points of failure, articulation points, reach, unreached data and
the cost summary, on a tiny hand-built graph and on the demo world's main."""

from __future__ import annotations

from pathlib import Path

from tests.golden.conftest import deps_for, world
from theseus.contracts.engine import GraphState, World
from theseus.contracts.posture import CostLine
from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow, Requirement
from theseus.engine.pipeline import actors, config_requirements, prepare_state, run_posture
from theseus.engine.posture import articulation_points, dependencies, posture
from theseus.graph.load import load_graph
from theseus.graph.store import MemoryStore

EV = [Evidence(address="hand_built", part="Sid", file="main.tf", line=3)]


def node(identifier: str, *labels: str, sensitive: bool = False, address: str = "") -> NodeRow:
    return NodeRow(
        id=identifier,
        name=identifier.split(":")[-1],
        labels=["Node", *labels],
        category="Database" if "Resource" in labels else None,
        sensitive=sensitive,
        sensitivity="regulated" if sensitive else "internal",
        props={"address": address} if address else {},
    )


def edge(eid: str, kind: str, src: str, dst: str, *grants: str) -> EdgeRow:
    return EdgeRow(
        eid=eid,
        type=kind,  # type: ignore[arg-type]
        src=src,
        dst=dst,
        kind="configured",
        grants=list(grants),
        evidence=EV,
    )


def state() -> GraphState:
    """Two services run as one shared role, which can read the db and the secret; the db is also readable
    through a second role that only alice can become. Nothing reaches `db:spare`."""
    rows = GraphRows(
        nodes=[
            node("workload:api", "Principal", "Workload"),
            node("workload:job", "Principal", "Workload"),
            node("user:alice", "Principal", "User"),
            node("role:shared", "Principal", "Role"),
            node("role:admin", "Principal", "Role"),
            node("db:main", "Resource", sensitive=True, address="aws_db_instance.main"),
            node("secret:key", "Resource", sensitive=True),
            node("db:spare", "Resource", address="aws_db_instance.spare"),
        ],
        edges=[
            edge("e1", "RUNS_AS", "workload:api", "role:shared"),
            edge("e2", "RUNS_AS", "workload:job", "role:shared"),
            edge("e3", "CAN", "role:shared", "db:main", "read"),
            edge("e4", "CAN", "role:shared", "secret:key", "read"),
            edge("e5", "CAN_ASSUME", "user:alice", "role:admin"),
            edge("e6", "CAN", "role:admin", "db:main", "read", "write"),
            edge("e7", "CALLS", "workload:api", "db:main", "read"),
            edge("e8", "CALLS", "workload:job", "secret:key", "read"),
        ],
    )
    return GraphState(name="posture-test", world=World(root="hand", iac="terraform"), rows=rows)


def run(lines: list[CostLine] | None = None):
    store, s = MemoryStore(), state()
    load_graph(store, s)
    need = [Requirement(id="R1", principal="user:alice", access="write", resource="db:main", source="config")]
    who = ["user:alice", "workload:api", "workload:job"]
    return posture(store, s, need, who, lines or [])


def test_every_code_call_and_config_requirement_is_a_dependency() -> None:
    need = [Requirement(id="R1", principal="user:alice", access="write", resource="db:main", source="config")]
    deps = [(d.principal, d.access, d.resource, d.source) for d in dependencies(state(), need)]
    assert deps == [
        ("user:alice", "write", "db:main", "requirement"),
        ("workload:api", "read", "db:main", "code"),
        ("workload:job", "read", "secret:key", "code"),
    ]


def test_a_shared_role_on_every_route_is_a_single_point_of_failure_for_each_service() -> None:
    found = {s.id: [(b.principal, b.resource) for b in s.breaks] for s in run().single_points}
    assert found["role:shared"] == [("workload:api", "db:main"), ("workload:job", "secret:key")]
    assert found["role:admin"] == [("user:alice", "db:main")]
    assert list(found)[0] == "role:shared"  # the most actors depend on it


def test_the_shared_role_splits_the_access_graph() -> None:
    s = state()
    points = {a.id: (a.cut_off, a.pieces) for a in articulation_points(s.rows.nodes, s.rows.edges)}
    # Without role:shared, job and the secret it calls are cut off; api stays joined to the db by its call.
    assert points["role:shared"] == (2, [4, 2])
    assert "db:spare" not in points


def test_reach_is_each_actor_s_blast_radius_and_names_what_a_requirement_asks_for() -> None:
    reach = {r.actor: r for r in run().reach}
    assert reach["workload:job"].targets == ["db:main", "secret:key"]
    assert reach["user:alice"].targets == ["db:main"] and reach["user:alice"].required == ["db:main"]
    assert reach["workload:api"].worst == "regulated"


def test_data_nobody_reaches_or_calls_is_a_saving_at_its_own_price() -> None:
    lines = [
        CostLine(address="aws_db_instance.spare", type="t", monthly_usd=12.5, basis="b"),
        CostLine(address="aws_db_instance.main", type="t", monthly_usd=30.0, basis="b"),
    ]
    found = run(lines)
    assert found.unreached == ["db:spare"]
    assert found.cost.monthly_usd == 42.5 and found.cost.savings_usd == 12.5
    assert [s.id for s in found.cost.savings] == ["db:spare"]
    assert [line.address for line in found.cost.lines] == ["aws_db_instance.main", "aws_db_instance.spare"]


def test_every_named_node_has_its_plain_name_info() -> None:
    found = run()
    assert {"role:shared", "db:main", "secret:key", "db:spare", "user:alice"} <= set(found.nodes)


def test_the_demo_world_s_main_has_the_db_secret_as_a_single_point_of_failure() -> None:
    deps = deps_for("unused-grant")
    w = world("unused-grant", "base")
    s, _ = prepare_state(w, "main", deps)
    load_graph(deps.store, s)
    found = posture(
        deps.store, s, config_requirements(w), actors(s), deps.adapters.cloud.monthly_cost(w.resources)
    )
    points = {p.id: {b.principal for b in p.breaks} for p in found.single_points}
    assert {"user:sam-support", "workload:billing-api"} <= points["secret:prod-db-credentials"]
    assert found.articulation[0].id == "role:prod-support"
    assert found.single_points[0].id == "secret:prod-db-credentials"  # three actors need it
    assert found.reach[0].worst == "regulated"
    assert found.cost.monthly_usd == round(sum(line.monthly_usd for line in found.cost.lines), 2) > 0


def test_a_posture_run_raises_a_finding_for_an_advisory_that_affects_main() -> None:
    import json

    deps = deps_for("unused-grant")
    advisory = json.loads(Path("advisories/GHSA-demo-0001.json").read_text(encoding="utf-8"))
    other = {"id": "GHSA-none", "action": "nobody/uses-this", "affected_versions": ["v1"], "text": "x"}
    report = run_posture(world("unused-grant", "base"), deps, [advisory, other])
    assert [(f.finding or {})["id"] for f in report.findings] == ["GHSA-demo-0001"]
    assert report.scan.mode == "scan" and report.scan.choke_points
    assert report.posture.single_points


def test_a_saving_carries_the_proof_that_nothing_uses_it() -> None:
    """The demo world's left-over replica: every actor's paths traced, every code file read; none reach it."""
    deps = deps_for("unused-grant")
    report = run_posture(world("unused-grant", "base"), deps, [])
    (saving,) = report.posture.cost.savings
    assert saving.id == "db:reports-replica" and saving.monthly_usd > 0
    proof = saving.proof
    assert proof is not None
    assert (proof.file, proof.line) == ("terraform/legacy.tf", 224)
    assert proof.actors > 10 and proof.paths > proof.actors and proof.code_files > 0
    assert proof.checks[0].startswith(f"No valid path from any of the {proof.actors} people")
    assert proof.checks[1].startswith(f"No code calls it: {proof.code_files} code files read")
    assert proof.inbound == [] and len(proof.blind_spots) == 3
    line = next(x for x in report.posture.cost.lines if x.address == "aws_db_instance.reports_replica")
    assert line.pricing_url and line.idle_check and line.retire
