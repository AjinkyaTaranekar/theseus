"""The evidence checker (docs/spec/06-agent.md, "The evidence checker"): a rationale may cite only evidence
and nodes that exist."""

from __future__ import annotations

from theseus.agent.evidence import check, evidence_refs, node_refs

EVIDENCE = {"E1", "E2", "E12"}
NODES = {
    "user:priya-intern",
    "group:support-engineers",
    "role:prod-support",
    "s3://demo-app-logs/",
    "db:customer-db",
    "dynamodb:demo-orders",
}


def test_a_rationale_that_cites_what_exists_has_no_bad_references() -> None:
    rationale = (
        "Removing user:priya-intern from group:support-engineers (E1) closes the paths to db:customer-db. "
        "A new role reads s3://demo-app-logs/ only (E12)."
    )
    assert check(rationale, EVIDENCE, NODES) == []


def test_a_made_up_evidence_id_is_a_bad_reference() -> None:
    assert check("The membership (E1) and the grant (E99) open it.", EVIDENCE, NODES) == ["E99"]


def test_a_made_up_node_of_a_kind_the_graph_has_is_a_bad_reference() -> None:
    assert check("Use role:intern-readonly instead of role:prod-support.", EVIDENCE, NODES) == [
        "role:intern-readonly"
    ]
    assert check("Read s3://demo-invented/ instead (E2).", EVIDENCE, NODES) == ["s3://demo-invented/"]


def test_words_of_kinds_the_graph_does_not_have_are_not_node_mentions() -> None:
    """An action or an ARN looks like `kind:name`, but no node has its kind, so it claims no node."""
    rationale = (
        "Grant s3:GetObject and sts:AssumeRole on arn:aws:s3:::demo-app-logs/* (E2). Note: least privilege."
    )
    assert check(rationale, EVIDENCE, NODES) == []


def test_strings_the_fix_itself_contains_are_quotes_not_node_mentions() -> None:
    """`dynamodb:GetItem` has a node kind, but quoting the fix's own action is not a claim about the graph."""
    assert check("It keeps dynamodb:GetItem (E1).", EVIDENCE, NODES) == ["dynamodb:GetItem"]
    assert check("It keeps dynamodb:GetItem (E1).", EVIDENCE, NODES, quoted={"dynamodb:GetItem"}) == []


def test_punctuation_around_a_reference_is_not_part_of_it() -> None:
    rationale = (
        "See `role:prod-support`, (user:priya-intern); and s3://demo-app-logs/. "
        "Also role:prod-support's trust."
    )
    assert check(rationale, EVIDENCE, NODES) == []


def test_bad_references_are_sorted_and_unique() -> None:
    rationale = "E7 and E3 and E7; role:b, role:a and role:b."
    assert check(rationale, EVIDENCE, NODES) == ["E3", "E7", "role:a", "role:b"]


def test_only_whole_evidence_ids_are_read() -> None:
    assert evidence_refs("E3, E12; SE4 and E5x are not IDs; (E1)") == ["E1", "E12", "E3"]


def test_node_mentions_are_read_by_the_graph_s_own_kinds_and_schemes() -> None:
    text = "user:priya-intern s3://demo-app-logs/ s3:GetObject https://example.com db:customer-db."
    assert node_refs(text, NODES) == ["db:customer-db", "s3://demo-app-logs/", "user:priya-intern"]


def test_an_empty_rationale_has_nothing_to_check() -> None:
    assert check("", EVIDENCE, NODES) == []
