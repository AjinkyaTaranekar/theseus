"""Says versus grants (04-engine.md section 18): the headline, approved intent, and what the change does."""

from __future__ import annotations

import pytest

from theseus.contracts.adapters import IacResource
from theseus.contracts.engine import World
from theseus.contracts.result import (
    BeyondIntent,
    Grant,
    Intent,
    NodeInfo,
    NodeRow,
    PathRecord,
    PathStep,
    Requirement,
    ResourceChange,
)
from theseus.engine.intent_effect import approved, change_line, changes, headline

NODES = {
    "db:customer-db": NodeInfo(category="Database", sensitivity="regulated"),
    "secret:prod-db-credentials": NodeInfo(category="Secret", sensitivity="regulated"),
    "s3://demo-company-files/invoices/": NodeInfo(category="ObjectStorage", sensitivity="confidential"),
    "s3://demo-app-logs/": NodeInfo(category="ObjectStorage", sensitivity="internal"),
}
PRIYA = "user:priya-intern"
LOGS = Intent(
    purpose="Add Priya to the support-engineers group so she can read production logs.",
    grants=[Grant(principal=PRIYA, access="read", resource="s3://demo-app-logs/")],
)


def path(target: str, hops: list[tuple[str, str, str]]) -> PathRecord:
    steps = [PathStep.model_validate({"from": a, "type": t, "to": b, "evidence": "e"}) for a, t, b in hops]
    return PathRecord(
        id=target,
        actor=PRIYA,
        target=target,
        grants=["read"],
        steps=steps,
        sensitivity=NODES[target].sensitivity,
    )


START = [
    (PRIYA, "MEMBER_OF", "group:support-engineers"),
    ("group:support-engineers", "CAN_ASSUME", "role:prod-support"),
]
INVOICES = path(
    "s3://demo-company-files/invoices/",
    [*START, ("role:prod-support", "CAN", "s3://demo-company-files/invoices/")],
)
SECRET = path(
    "secret:prod-db-credentials", [*START, ("role:prod-support", "CAN", "secret:prod-db-credentials")]
)
DB = path(
    "db:customer-db",
    [
        *START,
        ("role:prod-support", "CAN", "secret:prod-db-credentials"),
        ("secret:prod-db-credentials", "UNLOCKS", "db:customer-db"),
    ],
)
OPENED = [INVOICES, SECRET, DB]
READS = [
    BeyondIntent(
        workload="workload:support-portal",
        resource="secret:prod-db-credentials",
        access="read",
        file="f",
        line=1,
        unlocks=["db:customer-db"],
    ),
    BeyondIntent(
        workload="workload:support-portal", resource="db:customer-db", access="read", file="f", line=2
    ),
]


def test_opened_paths_name_the_most_sensitive_target_a_database_before_its_secret() -> None:
    assert headline(LOGS, OPENED, [], NODES) == (
        "Your PR says: add Priya to the support-engineers group so she can read production logs. "
        "Your change grants customer-db, a database."
    )
    # Regulated before confidential, whatever the order the paths come in.
    assert headline(LOGS, [INVOICES, SECRET], [], NODES).endswith(
        "Your change grants prod-db-credentials, a secret."
    )


def test_a_target_the_pr_asks_for_is_named_and_still_needs_an_owner() -> None:
    asks = LOGS.model_copy(
        update={"grants": [Grant(principal=PRIYA, access="read", resource="db:customer-db")]}
    )
    assert headline(asks, OPENED, [], NODES) == (
        "Your PR asks for customer-db, a database. "
        "Access to sensitive data needs an owner's approval in theseus.yaml."
    )


def test_code_that_reads_beyond_intent_names_the_database_before_the_secret() -> None:
    typo = Intent(purpose="Fix a typo in the refund confirmation text.")
    assert headline(typo, [], READS, NODES) == (
        "Your PR says: fix a typo in the refund confirmation text. "
        "Your code now reads customer-db, a database."
    )


def test_nothing_beyond_intent_matches_the_stated_purpose() -> None:
    assert headline(LOGS, [], [], NODES) == "This change matches its stated purpose."


@pytest.mark.parametrize(
    "opened,beyond,expected",
    [
        (OPENED, [], "This PR doesn't say what it's for. Your change grants customer-db, a database."),
        ([], READS, "This PR doesn't say what it's for. Your code now reads customer-db, a database."),
        ([], [], "This PR doesn't say what it's for. It opens no dangerous path."),
    ],
)
def test_a_pr_that_states_no_purpose_says_so(opened: list, beyond: list, expected: str) -> None:
    silent = Intent(purpose="", stated=False)
    assert headline(silent, opened, beyond, NODES) == expected
    assert headline(None, opened, beyond, NODES) == expected


def test_an_acronym_keeps_its_capitals_and_the_purpose_loses_its_full_stop() -> None:
    assert headline(Intent(purpose="IAM cleanup for the data team."), [DB], [], NODES).startswith(
        "Your PR says: IAM cleanup for the data team. Your change"
    )


def test_intent_on_sensitive_data_or_from_a_suspicious_pr_is_not_approved() -> None:
    nodes = {
        "s3://demo-app-logs/": NodeRow(
            id="s3://demo-app-logs/", name="x", labels=["Node", "Resource"], sensitive=False
        ),
        "db:customer-db": NodeRow(id="db:customer-db", name="x", labels=["Node", "Resource"], sensitive=True),
    }
    config = [
        Requirement(id="R1", principal="user:sam", access="read", resource="db:customer-db", source="config")
    ]
    logs = Requirement(
        id="I1", principal=PRIYA, access="read", resource="s3://demo-app-logs/", source="intent"
    )
    db = Requirement(id="I2", principal=PRIYA, access="read", resource="db:customer-db", source="intent")
    assert [r.id for r in approved([*config, logs, db], LOGS, nodes)] == ["R1", "I1"]
    shady = LOGS.model_copy(update={"suspicious": True})
    assert [r.id for r in approved([*config, logs, db], shady, nodes)] == ["R1"]


def resource(address: str, **values: object) -> IacResource:
    return IacResource(
        address=address,
        type=address.split(".")[0],
        name=address.split(".")[1],
        provider="aws",
        values=dict(values),
    )


def test_changes_and_the_line_that_says_what_the_change_does() -> None:
    base = World(
        root="b",
        iac="terraform",
        resources=[resource("a.keep", v=1), resource("a.edit", v=1), resource("a.gone")],
    )
    head = World(
        root="h",
        iac="terraform",
        resources=[resource("a.keep", v=1), resource("a.edit", v=2), resource("a.new")],
    )
    found = changes(base, head)
    assert [(c.action, c.address) for c in found] == [
        ("update", "a.edit"),
        ("delete", "a.gone"),
        ("create", "a.new"),
    ]
    assert (
        change_line(found, OPENED, [])
        == "Adds a.new, changes a.edit, removes a.gone. Opens 3 dangerous paths, closes 0."
    )
    one = [ResourceChange(address="aws_iam_user_group_membership.priya_support", type="x", action="create")]
    assert change_line(one, [DB], [SECRET]) == (
        "Adds aws_iam_user_group_membership.priya_support. Opens 1 dangerous path, closes 1."
    )
    assert change_line([], [], []) == "Changes no resource. Opens 0 dangerous paths, closes 0."
