"""Valid paths, dangerous paths, requirement status and the diff (04-engine.md 9 to 11), on small graphs."""

from __future__ import annotations

from typing import Any

import pytest

from theseus.contracts.engine import GraphState, World
from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow, Requirement
from theseus.engine.analyze import analyze, diff
from theseus.graph.store import MemoryStore


def ev(file: str, line: int, address: str = "x", part: str | None = None) -> Evidence:
    return Evidence(address=address, part=part, file=file, line=line)


def node(nid: str, *labels: str, sensitive: bool = False, **extra: Any) -> NodeRow:
    return NodeRow(id=nid, name=nid, labels=["Node", *labels], sensitive=sensitive, **extra)


def edge(
    eid: str,
    etype: str,
    src: str,
    dst: str,
    *,
    grants: list[str] | None = None,
    kind: str = "configured",
    evidence: list[Evidence] | None = None,
) -> EdgeRow:
    return EdgeRow(
        eid=eid,
        type=etype,
        src=src,
        dst=dst,
        kind=kind,
        grants=grants or [],
        evidence=evidence or [ev("t.tf", int(eid[1:]))],
    )  # type: ignore[arg-type]


NODES = [
    node("user:priya", "Principal", "User"),
    node("user:sam", "Principal", "User"),
    node("group:support", "Principal", "Group"),
    node("role:prod", "Principal", "Role", props={"address": "aws_iam_role.prod"}),
    node("secret:db", "Resource", "Secret", category="Secret", sensitive=True, sensitivity="regulated"),
    node(
        "db:customers", "Resource", "Database", category="Database", sensitive=True, sensitivity="regulated"
    ),
    node("s3://logs/", "Resource", "ObjectStorage", category="ObjectStorage", sensitivity="internal"),
    node("s3://files/invoices/", "Resource", "ObjectStorage", category="ObjectStorage", sensitive=True),
]
EDGES = [
    edge("e1", "MEMBER_OF", "user:sam", "group:support"),
    edge(
        "e3",
        "CAN_ASSUME",
        "group:support",
        "role:prod",
        evidence=[
            ev("people.tf", 56, "aws_iam_group_policy.a", "Assume"),
            ev("roles.tf", 9, "aws_iam_role.prod", "Trust"),
        ],
    ),
    edge("e4", "CAN", "role:prod", "secret:db", grants=["read"]),
    edge("e5", "UNLOCKS", "secret:db", "db:customers", grants=["read", "write"], kind="inferred"),
    edge("e6", "CAN", "role:prod", "s3://logs/", grants=["read"]),
    edge("e7", "CAN", "role:prod", "s3://files/invoices/", grants=["read"]),
]
REQS = [
    Requirement(id="R1", principal="user:sam", access="read", resource="s3://logs/", source="config"),
    Requirement(
        id="R2", principal="user:sam", access="read", resource="s3://files/invoices/", source="config"
    ),
    Requirement(id="R3", principal="user:sam", access="read", resource="db:customers", source="config"),
]


def state(name: str, edges: list[EdgeRow], nodes: list[NodeRow] = NODES) -> tuple[MemoryStore, GraphState]:
    store = MemoryStore()
    rows = GraphRows(nodes=nodes, edges=edges)
    store.load(name, rows)
    return store, GraphState(name=name, world=World(root="w", iac="terraform"), rows=rows)


def keys(paths: list[Any]) -> list[tuple[str, str]]:
    return [(p.actor, p.target) for p in paths]


def test_a_member_s_routes_are_valid_paths_with_grants_and_steps() -> None:
    store, s = state("g", EDGES)
    a = analyze(store, s, REQS, ["user:sam"])
    by_target = {p.target: p for p in a.paths["user:sam"]}
    assert set(by_target) == {"secret:db", "db:customers", "s3://logs/", "s3://files/invoices/"}
    db = by_target["db:customers"]
    assert db.route == ["user:sam", "group:support", "role:prod", "secret:db", "db:customers"]
    assert db.grants == ["read", "write"] and db.inferred and not db.unknown
    assert db.sensitivity == "regulated"
    assert [(st.src, st.type, st.dst) for st in db.steps][0] == ("user:sam", "MEMBER_OF", "group:support")


def test_covered_targets_are_not_dangerous_and_a_secret_on_a_required_route_is_covered() -> None:
    store, s = state("g", EDGES)
    a = analyze(store, s, REQS, ["user:sam"])
    assert a.dangerous == []
    assert {r.id: r.status for r in a.requirements} == {
        "R1": "satisfied",
        "R2": "satisfied",
        "R3": "satisfied",
    }


