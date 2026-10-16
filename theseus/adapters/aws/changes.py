"""AWS catalog operations for evidenced changes to the neutral graph."""

from __future__ import annotations

import hashlib
import json
import logging

from theseus.adapters.aws.catalog import load_catalog
from theseus.adapters.aws.iam import PolicyStatement, statements
from theseus.adapters.aws.ops import (
    AddPolicy,
    Condition,
    RemoveMembership,
    RemoveStatement,
    SetOidcSub,
    SetStatementResources,
    Statement,
    make,
)
from theseus.adapters.aws.patch import POLICIES
from theseus.contracts.adapters import Change, IacResource
from theseus.contracts.result import EdgeRow, GraphRows, NodeRow, PatchOp
from theseus.contracts.schema import RESOURCE, parse_id
from theseus.errors import IngestError, PatchError

log = logging.getLogger(__name__)


def _policy_statements(
    edge: EdgeRow, resources: list[IacResource]
) -> list[tuple[IacResource, PolicyStatement]]:
    by_address = {resource.address: resource for resource in resources}
    if len(by_address) != len(resources):
        raise PatchError("change translation requires unique resource addresses")
    found: dict[tuple[str, str], tuple[IacResource, PolicyStatement]] = {}
    for evidence in edge.evidence:
        resource = by_address.get(evidence.address)
        if (
            resource is None
            or resource.provider != "aws"
            or resource.type not in POLICIES
            or not evidence.part
        ):
            continue
        try:
            matches = [
                statement
                for statement in statements(resource.values.get("policy"))
                if statement.sid == evidence.part
            ]
        except IngestError as exc:
            raise PatchError(f"cannot translate unreadable policy {resource.address}") from exc
        if len(matches) != 1 or matches[0].effect != "Allow":
            continue
        found[(resource.address, evidence.part)] = (resource, matches[0])
    return [found[key] for key in sorted(found)]


def _node(nodes: dict[str, NodeRow], identifier: str) -> NodeRow:
    if identifier not in nodes:
        raise PatchError(f"change names a node outside this graph: {identifier!r}")
    return nodes[identifier]


def _scope(node: NodeRow, resources: list[IacResource]) -> list[str]:
    arn = node.props.get("arn_pattern")
    if RESOURCE not in node.labels or not isinstance(arn, str) or not arn.startswith("arn:"):
        return []
    kind, name = parse_id(node.id)
    entry = load_catalog().by_kind.get(kind)
    if entry is None:
        return []
    if entry.per == "location":
        bucket, _, prefix = name.partition("/")
        if entry.service != "s3" or ":::" not in arn or not bucket:
            return []
        return [arn.split(":::", 1)[0] + ":::" + bucket + "/" + prefix + "*"]
    if entry.type == "aws_secretsmanager_secret":
        declared = [r for r in resources if r.address == node.props.get("address")]
        if len(declared) != 1:
            return []
        actual = declared[0].values.get("arn")
        if isinstance(actual, str) and actual:
            return [actual]
        if ":secret:" not in arn:
            return []
        return [arn.partition(":secret:")[0] + ":secret:" + node.name + "-*"]
    return [arn]


def _narrow(
    change: Change,
    edge: EdgeRow,
    rows: GraphRows,
    resources: list[IacResource],
    nodes: dict[str, NodeRow],
) -> list[PatchOp]:
    if edge.type != "CAN":
        return []
    targets = [_node(nodes, identifier) for identifier in sorted(set(change.values))]
    policies = _policy_statements(edge, resources)
    if not policies:
        return []
    result: list[PatchOp] = []
    for policy, statement in policies:
        retained: set[str] = set()
        for target in targets:
            # A narrow operation may retain grants from this statement; it cannot create a new grant.
            covered = any(
                candidate.type == "CAN"
                and candidate.src == edge.src
                and candidate.dst == target.id
                and any(
                    ev.address == policy.address and ev.part == statement.sid for ev in candidate.evidence
                )
                for candidate in rows.edges
            )
            if not covered:
                continue
            scope = _scope(target, resources)
            if not scope:
                return []
            retained.update(scope)
        if retained:
            result.append(
                make(
                    "set_statement_resources",
                    SetStatementResources(
                        policy_address=policy.address,
                        sid=statement.sid,
                        resources=sorted(retained),
                    ),
                )
            )
        else:
            return []
    return result


