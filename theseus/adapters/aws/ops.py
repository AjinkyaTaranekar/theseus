"""The AWS patch-op catalog (docs/spec/04-engine.md section 13): each op's typed arguments.

A PatchOp is the neutral envelope {provider, op, args}. This module checks an AWS envelope against the catalog
and publishes the catalog's JSON schema for the LLM's fix tool. Applying ops is task E5 (`patch.py`).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ValidationError

from theseus.adapters.aws.kinds import PROVIDER
from theseus.contracts.result import Contract, PatchOp
from theseus.errors import PatchError


class Condition(Contract):
    """One IAM condition: an operator, a key and a value or list of values."""

    op: str
    key: str
    value: str | list[str]


class Statement(Contract):
    sid: str
    effect: Literal["Allow", "Deny"]
    actions: list[str]
    resources: list[str]
    condition: Condition | None = None


class RemoveMembership(Contract):
    user: str
    group: str


class AddMembership(Contract):
    user: str
    group: str


class RemoveStatement(Contract):
    """Removes the statement with that Sid from an inline policy or an aws_iam_policy."""

    policy_address: str
    sid: str


class SetStatementResources(Contract):
    policy_address: str
    sid: str
    resources: list[str]


class AddPolicy(Contract):
    """Adds an inline policy to a principal (`user:`, `group:` or `role:` ID)."""

    principal: str
    statements: list[Statement]


class AddRole(Contract):
    """Adds a role trusting those principals' exact ARNs, with an inline policy."""

    name: str
    trust_principals: list[str]
    statements: list[Statement]


class SetOidcSub(Contract):
    """Replaces the role's OIDC `sub` condition with StringLike on these patterns."""

    role: str
    patterns: list[str]


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
