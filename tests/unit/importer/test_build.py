"""Graph composition through adapter protocols, including the real F4/E2 handoff."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from theseus.adapters.aws.adapter import AwsAdapter
from theseus.adapters.github.adapter import GithubAdapter
from theseus.adapters.python.adapter import PythonAdapter
from theseus.adapters.terraform.adapter import TerraformAdapter
from theseus.agent.jev import JevAnswer
from theseus.contracts.adapters import Adapters, CiIdentity, CiRead, CodeRead
from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow, Sensitivity
from theseus.errors import IngestError
from theseus.importer.build import build_rows
from theseus.importer.world import load_world

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = "workflow:demo-org/infra/deploy.yml"


class SuppliedCi:
    """A test CI reader; production workflow facts remain FM1's responsibility."""

    name = "test-ci"

    def read(self, files: dict[str, str]) -> CiRead:
        return CiRead(
            rows=GraphRows(
                nodes=[NodeRow(id=WORKFLOW, name="deploy.yml", labels=["Node", "Principal", "Workflow"])]
            ),
            identities=[CiIdentity(workflow=WORKFLOW, issuer="https://ci.example", subjects=["main"])],
        )


def fixture(side: str, scenario: str = "intern", ci: Any = None) -> tuple[Any, Adapters]:
    root = ROOT / "fixtures" / scenario / side
    config = yaml.safe_load((root / "theseus.yaml").read_text())
    adapters = Adapters(
        iac=TerraformAdapter(), cloud=AwsAdapter(config), ci=ci or SuppliedCi(), code=PythonAdapter()
    )
    world = load_world(root, json.loads((root.parent / f"{side}.plan.json").read_text()), adapters)
    return world, adapters


def test_real_fixture_counts_and_only_new_membership() -> None:
    worlds = [fixture(side) for side in ["base", "head"]]
    base, head = [build_rows(world, {}, adapters) for world, adapters in worlds]
    for label, count in [
        ("User", 4),
        ("Group", 3),
        ("Role", 11),
        ("Workload", 6),
        ("Resource", 10),
        ("Requirement", 17),
    ]:
        assert sum(label in n.labels for n in base.nodes) == count
    before = {(e.type, e.src, e.dst) for e in base.edges}
    after = {(e.type, e.src, e.dst) for e in head.edges}
    assert after - before == {("MEMBER_OF", "user:priya-intern", "group:support-engineers")}
    assert not before - after
    edge = next(e for e in head.edges if e.type == "MEMBER_OF" and e.src == "user:priya-intern")
    assert [(ev.file, ev.line) for ev in edge.evidence] == [("terraform/people.tf", 77)]
    assert all(
        e.evidence
        and all(
            (ev.file == "unknown" and ev.line is None and ev.note)
            or (ev.file != "unknown" and ev.line and ev.line > 0)
            for ev in e.evidence
        )
        for e in head.edges
    )
    nodes = {n.id for n in head.nodes}
    assert all(e.src in nodes and e.dst in nodes for e in head.edges)
    assert len([e for e in head.edges if e.type == "FOR"]) == 17
    assert len([e for e in head.edges if e.type == "NEEDS"]) == 17
    for e in head.edges:
        if e.type in {"FOR", "NEEDS"}:
            ev = e.evidence[0]
            assert ev.file == "theseus.yaml" and ev.line
            assert (
                e.src.split(":", 1)[1]
                in (Path(worlds[1][0].root) / ev.file).read_text().splitlines()[ev.line - 1]
            )


@pytest.mark.parametrize(
    "scenario,side",
    [
        ("intern", "base"),
        ("intern", "head"),
        ("public-bucket", "base"),
        ("public-bucket", "head"),
        ("compromised-action", "base"),
        ("unused-grant", "base"),
    ],
)
def test_all_six_fixture_sides_are_deterministic_and_unmodified(scenario: str, side: str) -> None:
    world, adapters = fixture(side, scenario)
    original = deepcopy(world)
    first = build_rows(world, {}, adapters)
    shuffled = world.model_copy(
        update={
            "resources": list(reversed(world.resources)),
            "config": {**world.config, "requirements": list(reversed(world.config["requirements"]))},
        }
    )
    changed = build_rows(shuffled, {}, adapters)
    assert all(
        ev.file == "unknown" and ev.note
        for e in changed.edges
        if e.type in {"FOR", "NEEDS"}
        for ev in e.evidence
    )
    # YAML citations deliberately become unknown when a caller changes the configuration in memory.
    second = build_rows(world.model_copy(update={"resources": shuffled.resources}), {}, adapters)
    assert first == second and world == original
    assert [n.id for n in first.nodes] == sorted(n.id for n in first.nodes)
    assert [e.eid for e in first.edges] == [f"e{i}" for i in range(1, len(first.edges) + 1)]
    assert len({(e.src, e.type, e.dst) for e in first.edges}) == len(first.edges)
    runs = {e.src: e.dst for e in first.edges if e.type == "RUNS_AS"}
    assert runs["workload:orders-api"] == "role:orders-api-task"
    assert runs["workload:orders-worker"] == "role:orders-worker-task"


