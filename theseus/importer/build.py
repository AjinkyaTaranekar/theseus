"""Deterministic composition of adapter facts and owner-configured requirements."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from theseus.contracts.adapters import Adapters, CiRead, CodeRead
from theseus.contracts.engine import World
from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow, Requirement, Sensitivity
from theseus.contracts.schema import SENSITIVE, SENSITIVITY, node_id
from theseus.errors import IngestError

log = logging.getLogger(__name__)


def _citations(world: World) -> dict[str, Evidence]:
    try:
        source = (Path(world.root) / "theseus.yaml").read_text(encoding="utf-8")
        if yaml.safe_load(source) != world.config:
            log.info("config changed after loading; requirement source positions are unavailable")
            return {}
        document = yaml.compose(source)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        log.info("requirement source positions unavailable: %s", type(exc).__name__)
        return {}
    found = {}
    if isinstance(document, yaml.MappingNode):
        for key, value in document.value:
            if key.value == "requirements" and isinstance(value, yaml.SequenceNode):
                for item in value.value:
                    if isinstance(item, yaml.MappingNode):
                        for name, identifier in item.value:
                            if name.value == "id" and isinstance(identifier, yaml.ScalarNode):
                                found[identifier.value] = Evidence(
                                    address="theseus.yaml",
                                    part=identifier.value,
                                    file="theseus.yaml",
                                    line=name.start_mark.line + 1,
                                )
    return found


def _evidence(evidence: list[Evidence]) -> list[Evidence]:
    unique = {}
    for ev in evidence:
        if ev.file == "unknown":
            if ev.line is not None or not ev.note:
                raise IngestError("unknown evidence needs a reason and no line")
        elif ev.line is None or ev.line < 1:
            raise IngestError("located evidence needs a positive source line")
        unique[ev.model_dump_json()] = ev
    return sorted(unique.values(), key=lambda e: (e.file, e.line or 0, e.address, e.part or "", e.note or ""))


def _normalized(nodes: list[NodeRow], edges: list[EdgeRow], unknowns: list[str]) -> GraphRows:
    by_id: dict[str, NodeRow] = {}
    for node in nodes:
        node = node.model_copy(deep=True)
        node.labels = sorted(set(node.labels))
        if node.id in by_id and node != by_id[node.id]:
            raise IngestError(f"conflicting node declarations for {node.id}")
        by_id[node.id] = node
    merged: dict[tuple[str, str, str], EdgeRow] = {}
    for edge in edges:
        if edge.src not in by_id or edge.dst not in by_id:
            raise IngestError(f"edge has missing endpoint: {edge.src} {edge.type} {edge.dst}")
        if not edge.evidence:
            raise IngestError(f"edge has no evidence: {edge.src} {edge.type} {edge.dst}")
        edge = edge.model_copy(deep=True)
        key = (edge.type, edge.src, edge.dst)
        if key in merged:
            old = merged[key]
            if any(k in old.props and old.props[k] != v for k, v in edge.props.items()):
                raise IngestError(f"conflicting edge properties: {key}")
            kinds = {old.kind, edge.kind}
            if len(kinds) > 1 and "unknown" not in kinds:
                raise IngestError(f"conflicting edge kinds: {key}")
            edge = edge.model_copy(
                update={
                    "grants": sorted(set(old.grants) | set(edge.grants)),
                    "evidence": [*old.evidence, *edge.evidence],
                    "props": {**old.props, **edge.props},
                    "kind": "unknown" if "unknown" in kinds else old.kind,
                }
            )
        edge.grants = sorted(set(edge.grants))
        edge.evidence = _evidence(edge.evidence)
        merged[key] = edge
    ordered = [merged[key].model_copy(update={"eid": f"e{i}"}) for i, key in enumerate(sorted(merged), 1)]
    return GraphRows(
        nodes=[by_id[key] for key in sorted(by_id)], edges=ordered, unknowns=sorted(set(unknowns))
    )


def build_rows(world: World, labels: dict[str, str], adapters: Adapters) -> GraphRows:
    """Sorted, evidenced rows from the adapters, sensitivity labels and configured requirements."""
    ci = adapters.ci.read(world.ci_files) if world.ci_files else CiRead()
    cloud = adapters.cloud.rows(
        world.resources,
        ci.identities,
        lambda address, part: adapters.iac.locate(world.iac_files, address, part),
    )
    rows = _normalized(
        [*ci.rows.nodes, *cloud.nodes],
        [*ci.rows.edges, *cloud.edges],
        [*world.unknowns, *ci.rows.unknowns, *cloud.unknowns],
    )
    code = (
        adapters.code.read(world.code_files, rows.model_copy(deep=True), world.resources)
        if world.code_files
        else CodeRead()
    )
    nodes = [n.model_copy(deep=True) for n in rows.nodes]
    edges = [*rows.edges, *code.edges]
    unknowns = [*rows.unknowns, *code.unknowns]

    overrides = world.config.get("sensitive_overrides", {})
    if (
        not isinstance(labels, dict)
        or not isinstance(overrides, dict)
        or any(not isinstance(key, str) for key in [*labels, *overrides])
        or any(v not in SENSITIVITY for v in [*labels.values(), *overrides.values()])
    ):
        raise IngestError("sensitivity labels must be one of the supported classes")
    environments = world.config.get("environments", {})
    if (
        not isinstance(environments, dict)
        or not isinstance(environments.get("staging", []), list)
        or any(not isinstance(identifier, str) for identifier in environments.get("staging", []))
    ):
        raise IngestError("environments.staging must be a list")
    staging = environments.get("staging", [])
    for node in nodes:
        node.env = "staging" if node.id in staging else "prod"
        if "Resource" in node.labels:
            label = overrides.get(node.id, labels.get(node.id))
            node.sensitivity = cast(Sensitivity | None, label)
            node.sensitive = label in SENSITIVE
            node.sensitivity_source = (
                ("human" if node.id in overrides else "jev") if label else "unclassified"
            )
    available = {n.id for n in nodes}
    resource_ids = {n.id for n in nodes if "Resource" in n.labels}
    for target in sorted(set(overrides) - resource_ids):
        log.warning("sensitive_overrides names no resource in this graph: %s", target)

    raw_requirements = world.config.get("requirements", [])
    if not isinstance(raw_requirements, list):
        raise IngestError("requirements must be a list")
    requirements: list[Requirement] = []
    try:
        requirements = [Requirement.model_validate({**raw, "source": "config"}) for raw in raw_requirements]
    except (TypeError, ValidationError) as exc:
        raise IngestError("invalid config requirement") from exc
    if len({r.id for r in requirements}) != len(requirements):
        raise IngestError("duplicate requirement ID")
    citations = _citations(world) if requirements else {}
    for requirement in sorted(requirements, key=lambda r: r.id):
        identifier = node_id("req", requirement.id)
        ev = citations.get(requirement.id) or Evidence(
            address="theseus.yaml",
            part=requirement.id,
            file="unknown",
            note="requirement source positions unavailable for this world config",
        )
        nodes.append(
            NodeRow(
                id=identifier,
                name=requirement.id,
                env="staging" if identifier in staging else "prod",
                labels=["Node", "Requirement"],
                props={"req_id": requirement.id, "access": requirement.access, "source": "config"},
            )
        )
        for etype, target in [("FOR", requirement.principal), ("NEEDS", requirement.resource)]:
            if target not in available:
                if etype == "FOR" and target.startswith("workflow:"):
                    unknowns.append(f"requirement {requirement.id}: missing FOR endpoint {target}")
                    continue
                raise IngestError(f"requirement {requirement.id}: missing endpoint {target}")
            edges.append(
                EdgeRow(
                    eid="",
                    type=cast(Any, etype),
                    src=identifier,
                    dst=target,
                    kind="configured",
                    evidence=[ev],
                    props={"access": requirement.access} if etype == "NEEDS" else {},
                )
            )
    return _normalized(nodes, edges, unknowns)
