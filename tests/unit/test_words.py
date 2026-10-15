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
        ("db:customer-db", NodeInfo(category="database"), "database"),
        ("s3://demo-app-logs/", NodeInfo(category="object_store"), "storage location"),
        ("secret:prod-db-credentials", NodeInfo(category="secret"), "secret"),
        ("dynamodb:demo-orders", NodeInfo(category="table"), "database table"),
        ("db:customer-db", None, "data store"),
    ],
)
def test_a_node_s_kind_in_words(node: str, info: NodeInfo | None, word: str) -> None:
    assert kind(node, info) == word


def test_both_spellings_of_a_category_read_the_same() -> None:
    """The adapters' categories are moving to the Cartography labels (#50); both must read the same."""
    from theseus.engine import words

    assert words.CATEGORIES["objectstorage"] == words.CATEGORIES["objectstore"]
    assert words.CATEGORIES["database"] == "database"


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
    assert verb("MEMBER_OF", ["read"]) == "is a member of"
    assert verb("CAN_ASSUME", ["read"]) == "can switch into"
    assert verb("CAN", ["read"]) == "can read"
    assert access_words(["write", "read"]) == "can read and change"
    assert verb("HAS_ENV", []) == "has env"


def test_what_a_data_class_means() -> None:
    assert class_words("regulated") == "personal, payment or health data, or a key that opens it"
    assert class_words(None) == "data of unknown sensitivity"
