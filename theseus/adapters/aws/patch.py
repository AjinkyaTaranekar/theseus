"""Pure application of the AWS operation catalog to independent IaC resource copies."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from theseus.adapters.aws import ops as catalog
from theseus.adapters.aws.policies import INLINE, iam_name
from theseus.contracts.adapters import IacResource
from theseus.contracts.result import PatchOp
from theseus.errors import PatchError

log = logging.getLogger(__name__)

IAM_NAME = re.compile(r"[A-Za-z0-9_+=,.@-]{1,128}")
POLICIES = frozenset({*INLINE.values(), "aws_iam_policy", "aws_s3_bucket_policy"})
SUB = "token.actions.githubusercontent.com:sub"
PROVIDER = "token.actions.githubusercontent.com"


def _name(value: str) -> str:
    if not IAM_NAME.fullmatch(value):
        raise PatchError(f"invalid IAM name {value!r}")
    return value


def _strings(values: list[str], field: str) -> list[str]:
    if not values or any(not value.strip() for value in values):
        raise PatchError(f"{field} must contain nonempty strings")
    return sorted(set(values))


def _principal(resources: list[IacResource], identifier: str, kinds: tuple[str, ...]) -> IacResource:
    kind, sep, name = identifier.partition(":")
    if not sep or kind not in kinds:
        raise PatchError(f"unsupported principal {identifier!r}; expected {', '.join(kinds)}")
    _name(name)
    found = [r for r in resources if r.type == f"aws_iam_{kind}" and r.values.get("name") == name]
    if len(found) != 1 or found[0].provider != "aws":
        raise PatchError(f"principal {identifier!r} must have exactly one declared resource")
    return found[0]


def _at(resources: list[IacResource], address: str, types: frozenset[str]) -> IacResource:
    found = [r for r in resources if r.address == address]
    if len(found) != 1 or found[0].provider != "aws" or found[0].type not in types:
        raise PatchError(f"{address!r} is not a declared editable resource")
    return found[0]


def _document(resource: IacResource, field: str) -> dict[str, Any]:
    raw = resource.values.get(field)
    try:
        doc = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise PatchError(f"{resource.address}: {field} is not valid JSON") from exc
    if not isinstance(doc, dict):
        raise PatchError(f"{resource.address}: {field} must be a policy object")
    statements = doc.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list) or any(not isinstance(s, dict) for s in statements):
        raise PatchError(f"{resource.address}: policy Statement must be an object or list of objects")
    return {**doc, "Statement": statements}


def _write(resource: IacResource, field: str, doc: dict[str, Any]) -> None:
    resource.values[field] = (
        json.dumps(doc, sort_keys=True, separators=(",", ":"))
        if isinstance(resource.values.get(field), str)
        else doc
    )


def _statement(doc: dict[str, Any], sid: str) -> dict[str, Any]:
    matches = [s for s in doc["Statement"] if s.get("Sid") == sid]
    if not sid or len(matches) != 1:
        raise PatchError(f"Sid {sid!r} must match exactly one statement")
    return matches[0]


def _policy(statements: list[catalog.Statement]) -> str:
    if not statements or len({s.sid for s in statements}) != len(statements):
        raise PatchError("new policies need statements with unique, nonempty Sids")
    result: list[dict[str, Any]] = []
    for statement in sorted(statements, key=lambda s: s.sid):
        if not statement.sid.strip():
            raise PatchError("a new statement needs a nonempty Sid")
        row: dict[str, Any] = {
            "Sid": statement.sid,
            "Effect": statement.effect,
            "Action": _strings(statement.actions, "actions"),
            "Resource": _strings(statement.resources, "resources"),
        }
        condition = statement.condition
        if condition is not None:
            value = condition.value
            if not condition.op.strip() or not condition.key.strip():
                raise PatchError("condition operator and key must be nonempty")
            if isinstance(value, list):
                value = _strings(value, "condition values")
            elif not value.strip():
                raise PatchError("condition value must be nonempty")
            row["Condition"] = {condition.op: {condition.key: value}}
        result.append(row)
    return json.dumps({"Version": "2012-10-17", "Statement": result}, sort_keys=True, separators=(",", ":"))


def _append(resources: list[IacResource], kind: str, label: str, values: dict[str, Any]) -> None:
    address = f"{kind}.{label}"
    if any(r.address == address for r in resources):
        raise PatchError(f"generated resource {address} already exists")
    resources.append(IacResource(address=address, type=kind, name=label, provider="aws", values=values))


# Lists whose order means nothing: the Terraform renderer sorts and dedups them before it names a resource.
_SETS = ("resources", "patterns", "trust_principals")


def _label(op: PatchOp) -> str:
    """The new resource's label: a hash of the op with its unordered lists sorted, so a fix verified on the
    graph copy renders to the same Terraform address whatever order its principals came in."""
    data = op.model_dump()
    args = dict(data["args"])
    for key in _SETS:
        if isinstance(args.get(key), list):
            args[key] = sorted(set(args[key]))
    payload = json.dumps({**data, "args": args}, sort_keys=True, separators=(",", ":"))
    return "theseus_" + op.op + "_" + hashlib.sha256(payload.encode()).hexdigest()[:12]


def _memberships(resources: list[IacResource], user: str, group: str) -> list[IacResource]:
    _principal(resources, "user:" + user, ("user",))
    _principal(resources, "group:" + group, ("group",))
    found = []
    for resource in resources:
        if resource.type != "aws_iam_user_group_membership" or iam_name(resource.values.get("user")) != user:
            continue
        groups = resource.values.get("groups")
        if not isinstance(groups, list) or any(not isinstance(g, str) for g in groups):
            raise PatchError(f"{resource.address}: membership groups must be a known list of strings")
        if group in groups:
            found.append(resource)
    return found


def _trust_arn(resources: list[IacResource], identifier: str, account: str | None) -> str:
    principal = _principal(resources, identifier, ("user", "role"))
    if account is None or not re.fullmatch(r"[0-9]{12}", account):
        raise PatchError("creating a role needs an explicit 12-digit AWS account")
    if (principal.values.get("path") or "/") != "/":
        raise PatchError("role trust requires a principal with a root IAM path")
    kind, _, name = identifier.partition(":")
    arn = f"arn:aws:iam::{account}:{kind}/{name}"
    if principal.values.get("arn") not in (None, arn):
        raise PatchError(f"{identifier}: ARN disagrees with the canonical account and path")
    return arn


def _oidc(resource: IacResource, patterns: list[str]) -> None:
    patterns = _strings(patterns, "OIDC patterns")
    doc = _document(resource, "assume_role_policy")
    matched = False
    for statement in doc["Statement"]:
        actions = statement.get("Action", [])
        actions = [actions] if isinstance(actions, str) else actions
        if not isinstance(actions, list) or "sts:AssumeRoleWithWebIdentity" not in actions:
            continue
        principal = statement.get("Principal")
        federated = principal.get("Federated", []) if isinstance(principal, dict) else []
        federated = [federated] if isinstance(federated, str) else federated
        if not isinstance(federated, list):
            raise PatchError(f"{resource.address}: malformed federated principal")
        github = [isinstance(p, str) and p.endswith(":oidc-provider/" + PROVIDER) for p in federated]
        if not any(github):
            continue
        if not all(github):
            raise PatchError(f"{resource.address}: one statement mixes federated issuers")
        condition = statement.get("Condition", {})
        if not isinstance(condition, dict) or any(
            not isinstance(operator, str)
            or not isinstance(block, dict)
            or any(not isinstance(key, str) for key in block)
            for operator, block in condition.items()
        ):
            raise PatchError(f"{resource.address}: malformed OIDC condition")
        updated = {
            operator: {k: v for k, v in block.items() if k.lower() != SUB}
            for operator, block in condition.items()
        }
        updated = {operator: block for operator, block in updated.items() if block}
        updated.setdefault("StringLike", {})[SUB] = patterns
        statement["Condition"] = updated
        matched = True
    if not matched:
        raise PatchError(f"{resource.address}: no editable GitHub OIDC trust statement")
    _write(resource, "assume_role_policy", doc)


def apply_ops(
    resources: list[IacResource], ops: list[PatchOp], *, account: str | None = None
) -> list[IacResource]:
    """Independent, address-sorted patched resources; PatchError when any operation cannot apply.

    The adapter passes its configured account for canonical trust ARNs. Each envelope is validated through
    the shared catalog before mutation, and failed sequences never change the caller's resources.
    """
    if len({r.address for r in resources}) != len(resources):
        raise PatchError("resource addresses must be unique")
    parsed = [(operation, catalog.parse(operation)) for operation in ops]
    result = [r.model_copy(deep=True) for r in resources]
    for operation, args in parsed:
        if isinstance(args, catalog.RemoveMembership | catalog.AddMembership):
            found = _memberships(result, args.user, args.group)
            if isinstance(args, catalog.RemoveMembership):
                if not found:
                    raise PatchError("membership to remove does not exist")
                for membership in found:
                    membership.values["groups"] = sorted(set(membership.values["groups"]) - {args.group})
                    if not membership.values["groups"]:
                        result.remove(membership)
            else:
                if found:
                    raise PatchError("membership already exists")
                _append(
                    result,
                    "aws_iam_user_group_membership",
                    _label(operation),
                    {"user": args.user, "groups": [args.group]},
                )
        elif isinstance(args, catalog.RemoveStatement | catalog.SetStatementResources):
            target = _at(result, args.policy_address, POLICIES)
            doc = _document(target, "policy")
            statement = _statement(doc, args.sid)
            if isinstance(args, catalog.RemoveStatement):
                doc["Statement"].remove(statement)
            else:
                statement["Resource"] = _strings(args.resources, "resources")
            _write(target, "policy", doc)
        elif isinstance(args, catalog.AddPolicy):
            _principal(result, args.principal, ("user", "group", "role"))
            kind, _, name = args.principal.partition(":")
            label = _label(operation)
            _append(
                result, INLINE[kind], label, {"name": label, kind: name, "policy": _policy(args.statements)}
            )
        elif isinstance(args, catalog.AddRole):
            _name(args.name)
            if len(args.name) > 64:
                raise PatchError("role names must contain at most 64 characters")
            if any(
                r.type == "aws_iam_role"
                and isinstance(r.values.get("name"), str)
                and r.values["name"].casefold() == args.name.casefold()
                for r in result
            ):
                raise PatchError(f"role {args.name!r} already exists")
            principals = _strings(args.trust_principals, "trust principals")
            trusted = sorted({_trust_arn(result, identifier, account) for identifier in principals})
            trust = {
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Action": "sts:AssumeRole", "Principal": {"AWS": trusted}}],
            }
            policy = _policy(args.statements)
            label = _label(operation)
            _append(
                result,
                "aws_iam_role",
                label,
                {
                    "name": args.name,
                    "path": "/",
                    "assume_role_policy": json.dumps(trust, sort_keys=True, separators=(",", ":")),
                },
            )
            _append(
                result,
                "aws_iam_role_policy",
                label + "_access",
                {"name": label + "_access", "role": args.name, "policy": policy},
            )
        elif isinstance(args, catalog.SetOidcSub):
            target = _principal(result, "role:" + args.role, ("role",))
            _oidc(target, args.patterns)
    return sorted(result, key=lambda r: r.address)
