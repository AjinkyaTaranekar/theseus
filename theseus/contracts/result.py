"""Shared models (docs/spec/05-contracts.md, "Shared models"), and project() and compare() for golden tests.

Contracts only grow: add fields, never rename or remove them, and both humans approve.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Closed sets, the same in every cloud. tests/contract/test_models.py keeps them equal to schema.py.
Access = Literal["read", "write", "assume"]
Verdict = Literal["pass", "fail", "unknown", "invalid"]
EdgeKind = Literal["configured", "inferred", "assumed", "unknown"]
EdgeType = Literal[
    "MEMBER_OF",
    "CAN_ASSUME",
    "TRUSTS",
    "RUNS_AS",
    "CAN",
    "UNLOCKS",
    "USES",
    "CALLS",
    "REQUESTS",
    "HAS_ENV",
    "FOR",
    "NEEDS",
    "AFFECTS",
]
Category = Literal[
    "ObjectStorage",
    "FileStorage",
    "BlockStorage",
    "Database",
    "Secret",
    "EncryptionKey",
    "AIModel",
    "LogStore",
    "MessageQueue",
    "MessageTopic",
    "DataStream",
]
Sensitivity = Literal["public", "internal", "confidential", "regulated"]
SensitivitySource = Literal["jev", "fallback", "human", "unclassified"]
Env = Literal["staging", "prod"]
CandidateSource = Literal["rule", "llm", "human"]


class Contract(BaseModel):
    """Base for every shared model: unknown fields are errors, and aliases are used on output."""

    model_config = ConfigDict(extra="forbid", serialize_by_alias=True, validate_by_name=True)


class Evidence(Contract):
    """Where an edge comes from in the IaC source.

    `address` names the resource; `part` the piece of it that decided the edge, such as a policy statement's
    ID. `file` is relative to the world root, or "unknown" with `line` None.
    """

    address: str
    part: str | None = None
    file: str
    line: int | None = None
    note: str | None = None


class NodeRow(Contract):
    """One node. The typed fields are common to every kind; `category`, `provider` and the sensitivity
    fields are set on Resource nodes only. `props` holds the per-kind properties in 03-graph.md, such as a
    Workflow's `subs`, which core may read, and properties marked for one adapter, which core never reads.
    """

    id: str
    labels: list[str]
    name: str
    env: Env = "prod"
    category: Category | None = None
    provider: str | None = None
    sensitivity: Sensitivity | None = None
    sensitive: bool = False
    sensitivity_source: SensitivitySource | None = None
    props: dict[str, Any] = Field(default_factory=dict)


class EdgeRow(Contract):
    """One edge. `eid` is stable within one build only; across builds an edge is (src, type, dst).

    `props` holds the per-type properties in 03-graph.md, such as `version` on USES or `access` on CALLS.
    """

    eid: str
    type: EdgeType
    src: str
    dst: str
    kind: EdgeKind
    grants: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    props: dict[str, Any] = Field(default_factory=dict)


class GraphRows(Contract):
    nodes: list[NodeRow] = Field(default_factory=list)
    edges: list[EdgeRow] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class Requirement(Contract):
    id: str
    principal: str
    access: Access
    resource: str
    source: Literal["config", "intent"]


class Grant(Contract):
    principal: str
    access: Access
    resource: str


class Intent(Contract):
    """What the PR says it needs. `stated` is False when its title and text do not say what the change is
    for (empty, "update", a ticket number, a blank template): silence, not a claim of no access."""

    purpose: str
    grants: list[Grant] = Field(default_factory=list)
    suspicious: bool = False
    stated: bool = True


class ResourceChange(Contract):
    """One resource the change adds, changes or removes, from the base and head worlds."""

    address: str
    type: str
    action: Literal["create", "update", "delete"]


class PathStep(Contract):
    """One hop, named by (src, type, dst) so it means the same in every build of the graph."""

    src: str = Field(alias="from")
    type: EdgeType
    dst: str = Field(alias="to")
    evidence: str
    # The access this hop's own edge grants (a CAN edge's read or write), sorted; the path's `grants` are its
    # last edge's. Empty when not recorded.
    grants: list[str] = Field(default_factory=list)


class PathRecord(Contract):
    id: str
    actor: str
    target: str
    grants: list[Access]
    steps: list[PathStep]
    unknown: bool = False
    inferred: bool = False
    sensitivity: Sensitivity | None = None

    @property
    def route(self) -> list[str]:
        """Every node on the path in order, the actor first and the target last."""
        return [self.steps[0].src, *(s.dst for s in self.steps)] if self.steps else [self.actor]


class RequirementStatus(Contract):
    id: str
    status: Literal["satisfied", "missing", "unknown"]


class CutEdge(Contract):
    """A cut edge. `eid` refers to the analyzed graph, for the same run's Changes."""

    eid: str
    src: str
    type: EdgeType
    dst: str
    evidence: str


