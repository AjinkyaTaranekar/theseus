"""CAN and CAN_ASSUME edges (04-engine.md section 6), from identity policies, trust policies and S3 bucket
policies. E1's AwsAdapter.rows adds them to the rows; eids are numbered there, so these carry ""."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from theseus.adapters.aws.catalog import CatalogAction, load_catalog
from theseus.adapters.aws.iam import ASSUME, Decision, PolicyStatement, evaluate, statements, trust_kind
from theseus.adapters.aws.policies import iam_name, statements_for
from theseus.contracts.adapters import IacResource, Locate
from theseus.contracts.result import EdgeRow, Evidence, NodeRow
from theseus.contracts.schema import INTERNET, parse_id
from theseus.errors import IngestError

log = logging.getLogger(__name__)

PRINCIPALS = ("user", "group", "role")
Pairs = list[tuple[PolicyStatement, Evidence]]


def _prop(node: NodeRow, key: str) -> str:
    value = node.props.get(key)
    if not value:
        raise IngestError(
            f"node {node.id} has no {key}; the AWS resource builder sets it (04-engine.md section 4)"
        )
    return str(value)


def _evidence(pairs: Pairs, chosen: Iterable[PolicyStatement]) -> list[Evidence]:
    """The evidence for the chosen statements, once each, in file and line order."""
    by_id = {id(s): e for s, e in pairs}
    seen: dict[tuple[Any, ...], Evidence] = {}
    for s in chosen:
        e = by_id[id(s)]
        seen.setdefault((e.address, e.part, e.note), e)
    return sorted(seen.values(), key=lambda e: (e.file, e.line or 0, e.address, e.part or "", e.note or ""))


def _decide(stmts: list[PolicyStatement], action: CatalogAction, node_arn: str) -> Decision:
    """The decision for one catalog action. When AWS may check more than one ARN form and the forms disagree,
    the answer is unknown."""
    decisions = [evaluate(stmts, action.action, arn) for arn in action.arns_for(node_arn)]
    if len({d.result for d in decisions}) == 1:
        return decisions[0]
    involved = [s for d in decisions for s in d.statements]
    return Decision(result="unknown", statements=[s for s in stmts if s in involved])


def _can(src: str, target: NodeRow, pairs: Pairs) -> EdgeRow | None:
    """One CAN edge from `src` to `target`, merging every catalog action that is allowed or unknown."""
    entry = load_catalog().by_kind[parse_id(target.id)[0]]
    arn = _prop(target, "arn_pattern")
    stmts = [s for s, _ in pairs]
    grants: set[str] = set()
    unknown = False
    deciding: list[PolicyStatement] = []
    for action in entry.actions():
        decision = _decide(stmts, action, arn)
        if decision.result in ("allow", "unknown"):
            grants.add(action.access)
            unknown = unknown or decision.result == "unknown"
            deciding += decision.statements
    if not grants:
        return None
    return EdgeRow(
        eid="",
        type="CAN",
        src=src,
        dst=target.id,
        kind="unknown" if unknown else "configured",
        grants=sorted(grants),
        evidence=_evidence(pairs, deciding),
    )


def _is_public(s: PolicyStatement) -> bool:
    """Whether a bucket-policy statement could apply to anyone on the internet."""
    if s.unsupported:
        return True
    principals = s.principals or {}
    return "*" in principals.get("*", []) or "*" in principals.get("AWS", [])


def _public_edges(resources: list[IacResource], targets: list[NodeRow], locate: Locate) -> list[EdgeRow]:
    """CAN from entry:internet: bucket-policy statements open to anyone, on that bucket's locations."""
    edges = []
    for bp in sorted((r for r in resources if r.type == "aws_s3_bucket_policy"), key=lambda r: r.address):
        bucket = str(bp.values.get("bucket", "")).rsplit(":::", 1)[-1]
        pairs = [(s, locate(bp.address, s.sid)) for s in statements(bp.values.get("policy")) if _is_public(s)]
        if not pairs:
            continue
        for target in targets:
            kind, name = parse_id(target.id)
            if kind == "s3" and name.startswith(f"{bucket}/"):
                edge = _can(INTERNET, target, pairs)
                if edge:
                    edges.append(edge)
    return edges


def _assume_edge(
    caller: NodeRow, role: NodeRow, caller_pairs: Pairs, trust: Pairs, account: str
) -> EdgeRow | None:
    """CAN_ASSUME from caller to role, by the rule in 04-engine.md section 6. Without a permission of its own,
    the caller gets in only through trust that names it, so that trust is the evidence."""
    caller_kind = parse_id(caller.id)[0]
    caller_arn = None if caller_kind == "group" else _prop(caller, "arn")
    d = evaluate([s for s, _ in caller_pairs], ASSUME, _prop(role, "arn"))
    t = trust_kind([s for s, _ in trust], caller_arn, account)
    if d.result == "deny" or t.kind is None or (d.result == "none" and not t.names_caller):
        return None
    unknown = d.result == "unknown" or t.kind == "unknown" or (d.result == "none" and t.kind != "explicit")
    trusting = (
        t.statements if d.result != "none" else t.naming + [s for s in t.statements if s.effect == "Deny"]
    )
    return EdgeRow(
        eid="",
        type="CAN_ASSUME",
        src=caller.id,
        dst=role.id,
        kind="unknown" if unknown else "configured",
        evidence=_evidence(caller_pairs, d.statements) + _evidence(trust, trusting),
    )