def test_sensitivity_human_override_and_environment() -> None:
    world, adapters = fixture("base")
    target = "s3://demo-data-lake/raw/"
    world.config["environments"]["staging"].append("workload:orders-api")
    world.config["environments"]["staging"].append("req:R1")
    rows = build_rows(world, {target: "public", "secret:payments-api-key": "confidential"}, adapters)
    nodes = {n.id: n for n in rows.nodes}
    assert nodes[target].sensitivity == "regulated" and nodes[target].sensitive
    assert nodes[target].sensitivity_source == "human"
    assert nodes["secret:payments-api-key"].sensitivity_source == "jev"
    assert nodes["secret:payments-api-key"].sensitive
    assert nodes["s3://demo-company-files/public/"].sensitivity_source == "unclassified"
    assert nodes["workload:orders-api"].env == "staging"
    assert nodes["workload:orders-worker"].env == "prod"
    assert nodes["req:R1"].env == "staging"


def test_invalid_sensitivity_is_not_a_fact() -> None:
    world, adapters = fixture("base")
    with pytest.raises(IngestError):
        build_rows(world, {"secret:payments-api-key": "top-secret"}, adapters)


@pytest.mark.parametrize("label", ["public", "internal", "confidential", "regulated"])
@pytest.mark.parametrize("source", ["jev", "fallback"])
@pytest.mark.parametrize("override", [None, "public", "internal", "confidential", "regulated"])
def test_typed_sensitivity_keeps_source_and_human_precedence(
    label: Sensitivity, source: str, override: Sensitivity | None
) -> None:
    world, adapters = fixture("base")
    target = "secret:payments-api-key"
    if override is not None:
        world.config["sensitive_overrides"][target] = override
    answers = {target: JevAnswer(type="choice", choice=label, source=source, calibrated=source == "jev")}
    original_world = world.model_copy(deep=True)
    original_answer = answers[target].model_copy(deep=True)

    rows = build_rows(world, {}, adapters, answers=answers)

    node = next(n for n in rows.nodes if n.id == target)
    expected = override or label
    assert node.sensitivity == expected
    assert node.sensitive is (expected in {"confidential", "regulated"})
    assert node.sensitivity_source == ("human" if override else source)
    assert world == original_world and answers[target] == original_answer


def test_typed_sensitivity_does_not_accept_a_flattened_label_too() -> None:
    world, adapters = fixture("base")
    target = "secret:payments-api-key"
    answer = JevAnswer(type="choice", choice="regulated", source="fallback", calibrated=False)
    with pytest.raises(IngestError, match="labels or answers"):
        build_rows(world, {target: "public"}, adapters, answers={target: answer})


@pytest.mark.parametrize(
    "answer",
    [
        "regulated",
        JevAnswer(type="choice", choice="top-secret"),
        JevAnswer(type="noul", noul=0.9),
    ],
)
def test_invalid_typed_sensitivity_is_not_a_fact(answer: Any) -> None:
    world, adapters = fixture("base")
    with pytest.raises(IngestError, match="sensitivity answers"):
        build_rows(world, {}, adapters, answers={"secret:payments-api-key": answer})


def test_injected_adapters_receive_identity_and_code_inputs() -> None:
    world, original = fixture("base")
    seen: list[str] = []

    class Cloud:
        name = "test"
        modeled_types = original.cloud.modeled_types
        resource_kinds = original.cloud.resource_kinds

        def rows(self, resources: Any, identities: Any, locate: Any) -> GraphRows:
            assert identities[0].workflow == WORKFLOW
            seen.append("cloud")
            return original.cloud.rows(resources, identities, locate)

    class Code:
        name = "test"

        def read(self, files: Any, rows: GraphRows, resources: Any) -> CodeRead:
            assert any(n.id == WORKFLOW for n in rows.nodes)
            assert files == world.code_files and resources == world.resources
            seen.append("code")
            return CodeRead(unknowns=["synthetic unresolved call"])

    adapters = Adapters(iac=original.iac, cloud=Cloud(), ci=original.ci, code=Code())
    result = build_rows(world, {}, adapters)
    assert seen == ["cloud", "code"] and "synthetic unresolved call" in result.unknowns


def test_duplicate_edge_merges_evidence_grants_and_unknown() -> None:
    world, original = fixture("base")

    class Code:
        name = "test"

        def read(self, files: Any, rows: GraphRows, resources: Any) -> CodeRead:
            ev = Evidence(address="services/test.py", file="services/test.py", line=1)
            return CodeRead(
                edges=[
                    EdgeRow(
                        eid="old",
                        type="CAN",
                        src="role:prod-support",
                        dst="secret:prod-db-credentials",
                        kind="unknown",
                        grants=["write"],
                        evidence=[ev],
                    )
                ]
            )

    adapters = Adapters(iac=original.iac, cloud=original.cloud, ci=original.ci, code=Code())
    result = build_rows(world, {}, adapters)
    edges = [
        e
        for e in result.edges
        if e.type == "CAN" and e.src == "role:prod-support" and e.dst == "secret:prod-db-credentials"
    ]
    assert len(edges) == 1 and edges[0].kind == "unknown" and edges[0].grants == ["read", "write"]
    assert {ev.file for ev in edges[0].evidence} == {"terraform/roles.tf", "services/test.py"}


