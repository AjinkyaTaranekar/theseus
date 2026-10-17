"""The AWS patch-op catalog (docs/spec/04-engine.md section 13): each op's typed arguments.

A PatchOp is the neutral envelope {provider, op, args}. This module checks an AWS envelope against the catalog
and publishes the catalog's JSON schema for the LLM's fix tool. Applying ops is task E5 (`patch.py`).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, ValidationError

from theseus.adapters.aws.kinds import PROVIDER
from theseus.contracts.result import Contract, PatchOp
from theseus.errors import PatchError


class Condition(Contract):
    """One IAM condition: an operator, a key and a value or list of values."""

    op: str
    key: str
    value: str | list[str]


# Field descriptions go into ops_schema(), the only guide the LLM's fix tool has: some fields take a bare
# name, others a node ID, and a fix the model cannot write correctly is simply invalid. The examples are
# not the demo world's names, so they suggest none.
_USER = "The user's name alone, such as jane; not a node ID or an ARN."
_GROUP = "The group's name alone, such as developers; not a node ID or an ARN."
_ADDRESS = "The policy resource's address, such as aws_iam_role_policy.app_read."
_SID = "The statement's Sid."
_ARNS = "Exact ARNs."


class Statement(Contract):
    sid: str = Field(description="A Sid for the statement, unique in its policy.")
    effect: Literal["Allow", "Deny"]
    actions: list[str] = Field(description="IAM actions, such as s3:GetObject.")
    resources: list[str] = Field(description=_ARNS)
    condition: Condition | None = None


class RemoveMembership(Contract):
    user: str = Field(description=_USER)
    group: str = Field(description=_GROUP)


class AddMembership(Contract):
    user: str = Field(description=_USER)
    group: str = Field(description=_GROUP)


class RemoveStatement(Contract):
    """Removes the statement with that Sid from an inline policy or an aws_iam_policy."""

    policy_address: str = Field(description=_ADDRESS)
    sid: str = Field(description=_SID)


class SetStatementResources(Contract):
    policy_address: str = Field(description=_ADDRESS)
    sid: str = Field(description=_SID)
    resources: list[str] = Field(description=_ARNS)


class AddPolicy(Contract):
    """Adds an inline policy to a principal (`user:`, `group:` or `role:` ID)."""

    principal: str = Field(description="The principal's node ID: user:<name>, group:<name> or role:<name>.")
    statements: list[Statement]


class AddRole(Contract):
    """Adds a role trusted only by these principals, with an inline policy."""

    name: str = Field(description="The new role's name, unused by any other role.")
    trust_principals: list[str] = Field(
        description="Node IDs of the principals the role trusts: user:<name> or role:<name>, not ARNs."
    )
    statements: list[Statement]


class SetOidcSub(Contract):
    """Replaces the role's OIDC `sub` condition with StringLike on these patterns."""

    role: str = Field(description="The role's name alone, such as deploy.")
    patterns: list[str] = Field(description="OIDC sub patterns, such as repo:org/app:ref:refs/heads/main.")


OPS: dict[str, type[Contract]] = {
    "remove_membership": RemoveMembership,
    "add_membership": AddMembership,
    "remove_statement": RemoveStatement,
    "set_statement_resources": SetStatementResources,
    "add_policy": AddPolicy,
    "add_role": AddRole,
    "set_oidc_sub": SetOidcSub,
}


def make(op: str, args: Contract) -> PatchOp:
    """The envelope for one AWS op."""
    if OPS.get(op) is not type(args):
        raise PatchError(f"{op!r} does not take {type(args).__name__}")
    return PatchOp(provider=PROVIDER, op=op, args=args.model_dump(exclude_none=True))


def parse(op: PatchOp) -> Contract:
    """The op's typed arguments. Raises PatchError for another provider, an unknown op or bad arguments."""
    if op.provider != PROVIDER:
        raise PatchError(f"not an {PROVIDER} op: provider {op.provider!r}")
    model = OPS.get(op.op)
    if model is None:
        raise PatchError(f"unknown {PROVIDER} op {op.op!r}; known: {', '.join(sorted(OPS))}")
    try:
        return model.model_validate(op.args)
    except ValidationError as e:
        raise PatchError(f"bad arguments for {op.op}: {e.errors(include_url=False)}") from e


def ops_schema() -> dict[str, Any]:
    """JSON schema of one AWS op envelope: one branch per op, for the LLM's fix tool."""
    branches = [
        {
            "type": "object",
            "properties": {
                "provider": {"const": PROVIDER},
                "op": {"const": name},
                "args": model.model_json_schema(),
            },
            "required": ["provider", "op", "args"],
            "additionalProperties": False,
        }
        for name, model in sorted(OPS.items())
    ]
    return {"oneOf": branches}
