"""Catalog-driven resource nodes and structural facts from known plan values."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from theseus.adapters.aws.catalog import DataEntry, load_catalog, value_at
from theseus.adapters.aws.kinds import MODELED_TYPES, PROVIDER, s3_id
from theseus.adapters.aws.policies import iam_name
from theseus.contracts.adapters import IacResource, Locate
from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow
from theseus.contracts.schema import INTERNET, ONTOLOGY_LABELS, node_id
from theseus.errors import IngestError

log = logging.getLogger(__name__)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _tags(resource: IacResource) -> dict[str, Any]:
    tags = resource.values.get("tags") or {}
    if not isinstance(tags, dict):
        raise IngestError(f"{resource.address}: tags must be an object")
    return tags


def _join(value: Any) -> str | None:
    text = _text(value)
    return re.sub(r":\d+$", "", text.rsplit("/", 1)[-1]) if text else None


def _same_scope(value: Any, resource: IacResource, config: dict[str, Any]) -> bool:
    if not isinstance(value, str) or not value.startswith("arn:"):
        return True
    parts = value.split(":", 5)
    if len(parts) != 6:
        return False
    known = _text(resource.values.get("arn"))
    if known is not None:
        return parts[:5] == known.split(":", 5)[:5]
    return (
        parts[1] == config.get("partition", "aws")
        and parts[4] == config["account"]
        and (not parts[3] or parts[3] == config["region"])
    )


def _resource_arn(
    resource: IacResource, entry: DataEntry, value: dict[str, Any], config: dict[str, Any]
) -> str:
    representative = entry.resource_arn(value, config)
    known = _text(resource.values.get("arn"))
    if entry.per == "location" or known is None:
        return representative
    # A catalog may declare both a base ARN and its :* form for the same resource.
    if known == representative + ":*" and any(
        not action.by_path and {representative, known} <= set(action.arns_for(representative))
        for action in entry.actions()
    ):
        return representative
    return known


def _environment(resource: IacResource) -> dict[str, str]:
    if resource.type == "aws_lambda_function":
        block = resource.values.get("environment") or []
        if not block:
            return {}
        if not isinstance(block, list) or not isinstance(block[0], dict):
            raise IngestError(f"{resource.address}: malformed environment")
        variables = block[0].get("variables") or {}
        if not isinstance(variables, dict):
            raise IngestError(f"{resource.address}: environment variables must be an object")
    elif resource.type == "aws_ecs_task_definition":
        raw = resource.values.get("container_definitions")
        if raw is None:
            return {}
        try:
            containers = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise IngestError(f"{resource.address}: malformed container_definitions") from exc
        if not isinstance(containers, list) or any(not isinstance(c, dict) for c in containers):
            raise IngestError(f"{resource.address}: containers must be a list of objects")
        if not containers:
            return {}
        environment = containers[0].get("environment") or []
        if not isinstance(environment, list) or any(not isinstance(v, dict) for v in environment):
            raise IngestError(f"{resource.address}: malformed container environment")
        variables = {}
        for item in environment:
            name = _text(item.get("name"))
            if name is None or name in variables:
                raise IngestError(f"{resource.address}: missing or duplicate environment variable name")
            variables[name] = item.get("value")
    else:
        return {}
    return {k: v for k, v in sorted(variables.items()) if isinstance(k, str) and isinstance(v, str)}


def structural_rows(resources: list[IacResource], config: dict[str, Any], locate: Locate) -> GraphRows:
    """Principal, resource and workload nodes, with membership, identity, credential and environment edges."""
    ordered = sorted((r for r in resources if r.type in MODELED_TYPES), key=lambda r: r.address)
    nodes: dict[str, NodeRow] = {}
    edges: list[EdgeRow] = []
    unknowns: list[str] = []
    catalog = load_catalog()

    def unknown(message: str) -> None:
        log.info("%s", message)
        unknowns.append(message)

    def add(node: NodeRow) -> None:
        node.labels = sorted(set(node.labels))
        if node.id in nodes:
            raise IngestError(f"multiple resources declare node {node.id}")
        nodes[node.id] = node

    def edge(etype: Any, src: str, dst: str, evidence: list[Evidence], **kwargs: Any) -> None:
        if src not in nodes or dst not in nodes:
            unknown(f"{etype}: missing endpoint {src} -> {dst}")
            return
        edges.append(
            EdgeRow(
                eid="",
                type=etype,
                src=src,
                dst=dst,
                evidence=evidence,
                kind=kwargs.pop("kind", "configured"),
                **kwargs,
            )
        )

    add(NodeRow(id=INTERNET, labels=["Node", "Principal", "Entry"], name="internet"))
    principal_types = {"aws_iam_user": "user", "aws_iam_group": "group", "aws_iam_role": "role"}
    for resource in ordered:
        kind = principal_types.get(resource.type)
        if kind is None:
            continue
        name = _text(resource.values.get("name"))
        if name is None:
            unknown(f"{resource.address}: principal name unresolved")
            continue
        path = str(resource.values.get("path") or "/").strip("/")
        arn = _text(resource.values.get("arn")) or (
            f"arn:{config.get('partition', 'aws')}:iam::{config['account']}:{kind}/"
            + (path + "/" if path else "")
            + name
        )
        add(
            NodeRow(
                id=node_id(kind, name),
                name=name,
                labels=["Node", "Principal", kind.title(), ONTOLOGY_LABELS[kind]],
                props={"arn": arn, "address": resource.address},
            )
        )

    data_by_address: dict[str, list[NodeRow]] = {}
    for resource in ordered:
        entry = next((d for d in catalog.data if d.type == resource.type), None)
        if entry is None:
            continue
        name = _text(value_at(resource.values, entry.name))
        values: list[dict[str, Any]] = []
        if entry.per == "location":
            bucket = _text(resource.values.get("bucket"))
            if bucket is None:
                unknown(f"{resource.address}: bucket name unresolved")
                continue
            for location in config.get("data_locations", []):
                if location.get("bucket") == bucket:
                    prefix = location.get("prefix", "")
                    if not isinstance(prefix, str) or location.get("id") != s3_id(bucket, prefix):
                        raise IngestError(
                            f"{resource.address}: data location ID does not match bucket/prefix"
                        )
                    values.append({**location, "name": f"{bucket}/{prefix}"})
        elif name is not None:
            values.append({"id": node_id(entry.kind, name), "name": name})
        else:
            unknown(f"{resource.address}: resource name {entry.name} unresolved")
        for value in sorted(values, key=lambda v: v["id"]):
            node = NodeRow(
                id=value["id"],
                name=value["name"],
                labels=["Node", "Resource", entry.category],
                category=entry.category,
                provider=PROVIDER,
                props={
                    "kind": entry.kind,
                    "address": resource.address,
                    "arn_pattern": _resource_arn(resource, entry, value, config),
                },
            )
            add(node)
            data_by_address.setdefault(resource.address, []).append(node)

    bindings: list[tuple[NodeRow, IacResource, IacResource | None, str | None]] = []
    for resource in ordered:
        entry = next((w for w in catalog.workloads if w.type == resource.type), None)
        if entry is None:
            continue
        name = _text(value_at(resource.values, entry.name))
        if name is None:
            unknown(f"{resource.address}: workload name {entry.name} unresolved")
            continue
        node = NodeRow(
            id=node_id("workload", name),
            name=name,
            labels=["Node", "Principal", "Workload", *([entry.label] if entry.label else [])],
            props={
                "runtime": entry.runtime,
                "address": resource.address,
                "code_path": _tags(resource).get("theseus_code_path"),
            },
        )
        add(node)
        owner: IacResource | None = resource
        if entry.role.via:
            link = value_at(resource.values, entry.role.join)
            exact = [
                r
                for r in ordered
                if r.type == entry.role.via
                and link is not None
                and (r.values.get("arn") == link or value_at(r.values, entry.role.match) == link)
            ]
            candidates = exact or [
                r
                for r in ordered
                if r.type == entry.role.via
                and _join(link) is not None
                and _same_scope(link, r, config)
                and _join(value_at(r.values, entry.role.match)) == _join(link)
            ]
            owner = candidates[0] if len(candidates) == 1 else None
            if owner is None:
                unknown(f"{resource.address}: role source {entry.role.via} unresolved or ambiguous")
        role_value = _text(value_at(owner.values, entry.role.field)) if owner else None
        if role_value and role_value.startswith("arn:"):
            matches = [n.id for n in nodes.values() if "Role" in n.labels and n.props["arn"] == role_value]
            role = matches[0] if len(matches) == 1 else None
        else:
            name = iam_name(role_value)
            role = f"role:{name}" if name else None
        bindings.append((node, resource, owner, role))

    for resource in ordered:
        if resource.type == "aws_iam_user_group_membership":
            user = iam_name(resource.values.get("user"))
            groups = resource.values.get("groups") or []
            if not isinstance(groups, list) or any(not isinstance(g, str) for g in groups):
                raise IngestError(f"{resource.address}: groups must be strings")
            if not user:
                unknown(f"{resource.address}: membership user unresolved")
            else:
                for group in sorted(set(groups)):
                    edge(
                        "MEMBER_OF",
                        f"user:{user}",
                        f"group:{iam_name(group)}",
                        [locate(resource.address, None)],
                    )
        db = _tags(resource).get("db_instance")
        for node in data_by_address.get(resource.address, []):
            if node.category == "Secret" and isinstance(db, str):
                edge(
                    "UNLOCKS",
                    node.id,
                    f"db:{db}",
                    [locate(resource.address, None)],
                    kind="inferred",
                    grants=["read", "write"],
                )

    for node, resource, owner, role in bindings:
        evidence = [locate(resource.address, None)]
        if owner is not None and owner.address != resource.address:
            evidence.append(locate(owner.address, None))
        if role:
            edge("RUNS_AS", node.id, role, evidence)
        else:
            unknown(f"{resource.address}: runtime role unresolved")
        for var, value in _environment(owner).items() if owner is not None else []:
            for target in sorted(nodes.values(), key=lambda n: n.id):
                match = False
                if "Resource" in target.labels:
                    kind = target.props["kind"]
                    if kind == "s3":
                        bucket = target.id.split("://", 1)[1].split("/", 1)[0]
                        match = value == bucket
                    elif target.category == "Secret" or kind == "dynamodb":
                        match = value in {target.name, target.id, target.props["arn_pattern"]}
                elif "Workload" in target.labels:
                    try:
                        host = urlsplit(value).hostname
                    except ValueError:
                        host = None
                    match = host is not None and host.split(".", 1)[0] == target.name
                if match:
                    edge(
                        "HAS_ENV",
                        node.id,
                        target.id,
                        [locate((owner or resource).address, None)],
                        props={"var": var},
                    )
    return GraphRows(
        nodes=sorted(nodes.values(), key=lambda n: n.id),
        edges=sorted(edges, key=lambda e: (e.type, e.src, e.dst)),
        unknowns=sorted(set(unknowns)),
    )
