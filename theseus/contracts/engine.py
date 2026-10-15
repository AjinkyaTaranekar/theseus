"""Engine function signatures and the graph store protocol (docs/spec/05-contracts.md, "Engine functions").

Signatures only: each Protocol names the module and task that implement it. The engine works on the neutral
graph; anything that needs a cloud, an IaC format, a CI system or a language goes through `Adapters`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field

from theseus.config import Settings
from theseus.contracts.adapters import Adapters, Change, IacResource, UnknownField
from theseus.contracts.result import (
    AnalysisResult,
    BeyondIntent,
    Candidate,
    CandidateSource,
    ChokePoint,
    Contract,
    EdgeRow,
    GraphRows,
    MinCut,
    NodeRow,
    PatchOp,
    PathRecord,
    Requirement,
    RequirementStatus,
    StagingToProd,
    UnusedGrant,
)

# Inputs and outputs -------------------------------------------------------------------------------


class World(Contract):
    """One state of the infrastructure, read from a world root (04-engine.md section 1). Relative paths."""

    root: str
    iac: str
    resources: list[IacResource] = Field(default_factory=list)
    unknown_fields: list[UnknownField] = Field(default_factory=list)
    skipped_types: dict[str, int] = Field(default_factory=dict)
    unknowns: list[str] = Field(default_factory=list)
    iac_files: dict[str, str] = Field(default_factory=dict)
    ci_files: dict[str, str] = Field(default_factory=dict)
    code_files: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class GraphState(Contract):
    """One state loaded as one graph: its name in the store, the world it came from, and its rows.

    Engine functions take a GraphState instead of a graph name, a world and rows separately, so the three
    can never come from different states.
    """

    name: str
    world: World
    rows: GraphRows


class Analysis(Contract):
    """One graph analyzed for a set of actors (04-engine.md sections 9 and 10)."""

    actors: list[str] = Field(default_factory=list)
    paths: dict[str, list[PathRecord]] = Field(default_factory=dict)
    dangerous: list[PathRecord] = Field(default_factory=list)
    requirements: list[RequirementStatus] = Field(default_factory=list)


class PathDiff(Contract):
    """Dangerous paths keyed by (actor, target): head minus base, base minus head, and both."""

    opened: list[PathRecord] = Field(default_factory=list)
    closed: list[PathRecord] = Field(default_factory=list)
    unchanged: list[PathRecord] = Field(default_factory=list)


class GraphDelta(Contract):
    """Head rows to patched rows. Edges are removed by (src, type, dst), because eids change per build."""

    add_nodes: list[NodeRow] = Field(default_factory=list)
    remove_nodes: list[str] = Field(default_factory=list)
    add_edges: list[EdgeRow] = Field(default_factory=list)
    remove_edges: list[tuple[str, str, str]] = Field(default_factory=list)


class FlowRow(Contract):
    """One FLOW edge (03-graph.md, Q_SET_FLOW): every path edge from src to dst, capacities summed."""

    src: str
    dst: str
    eids: list[str]
    capacity: int


class EdgeFlow(Contract):
    eids: list[str]
    flow: float


class FlowResult(Contract):
    """Max flow and the flow on each FLOW edge that carries any; a missing edge carries 0."""

    value: float
    flows: list[EdgeFlow] = Field(default_factory=list)


class RuleFix(Contract):
    """A rule's fix in graph terms, before the cloud adapter turns its changes into ops."""

    id: str
    title: str
    changes: list[Change]


class CandidateDraft(Contract):
    """A fix before simulation: a RuleFix after `ops_for`, the LLM's ops, or a person's."""

    id: str
    source: CandidateSource
    proposed_by: str
    title: str
    ops: list[PatchOp] = Field(default_factory=list)


class WorkflowUse(Contract):
    workflow: str
    version: str


class GrantRow(Contract):
    """Q_UNUSED_GRANTS: a grant on a workload's own role to sensitive data its code never calls."""

    workload: str
    resource: str
    eid: str


