"""GitHub OIDC trust: which workflows may assume which roles (04-engine.md section 6, "OIDC matching")."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from theseus.adapters.aws.adapter import AwsAdapter
from theseus.adapters.aws.iam import statements
from theseus.adapters.aws.oidc import oidc_allows, oidc_statements
from theseus.adapters.github.adapter import GithubAdapter
from theseus.adapters.python.adapter import PythonAdapter
from theseus.adapters.terraform.adapter import TerraformAdapter
from theseus.contracts.adapters import Adapters
from theseus.importer.build import build_rows
from theseus.importer.world import load_world

ROOT = Path(__file__).resolve().parents[4]
PROVIDER = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
PREVIEW_SUB = "repo:demo-org/docs-site:pull_request"
APPLY_SUB = "repo:demo-org/infra:environment:production"


def trust(condition: dict[str, Any] | None, effect: str = "Allow") -> dict[str, Any]:
    statement: dict[str, Any] = {
        "Sid": "GitHubActionsOIDC",
        "Effect": effect,
        "Principal": {"Federated": PROVIDER},
        "Action": "sts:AssumeRoleWithWebIdentity",
    }
    if condition is not None:
        statement["Condition"] = condition
    return {"Version": "2012-10-17", "Statement": [statement]}


AUD = {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"}
LOOSE = trust(
    {"StringEquals": AUD, "StringLike": {"token.actions.githubusercontent.com:sub": "repo:demo-org/*"}}
)
PINNED = trust({"StringEquals": {**AUD, "token.actions.githubusercontent.com:sub": APPLY_SUB}})


def only(policy: dict[str, Any]) -> Any:
    (s,) = oidc_statements(statements(policy))
    return s


@pytest.mark.parametrize(
    "policy,sub,expected",
    [
        (LOOSE, PREVIEW_SUB, "yes"),  # github-deploy's loose sub accepts the docs-site PR token
        (PINNED, PREVIEW_SUB, "no"),  # terraform-apply's pinned sub refuses it
        (PINNED, APPLY_SUB, "yes"),  # and accepts deploy's apply job
        (trust({"StringEquals": AUD}), PREVIEW_SUB, "yes-any-repo"),  # no sub test at all
        (trust(None), PREVIEW_SUB, "yes-any-repo"),
        (trust({"StringEquals": {"token.actions.githubusercontent.com:aud": "other"}}), PREVIEW_SUB, "no"),
        (
            trust(
                {"StringLike": {"token.actions.githubusercontent.com:sub": ["repo:x/*", "repo:demo-org/*"]}}
            ),
            PREVIEW_SUB,
            "yes",
        ),
        # Anything outside the two keys and two operators is unknown, never a guess.
        (
            trust(
                {"StringEquals": {**AUD, "token.actions.githubusercontent.com:repository_owner": "demo-org"}}
            ),
            PREVIEW_SUB,
            "unknown",
        ),
        (
            trust({"ForAnyValue:StringLike": {"token.actions.githubusercontent.com:sub": "repo:demo-org/*"}}),
            PREVIEW_SUB,
            "unknown",
        ),
        (trust({"StringEquals": AUD, "IpAddress": {"aws:SourceIp": "10.0.0.0/8"}}), PREVIEW_SUB, "unknown"),
    ],
)
def test_a_sub_is_matched_against_the_trust_condition(
    policy: dict[str, Any], sub: str, expected: str
) -> None:
    assert oidc_allows(only(policy), sub, "sts.amazonaws.com") == expected


def test_condition_keys_match_without_case_as_iam_does() -> None:
    policy = trust({"StringEquals": {"Token.Actions.GitHubUserContent.com:Sub": APPLY_SUB}})
    assert oidc_allows(only(policy), APPLY_SUB, "sts.amazonaws.com") == "yes"


def test_only_web_identity_statements_from_github_are_oidc_trust() -> None:
    policy = {
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": "arn:aws:iam::111122223333:root"},
                "Action": "sts:AssumeRole",
            },
            {
                "Effect": "Allow",
                "Principal": {"Federated": "arn:aws:iam::1:oidc-provider/gitlab.com"},
                "Action": "sts:AssumeRoleWithWebIdentity",
            },
            *LOOSE["Statement"],
        ]
    }
    assert [s.sid for s in oidc_statements(statements(policy))] == ["GitHubActionsOIDC"]


# On the real fixture ---------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rows() -> Any:
    root = ROOT / "fixtures/intern/base"
    config = yaml.safe_load((root / "theseus.yaml").read_text(encoding="utf-8"))
    adapters = Adapters(
        iac=TerraformAdapter(), cloud=AwsAdapter(config), ci=GithubAdapter(), code=PythonAdapter()
    )
    world = load_world(
        root, json.loads((root.parent / "base.plan.json").read_text(encoding="utf-8")), adapters
    )
    return build_rows(world, {}, adapters)


def test_trusts_edges_exist_exactly_for_the_three_pairs_spec_02_names(rows: Any) -> None:
    trusts = sorted((e.src, e.dst, e.kind) for e in rows.edges if e.type == "TRUSTS")
    assert trusts == [
        ("workflow:demo-org/docs-site/preview.yml", "role:github-deploy", "configured"),
        ("workflow:demo-org/infra/deploy.yml", "role:github-deploy", "configured"),
        ("workflow:demo-org/infra/deploy.yml", "role:terraform-apply", "configured"),
    ]


def test_each_trusts_edge_cites_the_role_s_trust_statement(rows: Any) -> None:
    ci = (ROOT / "fixtures/intern/base/terraform/ci.tf").read_text(encoding="utf-8").splitlines()
    sids = [i for i, line in enumerate(ci, 1) if 'Sid    = "GitHubActionsOIDC"' in line]
    lines = {"role:github-deploy": sids[0], "role:terraform-apply": sids[1]}
    for e in rows.edges:
        if e.type == "TRUSTS":
            (ev,) = e.evidence
            assert (ev.file, ev.line, ev.part) == ("terraform/ci.tf", lines[e.dst], "GitHubActionsOIDC")
            assert ev.note and e.src.removeprefix("workflow:") in ev.note


def test_workflows_without_an_id_token_trust_nothing(rows: Any) -> None:
    sources = {e.src for e in rows.edges if e.type == "TRUSTS"}
    assert not sources & {"workflow:demo-org/website/lint.yml", "workflow:demo-org/infra/ci.yml"}


def test_with_workflows_in_the_graph_every_requirement_has_its_principal(rows: Any) -> None:
    fors = {e.src for e in rows.edges if e.type == "FOR"}
    assert fors == {f"req:R{i}" for i in range(1, 18)}
    assert not [u for u in rows.unknowns if "missing FOR endpoint" in u]
