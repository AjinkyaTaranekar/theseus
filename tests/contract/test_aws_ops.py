from __future__ import annotations

import pytest

from theseus.adapters.aws import kinds, ops
from theseus.contracts.result import PatchOp
from theseus.contracts.schema import RESOURCE_CATEGORIES, parse_id
from theseus.errors import PatchError


def test_every_aws_kind_maps_to_a_neutral_category() -> None:
    assert set(kinds.RESOURCE_KINDS.values()) <= set(RESOURCE_CATEGORIES)


def test_modeled_types_are_the_twenty_in_spec_04() -> None:
    assert len(kinds.MODELED_TYPES) == 20
    assert "aws_ecs_service" in kinds.MODELED_TYPES
    assert "aws_sqs_queue" not in kinds.MODELED_TYPES


def test_s3_ids_are_locations() -> None:
    assert kinds.s3_id("demo-company-files", "invoices/") == "s3://demo-company-files/invoices/"
    assert kinds.s3_id("demo-public-site") == "s3://demo-public-site/"
    assert parse_id(kinds.s3_id("b", "p/")) == ("s3", "b/p/")


def test_an_op_round_trips_through_the_envelope() -> None:
    args = ops.AddRole(
        name="intern-onboarding",
        trust_principals=["user:priya-intern"],
        statements=[
            ops.Statement(
                sid="ReadLogs", effect="Allow", actions=["s3:GetObject"], resources=["arn:aws:s3:::l/*"]
            )
        ],
    )
    envelope = ops.make("add_role", args)
    assert envelope.provider == "aws"
    assert PatchOp.model_validate_json(envelope.model_dump_json()) == envelope
    assert ops.parse(envelope) == args


@pytest.mark.parametrize(
    "envelope",
    [
        PatchOp(provider="gcp", op="remove_membership", args={"user": "a", "group": "b"}),
        PatchOp(provider="aws", op="delete_everything"),
        PatchOp(provider="aws", op="remove_membership", args={"user": "a"}),
        PatchOp(provider="aws", op="remove_membership", args={"user": "a", "group": "b", "extra": 1}),
    ],
)
def test_parse_rejects_what_the_catalog_does_not_allow(envelope: PatchOp) -> None:
    with pytest.raises(PatchError):
        ops.parse(envelope)


def test_make_checks_the_arguments_fit_the_op() -> None:
    with pytest.raises(PatchError):
        ops.make("remove_statement", ops.RemoveMembership(user="a", group="b"))


def test_the_schema_has_one_branch_per_op() -> None:
    branches = ops.ops_schema()["oneOf"]
    assert sorted(b["properties"]["op"]["const"] for b in branches) == sorted(ops.OPS)
    assert all(b["properties"]["provider"]["const"] == "aws" for b in branches)
