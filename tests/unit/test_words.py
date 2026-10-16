"""Plain words for graph things (theseus/engine/words.py), as the PR comment uses them."""

from __future__ import annotations

import pytest

from theseus.contracts.result import NodeInfo
from theseus.engine.words import access_words, article, class_words, kind, name, verb


@pytest.mark.parametrize(
    ("node", "info", "word"),
    [
        ("user:priya-intern", None, "user"),
        ("group:support-engineers", None, "group"),
        ("role:prod-support", None, "role"),
        ("workload:billing-api", None, "service"),
        ("workflow:demo-org/docs-site/preview.yml", None, "CI workflow"),
        ("db:customer-db", NodeInfo(category="Database"), "database"),
        ("s3://demo-app-logs/", NodeInfo(category="ObjectStorage"), "storage location"),
        ("secret:prod-db-credentials", NodeInfo(category="Secret"), "secret"),
        ("dynamodb:demo-orders", NodeInfo(category="Database"), "database"),
        ("log-group:/aws/lambda/billing-job", NodeInfo(category="LogStore"), "log store"),
        ("db:customer-db", None, "data store"),
    ],
)
def test_a_node_s_kind_in_words(node: str, info: NodeInfo | None, word: str) -> None:
    assert kind(node, info) == word


def test_every_category_has_plain_words() -> None:
    from theseus.contracts.schema import RESOURCE_CATEGORIES
    from theseus.engine import words

    assert sorted(words.CATEGORIES) == sorted(c.lower() for c in RESOURCE_CATEGORIES)


def test_names_and_articles() -> None:
    assert name("s3://demo-company-files/invoices/") == "demo-company-files/invoices/"
    assert name("entry:internet") == "anyone on the internet"
    assert [article(w) for w in ("user", "entry point", "AI model", "database")] == [
        "a user",
        "an entry point",
        "an AI model",
        "a database",
    ]


def test_what_an_edge_lets_its_source_do() -> None:
    assert verb("MEMBER_OF", ["read"]) == "is in"
    assert verb("CAN_ASSUME", ["read"]) == "can become"
    assert verb("UNLOCKS", []) == "opens"
    assert verb("CAN", ["read"]) == "can read"
    assert access_words(["write", "read"]) == "can read and change"
    assert verb("HAS_ENV", []) == "has env"


def test_what_a_data_class_means() -> None:
    assert class_words("regulated") == "personal, payment or health data, or a key that opens it"
    assert class_words(None) == "data of unknown sensitivity"