class MinCut(Contract):
    sources: list[str]
    sinks: list[str]
    value: int
    cuttable: bool
    cut: list[CutEdge] = Field(default_factory=list)


class PatchOp(Contract):
    """One change to the infrastructure, in the vocabulary of the cloud adapter named by `provider`.

    The adapter owns the op catalog: it validates `args`, applies the op to IaC resources, and publishes the
    JSON schema the LLM's fix tool uses (docs/spec/08-core-and-adapters.md).
    """

    provider: str
    op: str
    args: dict[str, Any] = Field(default_factory=dict)


class Candidate(Contract):
    """A verified fix. `proposed_by` says who wrote it: "theseus" for a rule, the model string for the LLM,
    or the login of the person who proposed it. Who approved it is recorded when it is applied.
    """

    id: str
    source: CandidateSource
    proposed_by: str
    title: str
    ops: list[PatchOp] = Field(default_factory=list)
    verdict: Verdict
    reason: str = ""
    paths_left: list[str] = Field(default_factory=list)
    new_paths: list[str] = Field(default_factory=list)
    requirements_broken: list[str] = Field(default_factory=list)
    calls_broken: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)
    recommended: bool = False
    needs_closer_look: bool = False
    seconds: float = 0.0


class UnusedGrant(Contract):
    workload: str
    resource: str
    access: Access
    eid: str
    evidence: str


class BeyondIntent(Contract):
    workload: str
    resource: str
    access: Access
    file: str
    line: int
    unlocks: list[str] = Field(default_factory=list)


class StagingToProd(Contract):
    actor: str
    target: str
    path_id: str


class ChokePoint(Contract):
    id: str
    score: float


class ToolCall(Contract):
    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    ms: int = 0


class Timings(Contract):
    engine_ms: int = 0
    llm_ms: int = 0
    jev_ms: int = 0
    total_ms: int = 0


class NodeInfo(Contract):
    """What the comment needs to name a node in plain words: the resource's category and its data class."""

    category: Category | None = None
    sensitivity: Sensitivity | None = None


class Coverage(Contract):
    resources: int = 0
    modeled: int = 0
    skipped_types: dict[str, int] = Field(default_factory=dict)
    code_calls_skipped: int = 0
    # The head graph's size in the store, for the comment's FalkorDB line; 0 when not recorded.
    nodes: int = 0
    edges: int = 0


class AnalysisResult(Contract):
    scenario: str | None = None
    mode: Literal["pr", "finding", "scan"]
    repo: str | None = None
    pr_number: int | None = None
    graphs: dict[str, str] = Field(default_factory=dict)
    intent: Intent | None = None
    changes: list[ResourceChange] = Field(default_factory=list)
    headline: str = ""
    opened: list[PathRecord] = Field(default_factory=list)
    closed: list[PathRecord] = Field(default_factory=list)
    unchanged: list[PathRecord] = Field(default_factory=list)
    requirements: list[RequirementStatus] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    min_cut: MinCut | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    rotate: list[str] = Field(default_factory=list)
    unused_grants: list[UnusedGrant] = Field(default_factory=list)
    use_beyond_intent: list[BeyondIntent] = Field(default_factory=list)
    staging_to_prod: list[StagingToProd] = Field(default_factory=list)
    choke_points: list[ChokePoint] = Field(default_factory=list)
    finding: dict[str, Any] | None = None
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    tool_trace: list[ToolCall] = Field(default_factory=list)
    timings: Timings = Field(default_factory=Timings)
    coverage: Coverage = Field(default_factory=Coverage)
    # The models that answered, such as {"llm": "zai-org/GLM-5.3", "jev": "jev-1.13.0"}: shown, not compared.
    models: dict[str, str] = Field(default_factory=dict)
    # Every node on a listed path, for plain names in the comment: shown, not compared.
    nodes: dict[str, NodeInfo] = Field(default_factory=dict)


# Golden tests ---------------------------------------------------------------------------------------------

# Lists compared in order. Every other list is compared as a multiset.
ORDERED_KEYS = frozenset({"route"})


def _cite(evidence: dict[str, Evidence], evidence_id: str) -> str:
    """`file:line` for an evidence ID, `file` alone when the line is unknown, `missing:<id>` if absent."""
    ev = evidence.get(evidence_id)
    if ev is None:
        return f"missing:{evidence_id}"
    return ev.file if ev.line is None else f"{ev.file}:{ev.line}"


def _path(p: PathRecord, evidence: dict[str, Evidence]) -> dict[str, Any]:
    return {
        "actor": p.actor,
        "target": p.target,
        "route": p.route,
        "cites": [_cite(evidence, s.evidence) for s in p.steps],
    }


