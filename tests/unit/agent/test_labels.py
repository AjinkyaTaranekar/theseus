"""The labels a reviewed PR carries (docs/spec/07-github-and-deploy.md, "Labels"), from results like the
engine's: one severity S0 to S6, one verdict, the most sensitive class reached, says versus grants and
steering."""

from __future__ import annotations

import pytest

from theseus.agent.labels import LABELS, PREFIX, SEVERITY, labels_for, severity
from theseus.contracts.result import (
    AnalysisResult,
    BeyondIntent,
    Grant,
    Intent,
    NodeInfo,
    PathRecord,
    PathStep,
)

PRIYA = "user:priya-intern"
INTENT = Intent(
    purpose="Let Priya read the app logs.",
    grants=[Grant(principal=PRIYA, access="read", resource="s3://demo-app-logs/")],
)


def opened(actor: str, target: str, sensitivity: str | None) -> PathRecord:
    step = PathStep(src=actor, type="CAN", dst=target, evidence="E1", grants=["read"])
    return PathRecord.model_validate(
        {"id": f"p-{target}", "actor": actor, "target": target, "grants": ["read"], "steps": [step]}
        | {"sensitivity": sensitivity}
    )


def pr(**fields: object) -> AnalysisResult:
    return AnalysisResult.model_validate({"mode": "pr", "intent": INTENT, **fields})


def names(result: AnalysisResult) -> list[str]:
    return [label.name.removeprefix(PREFIX) for label in labels_for(result)]


DB = opened(PRIYA, "db:customer-db", "regulated")
INVOICES = opened(PRIYA, "s3://demo-company-files/invoices/", "confidential")
CODE = BeyondIntent(
    workload="workload:billing-api", resource="db:customer-db", access="read", file="a.py", line=3
)


@pytest.mark.parametrize(
    ("result", "level"),
    [
        (pr(opened=[opened("entry:internet", "db:customer-db", "regulated")]), 0),
        (pr(opened=[DB, INVOICES]), 1),
        (pr(opened=[opened("entry:internet", "s3://demo-company-files/public/", "confidential")]), 1),
        (pr(use_beyond_intent=[CODE], nodes={"db:customer-db": NodeInfo(sensitivity="regulated")}), 1),
        (pr(opened=[INVOICES]), 2),
        (pr(opened=[opened(PRIYA, "db:x", None)]), 3),
        (pr(use_beyond_intent=[CODE]), 3),
        (pr(unknowns=["aws_kms_key.main: not modeled"]), 4),
        (pr(intent=Intent(purpose="", stated=False)), 5),
        (pr(intent=INTENT.model_copy(update={"suspicious": True})), 5),
        (pr(), 6),
        (AnalysisResult(mode="pr"), 6),
    ],
)
def test_severity_follows_the_first_rule_that_holds(result: AnalysisResult, level: int) -> None:
    assert severity(result) == level


def test_the_intern_pr_is_s1_blocked_on_regulated_data_and_grants_more_than_it_says() -> None:
    assert names(pr(opened=[DB, INVOICES])) == ["S1", "blocked", "grants more than it says", "regulated data"]


def test_a_pr_that_asks_for_what_it_gets_is_not_labelled_as_granting_more() -> None:
    asked = INTENT.model_copy(
        update={"grants": [Grant(principal=PRIYA, access="read", resource="db:customer-db")]}
    )
    assert "grants more than it says" not in names(pr(intent=asked, opened=[DB]))


def test_steering_text_and_the_other_verdicts() -> None:
    assert names(pr(intent=INTENT.model_copy(update={"suspicious": True}))) == [
        "S5",
        "clear",
        "steering text",
    ]
    assert names(pr(unknowns=["x"])) == ["S4", "needs a look"]
    assert names(pr()) == ["S6", "clear"]
    assert names(pr(opened=[INVOICES])) == ["S2", "blocked", "confidential data", "grants more than it says"]


def test_every_label_is_theseus_s_own_and_fits_github() -> None:
    assert len({label.name for label in LABELS}) == len(LABELS)
    for label in LABELS:
        assert label.name.startswith(PREFIX) and len(label.name) <= 50
        assert len(label.description) <= 100 and len(label.color) == 6
        int(label.color, 16)
    assert [label.name for label in SEVERITY] == [f"{PREFIX}S{n}" for n in range(7)]
