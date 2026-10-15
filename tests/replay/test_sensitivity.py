"""Sensitivity of the demo world's resources (docs/spec/02-demo-world.md, "People and data"), replayed from
recordings/jev/: never the network.

Record or refresh the recordings with the TypeSafe key in .env:

    THESEUS_MODE=record pytest -q tests/replay/test_sensitivity.py
"""

from __future__ import annotations

import logging

import pytest

from theseus.agent.jev import Jev, JevAnswer
from theseus.agent.llm import Llm
from theseus.agent.sensitivity import apply, classify
from theseus.config import get_settings
from theseus.contracts.result import GraphRows, NodeRow, Sensitivity

RESOURCE = ["Node", "Resource"]
# (ID, category, name, the class spec 02 expects). None where theseus.yaml overrides it: Jev rates both from
# the name alone, and neither name says what the files hold.
DEMO: list[tuple[str, str, str, Sensitivity | None]] = [
    ("s3://demo-app-logs/", "object_store", "demo-app-logs/", "internal"),
    ("s3://demo-company-files/invoices/", "object_store", "demo-company-files/invoices/", "confidential"),
    ("s3://demo-company-files/public/", "object_store", "demo-company-files/public/", "public"),
    ("s3://demo-data-lake/raw/", "object_store", "demo-data-lake/raw/", None),
    ("s3://demo-data-lake/curated/", "object_store", "demo-data-lake/curated/", "internal"),
    ("s3://demo-terraform-state/", "object_store", "demo-terraform-state/", None),
    ("secret:prod-db-credentials", "secret", "prod-db-credentials", "regulated"),
    ("secret:payments-api-key", "secret", "payments-api-key", "regulated"),
    ("db:customer-db", "database", "customer-db", "regulated"),
    ("dynamodb:demo-orders", "table", "demo-orders", "confidential"),
]
OVERRIDES: dict[str, Sensitivity] = {  # theseus.yaml in spec 02
    "s3://demo-terraform-state/": "regulated",
    "s3://demo-data-lake/raw/": "regulated",
}
NODES = [NodeRow(id=i, labels=RESOURCE, name=n, category=c) for i, c, n, _ in DEMO]  # type: ignore[arg-type]
ROWS = GraphRows(nodes=[*NODES, NodeRow(id="user:priya-intern", labels=["Node", "Principal"], name="priya")])


@pytest.fixture(scope="module")
def labels() -> dict[str, Sensitivity]:
    settings = get_settings()
    return classify(NODES, Jev(settings, llm=Llm(settings)))


def test_every_demo_resource_is_rated(labels: dict[str, Sensitivity]) -> None:
    assert sorted(labels) == sorted(i for i, *_ in DEMO)


def test_the_scenarios_sensitive_resources_are_sensitive(labels: dict[str, Sensitivity]) -> None:
    """What the engine needs: `sensitive` matches spec 02 for every resource, after the override."""
    nodes = {n.id: n for n in apply(ROWS, labels, OVERRIDES).nodes}
    for node, _, _, expected in DEMO:
        want = (expected or OVERRIDES[node]) in ("confidential", "regulated")
        assert nodes[node].sensitive is want, f"{node}: Jev said {labels[node]}, spec 02 expects {expected}"


def test_an_override_always_wins() -> None:
    labelled = apply(ROWS, {"s3://demo-terraform-state/": "public"}, OVERRIDES)
    node = next(n for n in labelled.nodes if n.id == "s3://demo-terraform-state/")
    assert (node.sensitivity, node.sensitive, node.sensitivity_source) == ("regulated", True, "human")


def test_jev_labels_are_marked_as_jev_s() -> None:
    labelled = apply(ROWS, {"db:customer-db": "regulated", "s3://demo-app-logs/": "internal"}, {})
    nodes = {n.id: n for n in labelled.nodes}
    assert (nodes["db:customer-db"].sensitive, nodes["db:customer-db"].sensitivity_source) == (True, "jev")
    assert (nodes["s3://demo-app-logs/"].sensitive, nodes["s3://demo-app-logs/"].sensitivity) == (
        False,
        "internal",
    )


def test_a_resource_with_no_label_is_unclassified_and_not_sensitive() -> None:
    node = next(n for n in apply(ROWS, {}, {}).nodes if n.id == "db:customer-db")
    assert (node.sensitivity, node.sensitive, node.sensitivity_source) == (None, False, "unclassified")


def test_principals_are_left_alone() -> None:
    node = next(n for n in apply(ROWS, {}, OVERRIDES).nodes if n.id == "user:priya-intern")
    assert node.sensitivity_source is None


class FallbackJev:
    def sensitivity(self, resources: list[tuple[str, str, str]]) -> dict[str, JevAnswer]:
        return {
            r[0]: JevAnswer(type="choice", choice="regulated", source="fallback", calibrated=False)
            for r in resources
        }


def test_labels_from_the_fallback_are_logged_as_uncalibrated(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="theseus.agent.sensitivity"):
        labels = classify(NODES[:1], FallbackJev())
    assert labels == {"s3://demo-app-logs/": "regulated"}
    assert "uncalibrated" in caplog.text