def _memberships(resources: list[IacResource]) -> dict[str, list[str]]:
    """Each user's groups, as node IDs, from `aws_iam_user_group_membership`."""
    out: dict[str, set[str]] = {}
    for r in resources:
        if r.type == "aws_iam_user_group_membership" and (user := iam_name(r.values.get("user"))):
            groups = r.values.get("groups") or []
            out.setdefault(f"user:{user}", set()).update(f"group:{iam_name(g)}" for g in groups)
    return {user: sorted(groups) for user, groups in out.items()}


def _boundaries(resources: list[IacResource], locate: Locate) -> dict[str, Evidence]:
    """Principals with a permissions boundary, which the subset does not model, and the evidence naming it."""
    out = {}
    for r in resources:
        kind = {"aws_iam_user": "user", "aws_iam_role": "role"}.get(r.type)
        boundary = r.values.get("permissions_boundary")
        if kind and boundary:
            ev = locate(r.address, None)
            out[f"{kind}:{iam_name(r.values.get('name'))}"] = ev.model_copy(
                update={"note": f"permissions boundary {boundary} not modeled"}
            )
    return out


def _bounded(edge: EdgeRow, boundaries: dict[str, Evidence]) -> EdgeRow:
    """An edge from a principal with a permissions boundary is unknown: the boundary might deny it."""
    if edge.src not in boundaries:
        return edge
    return edge.model_copy(update={"kind": "unknown", "evidence": [*edge.evidence, boundaries[edge.src]]})


def derive_access_edges(
    resources: list[IacResource], nodes: list[NodeRow], config: dict[str, Any], locate: Locate
) -> list[EdgeRow]:
    """Every CAN and CAN_ASSUME edge in the world, sorted by (type, src, dst).

    `nodes` are the AWS adapter's nodes, with `arn` on principals and `arn_pattern` on resources; `config` is
    theseus.yaml (its `account`); `locate` turns an address and a Sid into evidence with a file and line.
    """
    account = str(config["account"])
    ordered = sorted(nodes, key=lambda n: n.id)
    principals = [n for n in ordered if parse_id(n.id)[0] in PRINCIPALS]
    reachable = {d.kind for d in load_catalog().data if d.actions()}
    targets = [n for n in ordered if parse_id(n.id)[0] in reachable]
    roles = [n for n in principals if parse_id(n.id)[0] == "role"]

    held = {n.id: statements_for(*parse_id(n.id), resources, account, locate) for n in principals}
    # A group's Deny applies to its members as well, so it overrides a member's own Allow (section 5).
    for user, groups in _memberships(resources).items():
        if user in held:
            held[user] = held[user] + [p for g in groups for p in held.get(g, []) if p[0].effect == "Deny"]
    role_resources = {iam_name(r.values.get("name")): r for r in resources if r.type == "aws_iam_role"}
    trust: dict[str, Pairs] = {}
    for role in roles:
        r = role_resources.get(parse_id(role.id)[1])
        if r is None:
            log.info("no aws_iam_role for %s, so nothing can assume it", role.id)
            continue
        trust[role.id] = [
            (s, locate(r.address, s.sid)) for s in statements(r.values.get("assume_role_policy"))
        ]

    edges: list[EdgeRow] = []
    for p in principals:
        for target in targets if held[p.id] else []:
            edge = _can(p.id, target, held[p.id])
            if edge:
                edges.append(edge)
    edges += _public_edges(resources, targets, locate)
    for caller in principals:
        for role in roles:
            if caller.id != role.id and role.id in trust:
                edge = _assume_edge(caller, role, held[caller.id], trust[role.id], account)
                if edge:
                    edges.append(edge)

    edges = (
        [_bounded(e, boundaries) for e in edges] if (boundaries := _boundaries(resources, locate)) else edges
    )
    merged: dict[tuple[str, str, str], EdgeRow] = {}
    for e in edges:
        key = (e.type, e.src, e.dst)
        if key in merged:
            old = merged[key]
            e = old.model_copy(
                update={
                    "grants": sorted(set(old.grants) | set(e.grants)),
                    "kind": "unknown" if "unknown" in (old.kind, e.kind) else old.kind,
                    "evidence": old.evidence + [x for x in e.evidence if x not in old.evidence],
                }
            )
        merged[key] = e
    return [merged[k] for k in sorted(merged)]
