from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from theseus.contracts.result import (
    AnalysisResult,
    Candidate,
    CutEdge,
    Evidence,
    Grant,
    Intent,
    MinCut,
    PatchOp,
    PathRecord,
    PathStep,
    RequirementStatus,
    StagingToProd,
    UnusedGrant,
    compare,
    project,
)

ROUTE = [
    "user:priya-intern",
    "group:support-engineers",
    "role:prod-support",
    "secret:prod-db-credentials",
    "db:customer-db",
]


def intern_result() -> AnalysisResult:
    """A hand-built PR-mode result shaped like the intern scenario."""
    steps = [
        PathStep(src=ROUTE[0], edge="MEMBER_OF", dst=ROUTE[1], evidence="E1"),
        PathStep(src=ROUTE[1], edge="CAN_ASSUME", dst=ROUTE[2], evidence="E2"),
        PathStep(src=ROUTE[2], edge="CAN", dst=ROUTE[3], evidence="E3"),
        PathStep(src=ROUTE[3], edge="UNLOCKS", dst=ROUTE[4], evidence="E4"),
    ]
    return AnalysisResult(
        scenario="intern",
        mode="pr",
        repo="owner/theseus",
        pr_number=42,
        graphs={"base": "fx__intern__base", "head": "fx__intern__head"},
        intent=Intent(
            purpose="Let Priya read the app logs.",
            grants=[Grant(principal="user:priya-intern", access="read", resource="s3://demo-app-logs/")],
            suspicious=False,
        ),
        headline="Your PR says logs. Your change grants db:customer-db.",
        opened=[
            PathRecord(
                id="P1",
                actor=ROUTE[0],
                target=ROUTE[4],
                grants=["read", "write"],
                steps=steps,
                unknown=False,
                inferred=True,
                sensitivity="regulated",
            )
        ],
        requirements=[
            RequirementStatus(id="I1", status="satisfied"),
            RequirementStatus(id="R1", status="satisfied"),
        ],
        min_cut=MinCut(
            sources=[ROUTE[0]],
            sinks=[ROUTE[4]],
            value=1_000_000,
            cuttable=False,
            cut=[CutEdge(eid="e2", src=ROUTE[1], type="CAN_ASSUME", dst=ROUTE[2], evidence="E2")],
        ),
        candidates=[
            Candidate(
                id="B",
                source="llm",
                title="A new intern-onboarding role that reads only app-logs",
                ops=[
                    PatchOp(
                        provider="example",
                        op="remove_membership",
                        args={"user": "priya-intern", "group": "support-engineers"},
                    )
                ],
                verdict="pass",
                reason="Every dangerous path closed; every requirement kept.",
                recommended=True,
            ),
            Candidate(id="A", source="rule", title="Revert", verdict="fail", reason="Breaks I1."),
        ],
        rotate=["secret:prod-db-credentials"],
        unused_grants=[
            UnusedGrant(
                workload="workload:billing-api",
                resource="dynamodb:demo-orders",
                access="write",
                eid="e9",
                evidence="E9",
            )
        ],
        staging_to_prod=[
            StagingToProd(actor="workflow:demo-org/docs-site/preview.yml", target=ROUTE[4], path_id="P7")
        ],
        evidence={
            "E1": Evidence(
                address="aws_iam_user_group_membership.priya", file="terraform/people.tf", line=20
            ),
            "E2": Evidence(address="aws_iam_role.prod_support", file="terraform/roles.tf", line=5),
            "E3": Evidence(
                address="aws_iam_role_policy.prod_support_read",
                part="ReadDbSecret",
                file="terraform/roles.tf",
                line=31,
            ),
            "E4": Evidence(
                address="aws_secretsmanager_secret.prod_db", file="unknown", line=None, note="tag"
            ),
            "E9": Evidence(address="aws_iam_role_policy.billing", file="terraform/roles.tf", line=60),
        },
    )


EXPECTED_PROJECTION = {
    "scenario": "intern",
    "mode": "pr",
    "headline": "Your PR says logs. Your change grants db:customer-db.",
    "intent": {
        "purpose": "Let Priya read the app logs.",
        "grants": [["user:priya-intern", "read", "s3://demo-app-logs/"]],
        "suspicious": False,
    },
    "opened": [
        {
            "actor": "user:priya-intern",
            "target": "db:customer-db",
            "route": ROUTE,
            "cites": ["terraform/people.tf:20", "terraform/roles.tf:5", "terraform/roles.tf:31", "unknown"],
        }
    ],
    "closed": [],
    "unchanged": [],
    "requirements": {"I1": "satisfied", "R1": "satisfied"},
    "unknowns": [],
    "min_cut": {
        "value": 1_000_000,
        "cuttable": False,
        "cut": [["group:support-engineers", "CAN_ASSUME", "role:prod-support"]],
    },
    "candidates": {"A": "fail", "B": "pass"},
    "recommended": "B",
    "rotate": ["secret:prod-db-credentials"],
    "unused_grants": [["workload:billing-api", "dynamodb:demo-orders", "write"]],
    "use_beyond_intent": [],
    "staging_to_prod": [["workflow:demo-org/docs-site/preview.yml", "db:customer-db"]],
}


