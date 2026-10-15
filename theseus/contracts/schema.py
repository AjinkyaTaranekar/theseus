"""Graph schema constants and node ID helpers (docs/spec/03-graph.md, docs/spec/08-core-and-adapters.md).

Everything here is vendor-neutral. Resource kinds, resource types and patch ops belong to the cloud adapter.
"""

from __future__ import annotations

import re
from typing import Final

from theseus.errors import GraphError

# Labels. Every node has NODE and one kind label; principals also carry PRINCIPAL. Every resource node,
# whatever its kind, carries NODE and RESOURCE.
NODE: Final = "Node"
PRINCIPAL: Final = "Principal"
RESOURCE: Final = "Resource"

# Core node kinds: fixed, the same for every cloud. Any other kind is a resource kind a cloud adapter owns.
CORE_KINDS: Final[dict[str, str]] = {
    "user": "User",
    "group": "Group",
    "role": "Role",
    "workload": "Workload",
    "workflow": "Workflow",
    "action": "Action",
    "entry": "Entry",
    "req": "Requirement",
    "finding": "Finding",
}
PRINCIPAL_KINDS: Final = ("user", "group", "role", "workload", "workflow", "entry")
INTERNET: Final = "entry:internet"

# What a resource holds, whatever the cloud calls it. The engine reasons on category, never on kind.
RESOURCE_CATEGORIES: Final = ("object_store", "secret", "database", "table")

# Edge types. Paths walk TRAVERSE edges and end on GRANT edges; nothing else is traversed.
TRAVERSE: Final = ("MEMBER_OF", "CAN_ASSUME", "TRUSTS", "RUNS_AS")
GRANT: Final = ("CAN", "UNLOCKS")
PATH_TYPES: Final = TRAVERSE + GRANT
EDGE_TYPES: Final = (
    *PATH_TYPES,
    "USES",
    "CALLS",
    "REQUESTS",
    "HAS_ENV",
    "FOR",
    "NEEDS",
    "AFFECTS",
)
# Written by the engine before each max-flow call (Q_SET_FLOW); never shown and never evidence.
FLOW: Final = "FLOW"

EDGE_KINDS: Final = ("configured", "inferred", "assumed", "unknown")
ACCESS: Final = ("read", "write", "assume")
SENSITIVITY: Final = ("public", "internal", "confidential", "regulated")
SENSITIVE: Final = ("confidential", "regulated")

# Capacities and limits (04-engine.md sections 9 and 12).
BIG: Final = 1_000_000
USED: Final = 1_000
MAX_PATH_EDGES: Final = 7

# Candidate IDs (04-engine.md section 15): one letter per rule and for the LLM, then H1, H2, ... for fixes
# people propose, numbered in the order they arrive.
CANDIDATE_IDS: Final = ("A", "B", "C", "D", "S", "K", "U")
_HUMAN_ID = re.compile(r"^H[1-9][0-9]*$")

_KIND = re.compile(r"^[a-z][a-z0-9-]*$")


def node_id(kind: str, name: str) -> str:
    """`<kind>:<name>`, such as `role:prod-support`."""
    _check(kind, name)
    return f"{kind}:{name}"


def location_id(scheme: str, path: str) -> str:
    """`<scheme>://<path>`, for a resource that is a location inside a store, such as a prefix in a bucket."""
    _check(scheme, path)
    return f"{scheme}://{path}"


def parse_id(node: str) -> tuple[str, str]:
    """(kind, name) for either ID form; the inverse of node_id and location_id."""
    kind, sep, rest = node.partition(":")
    if sep and rest.startswith("//"):
        rest = rest[2:]
    if not sep or not _KIND.match(kind) or not rest:
        raise GraphError(f"not a node ID: {node!r}")
    return kind, rest


def is_candidate_id(candidate: str) -> bool:
    """Whether `candidate` is a fixed candidate ID or a person's (`H1`, `H2`, ...)."""
    return candidate in CANDIDATE_IDS or bool(_HUMAN_ID.match(candidate))


def human_candidate_id(n: int) -> str:
    """The ID of the n-th fix people proposed on a PR, from 1."""
    if n < 1:
        raise GraphError(f"human candidates are numbered from 1, got {n}")
    return f"H{n}"


def labels_for(kind: str) -> list[str]:
    """The labels a node of this kind carries, `Node` first. A kind that is not core is a resource."""
    if not _KIND.match(kind):
        raise GraphError(f"not a node kind: {kind!r}")
    if kind not in CORE_KINDS:
        return [NODE, RESOURCE]
    extra = [PRINCIPAL] if kind in PRINCIPAL_KINDS else []
    return [NODE, *extra, CORE_KINDS[kind]]


def _check(kind: str, name: str) -> None:
    if not _KIND.match(kind):
        raise GraphError(f"not a node kind: {kind!r}")
    if not name:
        raise GraphError(f"empty name for a {kind} node")
