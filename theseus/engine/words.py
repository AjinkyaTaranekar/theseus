"""Plain words for graph things, so a reader with no context can follow a finding: what a node is, what an
edge lets it do, and what a data class means. The PR comment uses them, and so does the headline
(04-engine.md section 18). They name categories and core kinds only, never a vendor's resource type.
"""

from __future__ import annotations

from theseus.contracts.result import NodeInfo
from theseus.contracts.schema import INTERNET, parse_id

# Core kinds, as a person would say them.
KINDS = {
    "user": "user",
    "group": "group",
    "role": "role",
    "workload": "service",
    "workflow": "CI workflow",
    "action": "GitHub Action",
    "entry": "entry point",
}
# Resource categories, keyed by a normalized name so both spellings work ("object_store", "ObjectStorage").
CATEGORIES = {
    "objectstore": "storage location",
    "objectstorage": "storage location",
    "filestorage": "file share",
    "blockstorage": "disk",
    "database": "database",
    "table": "database table",
    "secret": "secret",
    "encryptionkey": "encryption key",
    "aimodel": "AI model",
    "logstore": "log store",
    "messagequeue": "message queue",
    "messagetopic": "message topic",
    "datastream": "data stream",
}
CLASSES = {
    "regulated": "personal, payment or health data, or a key that opens it",
    "confidential": "business-sensitive data, such as invoices or contracts",
    "internal": "internal data, little harm if exposed",
    "public": "public data",
}
# What an edge lets its source do to its target, as the next clause of a sentence.
VERBS = {
    "MEMBER_OF": "is a member of",
    "CAN_ASSUME": "can switch into",
    "TRUSTS": "can sign in as",
    "RUNS_AS": "runs as",
    "UNLOCKS": "unlocks",
    "USES": "uses",
    "CALLS": "calls",
    "REQUESTS": "sends requests to",
}
ACCESS = {("read",): "can read", ("write",): "can change", ("read", "write"): "can read and change"}


def name(node: str) -> str:
    """The node's own name: `priya-intern`, `demo-company-files/invoices/`, or "anyone on the internet"."""
    return "anyone on the internet" if node == INTERNET else parse_id(node)[1]


def kind(node: str, info: NodeInfo | None = None) -> str:
    """What the node is: a core kind in words, a resource's category in words, or "data store"."""
    k = parse_id(node)[0]
    if k in KINDS:
        return KINDS[k]
    if info is not None and info.category:
        return CATEGORIES.get(info.category.lower().replace("_", ""), "data store")
    return "data store"


def article(word: str) -> str:
    """The word with its article, by sound: a user, an entry point, an AI model."""
    return f"an {word}" if word[:1].lower() in "aeio" else f"a {word}"


def class_words(sensitivity: str | None) -> str:
    return CLASSES.get(sensitivity or "", "data of unknown sensitivity")


def access_words(grants: list[str]) -> str:
    """`can read`, `can change` or `can read and change`, from a path's grants."""
    key = tuple(sorted(g for g in set(grants) if g in ("read", "write")))
    return ACCESS.get(key, "can reach")


def verb(edge_type: str, grants: list[str]) -> str:
    """What an edge lets its source do. A grant edge says what access it gives."""
    return (
        access_words(grants)
        if edge_type == "CAN"
        else VERBS.get(edge_type, edge_type.lower().replace("_", " "))
    )