def test_analysis_result_round_trips_through_json() -> None:
    result = intern_result()
    again = AnalysisResult.model_validate_json(result.model_dump_json())
    assert again == result


def test_path_step_serializes_as_from_and_to() -> None:
    step = PathStep(src="user:a", edge="MEMBER_OF", dst="group:b", evidence="E1")
    dumped = json.loads(step.model_dump_json())
    assert dumped == {"from": "user:a", "edge": "MEMBER_OF", "to": "group:b", "evidence": "E1"}
    assert PathStep.model_validate(dumped) == step
    assert step.model_dump()["from"] == "user:a"


def test_route_is_every_node_in_order() -> None:
    assert intern_result().opened[0].route == ROUTE


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Grant(principal="user:a", access="read", resource="s3://b/", extra="no")


def test_a_patch_op_is_an_envelope_any_provider_can_fill() -> None:
    op = PatchOp(provider="example", op="anything", args={"n": 1})
    assert PatchOp.model_validate_json(op.model_dump_json()) == op
    with pytest.raises(ValidationError):
        PatchOp(op="no-provider")


def test_project_matches_the_hand_written_projection() -> None:
    assert project(intern_result()) == EXPECTED_PROJECTION


def test_project_is_json_ready() -> None:
    assert json.loads(json.dumps(project(intern_result()))) == EXPECTED_PROJECTION


def test_compare_finds_nothing_when_they_match() -> None:
    assert compare(project(intern_result()), EXPECTED_PROJECTION) == []


def test_compare_reports_a_changed_verdict() -> None:
    expected = {"candidates": {"B": "fail"}}
    assert compare(project(intern_result()), expected) == ["candidates.B: expected 'fail', got 'pass'"]


def test_compare_ignores_fields_missing_from_expected() -> None:
    expected = {"mode": "pr", "opened": [{"actor": "user:priya-intern", "target": "db:customer-db"}]}
    assert compare(project(intern_result()), expected) == []


def test_compare_limits_itself_to_the_given_keys() -> None:
    expected = {"mode": "finding", "recommended": "B"}
    assert compare(project(intern_result()), expected, keys=["recommended"]) == []


def test_compare_reports_missing_and_extra_paths() -> None:
    expected = {"opened": [{"actor": "user:priya-intern", "target": "s3://demo-company-files/invoices/"}]}
    assert compare(project(intern_result()), expected) == [
        "opened: missing user:priya-intern -> s3://demo-company-files/invoices/",
        "opened: unexpected user:priya-intern -> db:customer-db",
    ]


def test_compare_names_each_unexpected_path() -> None:
    assert compare(project(intern_result()), {"opened": []}) == [
        "opened: unexpected user:priya-intern -> db:customer-db"
    ]


def test_compare_checks_route_order() -> None:
    expected = {"opened": [{"actor": ROUTE[0], "target": ROUTE[4], "route": list(reversed(ROUTE))}]}
    [difference] = compare(project(intern_result()), expected)
    assert difference.startswith("opened[user:priya-intern -> db:customer-db].route: expected")


def test_compare_ignores_order_in_other_lists() -> None:
    projection = project(intern_result())
    expected = {
        "opened": [
            {"actor": ROUTE[0], "target": ROUTE[4], "cites": list(reversed(projection["opened"][0]["cites"]))}
        ]
    }
    assert compare(projection, expected) == []


def test_compare_accepts_a_lower_bound_on_the_cut_value() -> None:
    projection = project(intern_result())
    assert compare(projection, {"min_cut": {"cuttable": False, "value_at_least": 1_000_000}}) == []
    assert compare(projection, {"min_cut": {"value_at_least": 2_000_000}}) == [
        "min_cut.value: expected at least 2000000, got 1000000"
    ]


def test_compare_reports_a_key_the_result_lacks() -> None:
    assert compare({"mode": "pr"}, {"rotate": []}) == ["rotate: missing from the result"]
