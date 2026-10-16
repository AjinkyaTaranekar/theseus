"""The GitHub Actions reader: workflows, their OIDC `sub` values, Actions and USES edges (04 section 6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from theseus.adapters.github.adapter import GithubAdapter
from theseus.adapters.github.workflows import ISSUER, parse_workflow

ROOT = Path(__file__).resolve().parents[4]
WORLD = ROOT / "demo-infra"

# Spec 02, "Workflows in demo-infra/workflows/demo-org/": id-token, and the sub values each can present.
DEMO = {
    "workflow:demo-org/infra/deploy.yml": (
        True,
        ["repo:demo-org/infra:environment:production", "repo:demo-org/infra:ref:refs/heads/main"],
    ),
    "workflow:demo-org/infra/ci.yml": (False, []),
    "workflow:demo-org/docs-site/preview.yml": (True, ["repo:demo-org/docs-site:pull_request"]),
    "workflow:demo-org/website/lint.yml": (False, []),
}
# Spec 02's "Jobs and uses:" column, by workflow.
USES = {
    "workflow:demo-org/infra/deploy.yml": {
        "action:actions/checkout": "v4",
        "action:aws-actions/configure-aws-credentials": "v4",
        "action:hashicorp/setup-terraform": "v3",
    },
    "workflow:demo-org/infra/ci.yml": {
        "action:actions/checkout": "v4",
        "action:hashicorp/setup-terraform": "v3",
        "action:actions/setup-python": "v5",
    },
    "workflow:demo-org/docs-site/preview.yml": {
        "action:actions/checkout": "v4",
        "action:demo-thirdparty/file-diff": "v3",
    },
    "workflow:demo-org/website/lint.yml": {
        "action:actions/checkout": "v4",
        "action:demo-thirdparty/file-diff": "v3",
    },
}


@pytest.fixture(scope="module")
def files() -> dict[str, str]:
    return {
        p.relative_to(WORLD).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted((WORLD / "workflows").rglob("*.yml"))
    }


def path_of(workflow: str) -> str:
    return "workflows/" + workflow.removeprefix("workflow:")


def lines_with(text: str, needle: str) -> list[int]:
    return [i for i, line in enumerate(text.splitlines(), 1) if needle in line]


def test_every_demo_workflow_presents_exactly_its_subs(files: dict[str, str]) -> None:
    read = GithubAdapter().read(files)
    workflows = {n.id: n for n in read.rows.nodes if "Workflow" in n.labels}
    assert set(workflows) == set(DEMO)
    for wid, (id_token, subs) in DEMO.items():
        node = workflows[wid]
        assert node.labels == ["Node", "Principal", "Workflow"]
        assert node.props == {
            "repo": "demo-org/" + wid.split("/")[1],
            "file": path_of(wid),
            "subs": subs,
            "id_token": id_token,
        }, wid
    # Only a workflow that can request an ID token presents an identity.
    assert [(i.workflow, i.issuer, i.subjects) for i in read.identities] == [
        (wid, ISSUER, subs) for wid, (id_token, subs) in sorted(DEMO.items()) if id_token
    ]
    assert read.rows.unknowns == []


def test_every_uses_line_becomes_one_edge_per_action_with_each_line_cited(files: dict[str, str]) -> None:
    read = GithubAdapter().read(files)
    actions = {n.id: n for n in read.rows.nodes if "Action" in n.labels}
    assert set(actions) == {a for uses in USES.values() for a in uses}
    assert all(n.labels == ["Action", "Node"] for n in actions.values())
    assert actions["action:demo-thirdparty/file-diff"].props == {"version": "v3"}
    edges = {(e.src, e.dst): e for e in read.rows.edges}
    assert set(edges) == {(w, a) for w, uses in USES.items() for a in uses}
    for (wid, aid), edge in edges.items():
        text = files[path_of(wid)]
        lines = lines_with(text, f"uses: {aid.removeprefix('action:')}@")
        assert edge.type == "USES" and edge.kind == "configured"
        assert edge.props == {"version": USES[wid][aid], "line": lines[0]}, (wid, aid)
        assert [(ev.file, ev.line) for ev in edge.evidence] == [(path_of(wid), n) for n in lines]
        assert all(ev.address == path_of(wid) and ev.part for ev in edge.evidence)
    # deploy.yml uses checkout in both jobs: one edge, both lines, each naming its job.
    checkout = edges[("workflow:demo-org/infra/deploy.yml", "action:actions/checkout")]
    assert [ev.part for ev in checkout.evidence] == ["apply", "release"]


def test_the_rows_are_sorted_and_independent_of_file_order(files: dict[str, str]) -> None:
    forward = GithubAdapter().read(files)
    backward = GithubAdapter().read(dict(reversed(list(files.items()))))
    assert forward == backward
    assert [n.id for n in forward.rows.nodes] == sorted(n.id for n in forward.rows.nodes)
    assert [(e.src, e.dst) for e in forward.rows.edges] == sorted((e.src, e.dst) for e in forward.rows.edges)


# One workflow at a time ---------------------------------------------------------------------------------


def one(text: str, path: str = "workflows/acme/app/build.yml") -> tuple[bool, list[str]]:
    parsed = parse_workflow("acme", "app", path, text)
    return parsed.node.props["id_token"], parsed.node.props["subs"]


@pytest.mark.parametrize(
    "text,expected",
    [
        # PyYAML reads `on:` as True; a string, a list and a mapping of triggers all work.
        (
            "on: push\npermissions: {id-token: write}\njobs: {b: {runs-on: x}}\n",
            ["repo:acme/app:ref:refs/heads/main"],
        ),
        (
            "on: [push, pull_request]\npermissions: {id-token: write}\njobs: {b: {runs-on: x}}\n",
            ["repo:acme/app:pull_request", "repo:acme/app:ref:refs/heads/main"],
        ),
        (
            "on: {push: {branches: [main, release]}}\npermissions: {id-token: write}\n"
            "jobs: {b: {runs-on: x}}\n",
            ["repo:acme/app:ref:refs/heads/main", "repo:acme/app:ref:refs/heads/release"],
        ),
        (
            "'on': {pull_request_target: {}}\npermissions: write-all\njobs: {b: {runs-on: x}}\n",
            ["repo:acme/app:pull_request"],
        ),
        # A job with an environment presents only the environment's sub, as GitHub does.
        (
            "on: push\npermissions: {id-token: write}\njobs: {d: {environment: {name: prod, url: x}}}\n",
            ["repo:acme/app:environment:prod"],
        ),
    ],
)
def test_subs_follow_the_triggers_and_the_environment(text: str, expected: list[str]) -> None:
    assert one(text) == (True, expected)


@pytest.mark.parametrize(
    "text,expected",
    [
        # Job-level permissions replace the top level: this job cannot ask for a token.
        (
            "on: push\npermissions: {id-token: write}\njobs: {b: {permissions: {contents: read}}}\n",
            (False, []),
        ),
        # Only the job that asks for a token contributes its sub.
        (
            "on: push\njobs:\n  a: {environment: prod}\n  b: {permissions: {id-token: write}}\n",
            (True, ["repo:acme/app:ref:refs/heads/main"]),
        ),
        # No permissions at all: the default token has no id-token permission.
        ("on: push\njobs: {b: {runs-on: x}}\n", (False, [])),
        ("on: push\npermissions: read-all\njobs: {b: {runs-on: x}}\n", (False, [])),
    ],
)
def test_only_jobs_that_can_request_a_token_present_a_sub(
    text: str, expected: tuple[bool, list[str]]
) -> None:
    assert one(text) == expected


def test_a_token_with_no_known_sub_is_an_unknown() -> None:
    parsed = parse_workflow(
        "acme",
        "app",
        "workflows/acme/app/x.yml",
        "on: workflow_dispatch\npermissions: {id-token: write}\njobs: {b: {}}\n",
    )
    assert parsed.node.props["subs"] == [] and parsed.identity is not None and parsed.identity.subjects == []
    assert parsed.unknowns == [
        "ci: workflows/acme/app/x.yml can request an ID token, but no trigger gives it a known sub"
    ]


def test_local_and_docker_steps_are_not_actions_and_a_reusable_workflow_is() -> None:
    text = (
        "on: push\njobs:\n  a:\n    steps:\n      - uses: ./local-action\n      - uses: docker://alpine:3\n"
        "      - uses: acme/tools/lint@v2\n  b:\n    uses: acme/shared/.github/workflows/deploy.yml@main\n"
    )
    parsed = parse_workflow("acme", "app", "workflows/acme/app/x.yml", text)
    assert sorted((e.dst, e.props["version"], e.props["line"]) for e in parsed.uses) == [
        ("action:acme/shared", "main", 9),
        ("action:acme/tools", "v2", 7),
    ]


def test_a_workflow_that_does_not_parse_is_an_unknown_not_a_crash() -> None:
    read = GithubAdapter().read(
        {"workflows/acme/app/bad.yml": "on: [push\njobs: {", "notes/readme.yml": "a: 1\n"}
    )
    assert read.rows.nodes == [] and read.identities == []
    assert read.rows.unknowns == [
        "ci: notes/readme.yml is not under workflows/<org>/<repo>/",
        "ci: workflows/acme/app/bad.yml does not parse",
    ]