def _paths(paths: list[PathRecord], evidence: dict[str, Evidence]) -> list[dict[str, Any]]:
    return sorted((_path(p, evidence) for p in paths), key=lambda d: (d["actor"], d["target"]))


def project(result: AnalysisResult) -> dict[str, Any]:
    """The comparable part of a result in the expected.json shape (05-contracts.md), JSON-ready and sorted."""
    ev = result.evidence
    min_cut = None
    if result.min_cut is not None:
        min_cut = {
            "value": result.min_cut.value,
            "cuttable": result.min_cut.cuttable,
            "cut": sorted([c.src, c.type, c.dst] for c in result.min_cut.cut),
        }
    intent = None
    if result.intent is not None:
        intent = {
            "purpose": result.intent.purpose,
            "grants": sorted([g.principal, g.access, g.resource] for g in result.intent.grants),
            "suspicious": result.intent.suspicious,
            "stated": result.intent.stated,
        }
    recommended = [c.id for c in result.candidates if c.recommended]
    return {
        "scenario": result.scenario,
        "mode": result.mode,
        "headline": result.headline,
        "intent": intent,
        "changes": sorted([c.action, c.address] for c in result.changes),
        "opened": _paths(result.opened, ev),
        "closed": _paths(result.closed, ev),
        "unchanged": _paths(result.unchanged, ev),
        "requirements": {r.id: r.status for r in sorted(result.requirements, key=lambda r: r.id)},
        "unknowns": sorted(result.unknowns),
        "min_cut": min_cut,
        "candidates": {c.id: c.verdict for c in sorted(result.candidates, key=lambda c: c.id)},
        "recommended": recommended[0] if recommended else None,
        "rotate": sorted(result.rotate),
        "unused_grants": sorted([u.workload, u.resource, u.access] for u in result.unused_grants),
        "use_beyond_intent": sorted([b.workload, b.resource, b.access] for b in result.use_beyond_intent),
        "staging_to_prod": sorted([s.actor, s.target] for s in result.staging_to_prod),
    }


def compare(projection: dict[str, Any], expected: dict[str, Any], keys: list[str] | None = None) -> list[str]:
    """Readable differences between a projection and expected.json; empty when they agree.

    Compares only the keys present in `expected` (or only `keys`), and inside them only what `expected` holds:
    a field it leaves out is not compared. Paths are matched by (actor, target). `route` is compared in order,
    every other list as a multiset. `value_at_least` in `min_cut` is a lower bound on `value`.
    """
    out: list[str] = []
    for key in keys if keys is not None else list(expected):
        if key not in expected:
            continue
        if key not in projection:
            out.append(f"{key}: missing from the result")
            continue
        _diff(key, key, projection[key], expected[key], out)
    return out


def _diff(where: str, key: str, got: Any, want: Any, out: list[str]) -> None:
    if isinstance(want, dict):
        if not isinstance(got, dict):
            out.append(f"{where}: expected {want!r}, got {got!r}")
            return
        for k, w in want.items():
            if k == "value_at_least":
                value = got.get("value")
                if value is None or value < w:
                    out.append(f"{where}.value: expected at least {w}, got {value}")
            elif k not in got:
                out.append(f"{where}.{k}: missing from the result")
            else:
                _diff(f"{where}.{k}", k, got[k], w, out)
    elif isinstance(want, list) and isinstance(got, list) and (want or got) and _is_paths(want + got):
        _diff_paths(where, got, want, out)
    elif isinstance(want, list) and isinstance(got, list):
        same = got == want if key in ORDERED_KEYS else sorted(map(_key, got)) == sorted(map(_key, want))
        if not same:
            out.append(f"{where}: expected {want!r}, got {got!r}")
    elif got != want:
        out.append(f"{where}: expected {want!r}, got {got!r}")


def _is_paths(items: list[Any]) -> bool:
    return all(isinstance(x, dict) and "actor" in x and "target" in x for x in items)


def _diff_paths(where: str, got: list[dict[str, Any]], want: list[dict[str, Any]], out: list[str]) -> None:
    have = {(g["actor"], g["target"]): g for g in got}
    need = {(w["actor"], w["target"]): w for w in want}
    for actor, target in sorted(need.keys() - have.keys()):
        out.append(f"{where}: missing {actor} -> {target}")
    for actor, target in sorted(have.keys() - need.keys()):
        out.append(f"{where}: unexpected {actor} -> {target}")
    for pair in sorted(need.keys() & have.keys()):
        label = f"{where}[{pair[0]} -> {pair[1]}]"
        for k, w in need[pair].items():
            if k in ("actor", "target"):
                continue
            if k not in have[pair]:
                out.append(f"{label}.{k}: missing from the result")
            else:
                _diff(f"{label}.{k}", k, have[pair][k], w, out)


def _key(value: Any) -> str:
    """A sort key that orders any JSON value."""
    return json.dumps(value, sort_keys=True)