def _deny(
    change: Change, edge: EdgeRow, resources: list[IacResource], nodes: dict[str, NodeRow]
) -> list[PatchOp]:
    if edge.type != "CAN":
        return []
    owner = _node(nodes, edge.src)
    if not {"User", "Group", "Role"}.intersection(owner.labels):
        return []
    target = _node(nodes, edge.dst)
    kind, _ = parse_id(target.id)
    entry = load_catalog().by_kind.get(kind)
    if entry is None:
        return []
    arns = []
    for identifier in sorted(set(change.values)):
        principal = _node(nodes, identifier)
        arn = principal.props.get("arn")
        if (
            not {"User", "Role"}.intersection(principal.labels)
            or not isinstance(arn, str)
            or not arn.startswith("arn:")
        ):
            return []
        arns.append(arn)
    actions = sorted({action.action for action in entry.actions() if action.access in edge.grants})
    scope = _scope(target, resources)
    if not actions or not scope:
        return []
    payload = json.dumps([edge.src, edge.dst, sorted(arns)], separators=(",", ":"))
    sid = "DenyPrincipal" + hashlib.sha256(payload.encode()).hexdigest()[:12]
    return [
        make(
            "add_policy",
            AddPolicy(
                principal=edge.src,
                statements=[
                    Statement(
                        sid=sid,
                        effect="Deny",
                        actions=actions,
                        resources=scope,
                        condition=Condition(op="StringEquals", key="aws:PrincipalArn", value=sorted(arns)),
                    )
                ],
            ),
        )
    ]


def ops_for(
    change: Change,
    rows: GraphRows,
    resources: list[IacResource],
    *,
    base_resources: list[IacResource] | None = None,
) -> list[PatchOp]:
    """Sorted catalog operations for the evidenced change, or no operations when it cannot be expressed.

    Missing graph IDs and empty restrictions raise PatchError; no statement name or target ARN is guessed.
    """
    matches = [edge for edge in rows.edges if edge.eid == change.eid]
    if len(matches) != 1:
        raise PatchError(f"change edge ID must identify exactly one edge: {change.eid!r}")
    if change.kind != "remove_edge" and (not change.values or any(not value for value in change.values)):
        raise PatchError("a restriction or deny must name nonempty retained values")
    edge = matches[0]
    if change.evidence:
        selected = {(ev.address, ev.part) for ev in change.evidence}
        actual = {(ev.address, ev.part) for ev in edge.evidence}
        if not selected <= actual:
            raise PatchError("change evidence is not carried by the edge")
        edge = edge.model_copy(
            update={"evidence": [ev for ev in edge.evidence if (ev.address, ev.part) in selected]}
        )
    nodes = {node.id: node for node in rows.nodes}
    result: list[PatchOp] = []
    if change.added_only:
        if change.kind != "remove_edge" or edge.type not in {"CAN", "CAN_ASSUME"} or not change.evidence:
            raise PatchError("added-only removal requires selected grant evidence")
        if base_resources is None:
            log.info("no base resources supplied to verify an added statement")
            return []
        before = {resource.address: resource for resource in base_resources}
        selected = _policy_statements(edge, resources)
        for resource, statement in selected:
            original = before.get(resource.address)
            if original is None:
                continue
            try:
                existed = any(old.sid == statement.sid for old in statements(original.values.get("policy")))
            except IngestError as exc:
                raise PatchError(f"cannot verify base policy {original.address}") from exc
            if existed:
                log.info("statement %s in %s already existed; no revert", statement.sid, resource.address)
                return []
    if change.kind == "remove_edge":
        if edge.type == "MEMBER_OF":
            user, group = _node(nodes, edge.src), _node(nodes, edge.dst)
            if "User" in user.labels and "Group" in group.labels:
                result = [make("remove_membership", RemoveMembership(user=user.name, group=group.name))]
        elif edge.type in {"CAN", "CAN_ASSUME"}:
            result = [
                make("remove_statement", RemoveStatement(policy_address=resource.address, sid=statement.sid))
                for resource, statement in _policy_statements(edge, resources)
            ]
    elif change.kind == "narrow_grant":
        result = _narrow(change, edge, rows, resources, nodes)
    elif change.kind == "restrict_trust" and edge.type == "TRUSTS":
        role = _node(nodes, edge.dst)
        if "Role" in role.labels:
            result = [make("set_oidc_sub", SetOidcSub(role=role.name, patterns=sorted(set(change.values))))]
    elif change.kind == "deny_principal":
        result = _deny(change, edge, resources, nodes)
    if not result:
        log.info("no catalog operation expresses %s on %s", change.kind, change.eid)
    return sorted(result, key=lambda operation: operation.model_dump_json())