def test_empty_ci_world_without_requirements_still_builds() -> None:
    world, adapters = fixture("base", ci=GithubAdapter())
    world.config["requirements"] = []
    assert build_rows(world, {}, adapters).nodes


@pytest.mark.parametrize(
    "scenario,side",
    [
        ("intern", "base"),
        ("intern", "head"),
        ("public-bucket", "base"),
        ("public-bucket", "head"),
        ("compromised-action", "base"),
        ("unused-grant", "base"),
    ],
)
def test_real_empty_ci_keeps_requirements_and_reports_missing_workflow(scenario: str, side: str) -> None:
    world, adapters = fixture(side, scenario, ci=GithubAdapter())
    rows = build_rows(world, {}, adapters)
    nodes = {node.id for node in rows.nodes}
    assert sum("Requirement" in node.labels for node in rows.nodes) == 17
    assert len([edge for edge in rows.edges if edge.type == "FOR"]) == 14
    assert len([edge for edge in rows.edges if edge.type == "NEEDS"]) == 17
    assert WORKFLOW not in nodes
    assert all(edge.src in nodes and edge.dst in nodes for edge in rows.edges)
    assert {
        message
        for message in rows.unknowns
        if message.startswith("requirement ") and "missing FOR endpoint" in message
    } == {f"requirement {identifier}: missing FOR endpoint {WORKFLOW}" for identifier in ("R4", "R5", "R17")}


def test_missing_non_workflow_requirement_endpoints_are_errors() -> None:
    world, adapters = fixture("base", ci=GithubAdapter())
    requirement = next(item for item in world.config["requirements"] if item["id"] == "R1")
    requirement["principal"] = "role:missing"
    with pytest.raises(IngestError, match="missing endpoint role:missing"):
        build_rows(world, {}, adapters)
    requirement["principal"] = "role:prod-support"
    requirement["resource"] = "secret:missing"
    with pytest.raises(IngestError, match="missing endpoint secret:missing"):
        build_rows(world, {}, adapters)


def test_adapter_with_no_files_is_not_called() -> None:
    world, original = fixture("base")
    world.ci_files = {}
    world.code_files = {}
    world.config["requirements"] = []

    class EmptyCi:
        name = "empty"

        def read(self, files: Any) -> CiRead:
            raise AssertionError("CI adapter with no files was called")

    class EmptyCode:
        name = "empty"

        def read(self, files: Any, rows: Any, resources: Any) -> CodeRead:
            raise AssertionError("Code adapter with no files was called")

    adapters = Adapters(iac=original.iac, cloud=original.cloud, ci=EmptyCi(), code=EmptyCode())
    assert build_rows(world, {}, adapters).nodes


def test_unknown_policy_survives_the_whole_import_boundary() -> None:
    world, adapters = fixture("base")
    plan = json.loads((ROOT / "fixtures/intern/base.plan.json").read_text())
    address = "aws_iam_role_policy.prod_support_read"
    change = next(c for c in plan["resource_changes"] if c["address"] == address)
    change["change"]["after_unknown"]["policy"] = True
    unknown_world = load_world(Path(world.root), plan, adapters)
    rows = build_rows(unknown_world, {}, adapters)
    assert any(u.address == address and u.field == "policy" for u in unknown_world.unknown_fields)
    edge = next(
        e
        for e in rows.edges
        if e.type == "CAN" and e.src == "role:prod-support" and e.dst == "secret:prod-db-credentials"
    )
    assert edge.kind == "unknown" and edge.evidence
    assert any(address in message and "unknown until apply" in message for message in rows.unknowns)


@pytest.mark.parametrize(
    "config",
    [
        {"sensitive_overrides": {1: "public"}},
        {"environments": {"staging": [None]}},
        {"environments": {"staging": [False]}},
    ],
)
def test_malformed_config_fields_fail_with_typed_error(config: dict[str, Any]) -> None:
    world, adapters = fixture("base")
    world.config.update(config)
    with pytest.raises(IngestError):
        build_rows(world, {}, adapters)


def test_override_for_a_principal_is_reported_as_naming_no_resource(caplog: pytest.LogCaptureFixture) -> None:
    world, adapters = fixture("base")
    world.config["sensitive_overrides"]["user:priya-intern"] = "regulated"
    rows = build_rows(world, {}, adapters)
    node = next(n for n in rows.nodes if n.id == "user:priya-intern")
    assert node.sensitivity is None and not node.sensitive
    assert "user:priya-intern" in caplog.text
