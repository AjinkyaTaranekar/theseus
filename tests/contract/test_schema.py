from __future__ import annotations

import pytest

from theseus.contracts import schema
from theseus.errors import GraphError


@pytest.mark.parametrize(
    ("kind", "name", "node"),
    [
        ("user", "priya-intern", "user:priya-intern"),
        ("group", "support-engineers", "group:support-engineers"),
        ("role", "prod-support", "role:prod-support"),
        ("workload", "billing-api", "workload:billing-api"),
        ("workflow", "demo-org/docs-site/preview.yml", "workflow:demo-org/docs-site/preview.yml"),
        ("action", "demo-thirdparty/file-diff", "action:demo-thirdparty/file-diff"),
        ("entry", "internet", "entry:internet"),
        ("secret", "prod-db-credentials", "secret:prod-db-credentials"),
        ("req", "R1", "req:R1"),
        ("finding", "GHSA-demo-0001", "finding:GHSA-demo-0001"),
    ],
)
def test_node_ids_follow_the_grammar(kind: str, name: str, node: str) -> None:
    assert schema.node_id(kind, name) == node
    assert schema.parse_id(node) == (kind, name)


@pytest.mark.parametrize(
    ("scheme", "path", "node"),
    [
        ("s3", "demo-company-files/invoices/", "s3://demo-company-files/invoices/"),
        ("s3", "demo-public-site/", "s3://demo-public-site/"),
        ("gcs", "bucket/prefix/", "gcs://bucket/prefix/"),
    ],
)
def test_location_ids_follow_the_grammar(scheme: str, path: str, node: str) -> None:
    assert schema.location_id(scheme, path) == node
    assert schema.parse_id(node) == (scheme, path)


def test_a_new_cloud_needs_no_contract_change_for_its_kinds() -> None:
    assert schema.parse_id("gcp-secret:db-password") == ("gcp-secret", "db-password")
    assert schema.labels_for("gcp-secret") == ["Node", "Resource"]
    assert schema.labels_for("gcp-secret", "Secret") == ["Node", "Resource", "Secret"]


@pytest.mark.parametrize("bad", ["", "nobody", "Role:x", "user:", "s3://", ":x", "1st:x"])
def test_parse_id_rejects_what_the_grammar_does_not_allow(bad: str) -> None:
    with pytest.raises(GraphError):
        schema.parse_id(bad)


def test_node_id_rejects_a_bad_kind_or_an_empty_name() -> None:
    with pytest.raises(GraphError):
        schema.node_id("Role", "x")
    with pytest.raises(GraphError):
        schema.node_id("user", "")


def test_path_edges_are_traversal_then_grant() -> None:
    assert schema.TRAVERSE == ("MEMBER_OF", "CAN_ASSUME", "TRUSTS", "RUNS_AS")
    assert schema.GRANT == ("CAN", "UNLOCKS")
    assert schema.PATH_TYPES == schema.TRAVERSE + schema.GRANT
    assert set(schema.PATH_TYPES) <= set(schema.EDGE_TYPES)
    assert schema.FLOW not in schema.EDGE_TYPES


def test_core_kinds_carry_their_labels() -> None:
    assert schema.labels_for("role") == ["Node", "Principal", "Role", "PermissionRole"]
    assert schema.labels_for("user") == ["Node", "Principal", "User", "UserAccount"]
    assert schema.labels_for("workload", "Function") == ["Node", "Principal", "Workload", "Function"]
    assert schema.labels_for("workflow") == ["Node", "Principal", "Workflow"]
    assert schema.labels_for("entry") == ["Node", "Principal", "Entry"]
    assert schema.labels_for("action") == ["Node", "Action"]
    assert schema.labels_for("req") == ["Node", "Requirement"]
    assert set(schema.PRINCIPAL_KINDS) <= set(schema.CORE_KINDS)


def test_constants_match_the_spec() -> None:
    assert (schema.BIG, schema.USED, schema.MAX_PATH_EDGES) == (1_000_000, 1_000, 7)
    assert schema.CANDIDATE_IDS == ("A", "B", "C", "D", "S", "K", "U")
    assert schema.CARTOGRAPHY_CATEGORIES == (
        "ObjectStorage",
        "FileStorage",
        "BlockStorage",
        "Database",
        "Secret",
        "EncryptionKey",
        "AIModel",
    )
    assert schema.RESOURCE_CATEGORIES[len(schema.CARTOGRAPHY_CATEGORIES) :] == (
        "LogStore",
        "MessageQueue",
        "MessageTopic",
        "DataStream",
    )


@pytest.mark.parametrize(
    ("candidate", "ok"),
    [("A", True), ("U", True), ("H1", True), ("H12", True), ("H0", False), ("Z", False), ("h1", False)],
)
def test_candidate_ids_are_fixed_letters_or_numbered_human_fixes(candidate: str, ok: bool) -> None:
    assert schema.is_candidate_id(candidate) is ok


def test_human_candidates_are_numbered_from_one() -> None:
    assert schema.human_candidate_id(1) == "H1"
    with pytest.raises(GraphError):
        schema.human_candidate_id(0)


@pytest.mark.parametrize(
    ("kind", "label"), [("gcp-secret", "Function"), ("workload", "Secret"), ("role", "Function")]
)
def test_an_ontology_label_must_fit_the_kind(kind: str, label: str) -> None:
    with pytest.raises(GraphError):
        schema.labels_for(kind, label)
