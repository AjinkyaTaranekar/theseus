"""A principal's statements (04-engine.md section 5): inline policies, attached customer-managed policies, the
AWS-managed table, and an unknown policy for any attachment that cannot be resolved."""

from __future__ import annotations

import logging
from typing import Any

from theseus.adapters.aws.iam import PolicyStatement, statements, unknown_policy
from theseus.adapters.aws.managed import AWS_MANAGED
from theseus.contracts.adapters import IacResource, Locate
from theseus.contracts.result import Evidence

log = logging.getLogger(__name__)

INLINE = {"user": "aws_iam_user_policy", "group": "aws_iam_group_policy", "role": "aws_iam_role_policy"}
ATTACHMENT = {
    "user": "aws_iam_user_policy_attachment",
    "group": "aws_iam_group_policy_attachment",
    "role": "aws_iam_role_policy_attachment",
}


def iam_name(value: Any) -> str | None:
    """A user, group or role name from a value that holds either the name or the ARN."""
    if value is None:
        return None
    return str(value).rsplit("/", 1)[-1]


def policy_arn(policy: IacResource, account: str) -> str | None:
    """The ARN of a customer-managed policy: its own, or the canonical one built from its path and name."""
    if policy.values.get("arn"):
        return str(policy.values["arn"])
    name = policy.values.get("name")
    if not name:
        return None
    path = str(policy.values.get("path") or "/")
    path = "/" + path.strip("/") + "/" if path.strip("/") else "/"
    return f"arn:aws:iam::{account}:policy{path}{name}"


def _with_evidence(
    stmts: list[PolicyStatement], address: str, locate: Locate, note: str | None
) -> list[tuple[PolicyStatement, Evidence]]:
    out = []
    for s in stmts:
        ev = locate(address, s.sid)
        out.append((s, ev.model_copy(update={"note": note}) if note else ev))
    return out


def statements_for(
    kind: str, name: str, resources: list[IacResource], account: str, locate: Locate
) -> list[tuple[PolicyStatement, Evidence]]:
    """Every statement that applies to the user, group or role `name`, with its evidence, in address order.

    The importer has already resolved a `policy_arn` that was unknown until apply (04-engine.md section 2);
    one still missing here is an unknown policy.
    """
    by_arn = {arn: r for r in resources if r.type == "aws_iam_policy" and (arn := policy_arn(r, account))}
    out: list[tuple[PolicyStatement, Evidence]] = []
    for r in sorted(resources, key=lambda r: r.address):
        if iam_name(r.values.get(kind)) != name:
            continue
        if r.type == INLINE[kind]:
            policy = r.values.get("policy")
            note = None if policy is not None else "policy unknown until apply"
            out += _with_evidence(statements(policy), r.address, locate, note)
        elif r.type == ATTACHMENT[kind]:
            arn = r.values.get("policy_arn")
            if arn in by_arn:
                target = by_arn[arn]
                policy = target.values.get("policy")
                note = f"attached by {r.address}" + (
                    "" if policy is not None else "; policy unknown until apply"
                )
                out += _with_evidence(statements(policy), target.address, locate, note)
            elif arn in AWS_MANAGED:
                managed_name = str(arn).rsplit("/", 1)[-1]
                out += _with_evidence(AWS_MANAGED[arn], r.address, locate, f"AWS-managed {managed_name}")
            else:
                log.info(
                    "%s attaches %s, which is neither in the plan nor in the managed table", r.address, arn
                )
                note = f"unknown policy {arn}" if arn else "unknown policy: policy_arn unknown until apply"
                out += _with_evidence(unknown_policy(), r.address, locate, note)
    return out