def test_a_new_member_opens_every_sensitive_target_no_requirement_covers() -> None:
    edges = [*EDGES, edge("e2", "MEMBER_OF", "user:priya", "group:support")]
    store, s = state("g", edges)
    a = analyze(store, s, REQS, ["user:priya", "user:sam"])
    assert keys(a.dangerous) == [
        ("user:priya", "db:customers"),
        ("user:priya", "s3://files/invoices/"),
        ("user:priya", "secret:db"),
    ]


def test_the_diff_keys_paths_by_actor_and_target() -> None:
    store, base_state = state("base", EDGES)
    base = analyze(store, base_state, REQS, ["user:priya", "user:sam"])
    store2, head_state = state("head", [*EDGES, edge("e2", "MEMBER_OF", "user:priya", "group:support")])
    head = analyze(store2, head_state, REQS, ["user:priya", "user:sam"])
    d = diff(base, head)
    assert keys(d.opened) == keys(head.dangerous) and d.closed == [] and d.unchanged == []
    back = diff(head, base)
    assert keys(back.closed) == keys(head.dangerous) and back.opened == []


@pytest.mark.parametrize(
    "extra,why",
    [
        ([edge("e8", "CAN", "secret:db", "s3://logs/", grants=["read"])], "CAN from a resource"),
        ([edge("e8", "UNLOCKS", "s3://logs/", "db:customers", grants=["read"])], "UNLOCKS from a non-secret"),
        ([edge("e8", "CAN_ASSUME", "role:prod", "group:support")], "a route that visits a node twice"),
    ],
)
def test_only_valid_routes_become_paths(extra: list[EdgeRow], why: str) -> None:
    store, s = state("g", [*EDGES, *extra])
    a = analyze(store, s, REQS, ["user:sam"])
    for p in a.paths["user:sam"]:
        assert len(set(p.route)) == len(p.route), why
        types = [st.type for st in p.steps]
        assert types.index("CAN") == len(types) - 1 or types[-2:] == ["CAN", "UNLOCKS"], why


def test_an_unknown_edge_makes_a_requirement_unknown_and_a_missing_route_missing() -> None:
    edges = [e.model_copy(update={"kind": "unknown"}) if e.eid == "e7" else e for e in EDGES if e.eid != "e6"]
    store, s = state("g", edges)
    a = analyze(store, s, REQS, ["user:sam"])
    assert {r.id: r.status for r in a.requirements} == {"R1": "missing", "R2": "unknown", "R3": "satisfied"}


def test_write_needs_a_write_grant_and_assume_needs_only_traversal() -> None:
    reqs = [
        Requirement(id="W", principal="user:sam", access="write", resource="s3://logs/", source="config"),
        Requirement(id="D", principal="user:sam", access="write", resource="db:customers", source="config"),
        Requirement(id="A", principal="user:sam", access="assume", resource="role:prod", source="config"),
    ]
    store, s = state("g", EDGES)
    a = analyze(store, s, reqs, ["user:sam"])
    # UNLOCKS grants read and write, so the database is written through the secret.
    assert {r.id: r.status for r in a.requirements} == {"W": "missing", "D": "satisfied", "A": "satisfied"}


def test_intent_requirements_never_cover() -> None:
    edges = [*EDGES, edge("e2", "MEMBER_OF", "user:priya", "group:support")]
    intent = Requirement(
        id="I1", principal="user:priya", access="read", resource="db:customers", source="intent"
    )
    store, s = state("g", edges)
    a = analyze(store, s, [*REQS, intent], ["user:priya", "user:sam"])
    assert ("user:priya", "db:customers") in keys(a.dangerous)
    assert {r.id: r.status for r in a.requirements}["I1"] == "satisfied"


def test_an_assume_step_cites_the_caller_s_permission_not_the_role_s_trust() -> None:
    store, s = state("g", EDGES)
    a = analyze(store, s, REQS, ["user:sam"])
    db = next(p for p in a.paths["user:sam"] if p.target == "db:customers")
    assume = next(st for st in db.steps if st.type == "CAN_ASSUME")
    assert assume.evidence == "people.tf:56:aws_iam_group_policy.a:Assume"


def test_path_ids_are_stable_across_builds_and_eids() -> None:
    store, s = state("g", EDGES)
    renumbered = [e.model_copy(update={"eid": f"x{i}"}) for i, e in enumerate(EDGES)]
    store2, s2 = state("g2", renumbered)
    one = analyze(store, s, REQS, ["user:sam"]).paths["user:sam"]
    two = analyze(store2, s2, REQS, ["user:sam"]).paths["user:sam"]
    assert [p.id for p in one] == [p.id for p in two]
    assert [p.actor for p in one] == sorted(p.actor for p in one)