class CallRow(Contract):
    """Q_CALLS: one code call."""

    workload: str
    resource: str
    access: str
    eid: str


# The graph store ----------------------------------------------------------------------------------


class GraphStore(Protocol):
    """FalkorDB in the product, MemoryStore in offline tests (task E3). One method per canonical query."""

    def list_graphs(self) -> list[str]:
        """Every graph name in the store, sorted."""
        ...

    def load(self, graph: str, rows: GraphRows) -> None:
        """Replace `graph` with these rows (03-graph.md, "Loading")."""
        ...

    def copy(self, src: str, dst: str) -> None:
        """GRAPH.COPY `src` to `dst`, replacing `dst`."""
        ...

    def delete(self, graph: str) -> None:
        """Delete `graph`; no error if it does not exist."""
        ...

    def apply_delta(self, graph: str, delta: GraphDelta) -> None:
        """Remove, then add, the delta's nodes and edges."""
        ...

    def paths(self, graph: str, actor: str) -> list[list[str]]:
        """Q_PATHS: the eids of every route of at most MAX_PATH_EDGES edges from `actor` to a resource."""
        ...

    def max_flow(self, graph: str, sources: list[str], sinks: list[str], rows: list[FlowRow]) -> FlowResult:
        """Q_SET_FLOW with `rows`, then Q_MAXFLOW. Sources and sinks must not overlap."""
        ...

    def betweenness(self, graph: str) -> list[ChokePoint]:
        """Q_BETWEENNESS over the path types the graph has, highest score first, then by ID."""
        ...

    def workflows_using(self, graph: str, action: str) -> list[WorkflowUse]:
        """Q_WORKFLOWS_USING, sorted by workflow."""
        ...

    def unused_grants(self, graph: str) -> list[GrantRow]:
        """Q_UNUSED_GRANTS, sorted by (workload, resource)."""
        ...

    def calls(self, graph: str) -> list[CallRow]:
        """Q_CALLS, sorted by (workload, resource, access)."""
        ...


@dataclass(frozen=True)
class Deps:
    """What a run needs from outside: the store, the adapters, the LLM wrapper (A1), Jev (A2), settings."""

    store: GraphStore
    adapters: Adapters
    llm: Any
    jev: Any
    settings: Settings


# Engine functions, in the order of the 05 table ---------------------------------------------------


class LoadWorld(Protocol):
    """`importer/world.py: load_world` (E1)."""

    def __call__(self, root: Path, plan: dict[str, Any], adapters: Adapters) -> World:
        """The world read from a world root and its plan output."""
        ...


class BuildRows(Protocol):
    """`importer/build.py: build_rows` (E1)."""

    def __call__(self, world: World, labels: dict[str, str], adapters: Adapters) -> GraphRows:
        """Nodes and edges for a world, with each resource's sensitivity label (node ID -> label) applied."""
        ...


class LoadGraph(Protocol):
    """`graph/load.py: load_graph` (E3). Loads the state's rows into the graph its name names."""

    def __call__(self, store: GraphStore, state: GraphState) -> None: ...


class CopyGraph(Protocol):
    """`graph/load.py: copy_graph` (E3)."""

    def __call__(self, store: GraphStore, src: str, dst: str) -> None: ...


class DeleteGraph(Protocol):
    """`graph/load.py: delete_graph` (E3)."""

    def __call__(self, store: GraphStore, name: str) -> None: ...


class MakeDelta(Protocol):
    """`graph/load.py: delta` (E5)."""

    def __call__(self, old: GraphRows, new: GraphRows) -> GraphDelta:
        """What turns `old` into `new`, comparing nodes by ID and edges by (src, type, dst)."""
        ...


class ApplyDelta(Protocol):
    """`graph/load.py: apply_delta` (E5)."""

    def __call__(self, store: GraphStore, name: str, delta: GraphDelta) -> None: ...


class Analyze(Protocol):
    """`engine/analyze.py: analyze` (E3)."""

    def __call__(
        self, store: GraphStore, state: GraphState, requirements: list[Requirement], actors: list[str]
    ) -> Analysis:
        """Valid paths per actor, the dangerous ones, and each requirement's status."""
        ...


