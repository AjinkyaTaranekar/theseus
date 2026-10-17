"""The posture of a world's `main` (issues O1 to O3): who reaches what, the single points of failure and
articulation points of its graph, and what it costs. Additive: nothing in `result.py` changes.

The engine computes every field from the graph and the IaC read; a cost is an estimate from the cloud
adapter's list prices, and says so.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from theseus.contracts.result import Access, AnalysisResult, Contract, NodeInfo, Sensitivity


class Reach(Contract):
    """What one actor reaches: every sensitive target with a valid path, the ones a requirement names, and
    the most sensitive class among them. Its blast radius if it is compromised."""

    actor: str
    targets: list[str] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)
    worst: Sensitivity | None = None
    paths: int = 0


class Dependency(Contract):
    """An access something needs: a code call (`code`) or a `theseus.yaml` requirement (`requirement`)."""

    principal: str
    access: Access
    resource: str
    source: Literal["code", "requirement"]


class SinglePoint(Contract):
    """A node on every route of each dependency in `breaks`: losing it cuts all of them off."""

    id: str
    breaks: list[Dependency] = Field(default_factory=list)


class Articulation(Contract):
    """A node whose removal splits the access graph: `pieces` are the sizes of what is left, largest first,
    and `cut_off` counts the nodes outside the largest piece."""

    id: str
    cut_off: int
    pieces: list[int] = Field(default_factory=list)


class CostLine(Contract):
    """One resource's estimated monthly cost at list price. `monthly_usd` is 0 for a resource billed only by
    use; `basis` says what the estimate counts."""

    address: str
    type: str
    monthly_usd: float
    basis: str
    usage_billed: bool = False


class Saving(Contract):
    """Something that could be removed, its estimated monthly saving, and why the graph says so."""

    id: str
    monthly_usd: float = 0.0
    reason: str


class CostSummary(Contract):
    monthly_usd: float = 0.0
    lines: list[CostLine] = Field(default_factory=list)
    savings: list[Saving] = Field(default_factory=list)
    savings_usd: float = 0.0
    note: str = ""


class Posture(Contract):
    reach: list[Reach] = Field(default_factory=list)
    dependencies: int = 0
    single_points: list[SinglePoint] = Field(default_factory=list)
    articulation: list[Articulation] = Field(default_factory=list)
    unreached: list[str] = Field(default_factory=list)
    cost: CostSummary = Field(default_factory=CostSummary)
    # Every node named above, for plain names on the dashboard: shown, not compared.
    nodes: dict[str, NodeInfo] = Field(default_factory=dict)


class PostureReport(Contract):
    """One posture run of `main`: the scan (C3), its posture, and a finding for each advisory whose Action a
    workflow on `main` uses at an affected version."""

    scan: AnalysisResult
    posture: Posture
    findings: list[AnalysisResult] = Field(default_factory=list)