class Diff(Protocol):
    """`engine/analyze.py: diff` (E3)."""

    def __call__(self, base: Analysis, head: Analysis) -> PathDiff: ...


class MinCutFn(Protocol):
    """`engine/mincut.py: min_cut` (E4)."""

    def __call__(
        self,
        store: GraphStore,
        state: GraphState,
        analysis: Analysis,
        sources: list[str],
        requirements: list[Requirement],
    ) -> MinCut:
        """The minimum cut between the sources and their dangerous targets."""
        ...


class Simulate(Protocol):
    """`engine/simulate.py: simulate` (E5)."""

    def __call__(
        self,
        store: GraphStore,
        head: GraphState,
        draft: CandidateDraft,
        actors: list[str],
        requirements: list[Requirement],
        adapters: Adapters,
    ) -> Candidate:
        """The draft verified on a copy of the head graph, with its verdict (04-engine.md section 14)."""
        ...


class RuleCandidates(Protocol):
    """`engine/candidates.py: rule_candidates` (E6)."""

    def __call__(
        self, state: GraphState, analysis: Analysis, opened: list[PathRecord], cut: MinCut | None
    ) -> list[RuleFix]:
        """Rules A, C, D and S that apply to these paths, sorted by ID."""
        ...


class Rank(Protocol):
    """`engine/candidates.py: rank` (E6)."""

    def __call__(self, candidates: list[Candidate], break_scores: dict[str, float]) -> list[Candidate]:
        """Candidates in rank order, the first pass recommended unless Jev's break score (by ID) vetoes it."""
        ...


class BlastRadius(Protocol):
    """`engine/finding.py: blast_radius` (FM3)."""

    def __call__(self, store: GraphStore, state: GraphState, workflows: list[str]) -> list[PathRecord]: ...


class RotateList(Protocol):
    """`engine/finding.py: rotate_list` (FM3)."""

    def __call__(self, store: GraphStore, state: GraphState, workflows: list[str]) -> list[str]:
        """Every reachable resource whose category is `secret`, sorted."""
        ...


class Containment(Protocol):
    """`engine/finding.py: containment` (FM3, FM6)."""

    def __call__(
        self, state: GraphState, analysis: Analysis, cut: MinCut, requirements: list[Requirement]
    ) -> RuleFix | None:
        """Candidate K: restrict the cut trust to the subjects whose requirements need it, if one is cut."""
        ...


class StagingToProdFn(Protocol):
    """`engine/staging.py: staging_to_prod` (FM4)."""

    def __call__(self, analysis: Analysis, state: GraphState) -> list[StagingToProd]: ...


class UnusedGrants(Protocol):
    """`engine/usage.py: unused_grants` (C3)."""

    def __call__(self, store: GraphStore, state: GraphState) -> list[UnusedGrant]: ...


class UseBeyondIntent(Protocol):
    """`engine/usage.py: use_beyond_intent` (C4)."""

    def __call__(
        self, base: GraphState, head: GraphState, requirements: list[Requirement]
    ) -> list[BeyondIntent]: ...


class ChokePoints(Protocol):
    """`graph/algos.py: choke_points` (FM4)."""

    def __call__(self, store: GraphStore, state: GraphState) -> list[ChokePoint]: ...


class RunPr(Protocol):
    """`engine/pipeline.py: run_pr` (E3, then A5)."""

    def __call__(
        self, base: World, head: World, pr_title: str, pr_body: str, deps: Deps
    ) -> AnalysisResult: ...


class RunFinding(Protocol):
    """`engine/pipeline.py: run_finding` (FM3)."""

    def __call__(self, world: World, advisory: dict[str, Any], deps: Deps) -> AnalysisResult: ...


class RunScan(Protocol):
    """`engine/pipeline.py: run_scan` (C3)."""

    def __call__(self, world: World, deps: Deps) -> AnalysisResult: ...
