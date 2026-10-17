"""An outage's blast radius on `main`: what breaks when a provider's service is down.

A posture run keeps an `OutageBasis` (in posture.py: the cloud and CI adapters' service tags, and every
dependency's valid routes from the engine), so an incident is answered from the kept graph in milliseconds,
however it arrives: picked on the dashboard, typed as a headline, or read from a provider's status feed.
Additive: nothing in `result.py` changes, and `Posture` only gains its `outage` field.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from theseus.contracts.posture import (
    Dependency,
    DependencyRoutes,
    Effect,
    OutageBasis,
    OutageMap,
    RegionTerm,
    ServiceTag,
    ServiceTerm,
)
from theseus.contracts.result import Contract, NodeInfo

__all__ = [
    "BrokenDependency",
    "DependencyRoutes",
    "Effect",
    "Impact",
    "Incident",
    "IncidentReport",
    "OutageBasis",
    "OutageMap",
    "RegionTerm",
    "ServiceTag",
    "ServiceTerm",
    "State",
]

State = Literal["down", "impaired", "degraded"]


class Incident(Contract):
    """An outage of one service, in one region or (None) every region. `title` is the headline as given:
    untrusted text, shown, never evidence and never an instruction."""

    provider: str
    service: str
    region: str | None = None
    severity: Effect = "down"
    title: str = ""
    source: Literal["picker", "text", "feed"] = "picker"
    url: str | None = None


class Impact(Contract):
    """A node the outage reaches: down or degraded itself, or impaired because it loses something it needs."""

    id: str
    state: State
    why: str
    address: str = ""


class BrokenDependency(Contract):
    """A dependency the outage cuts (`broken`: no route survives) or weakens (`degraded`). `via` lists the
    nodes on its routes that are out."""

    dependency: Dependency
    state: Literal["broken", "degraded"]
    why: str
    via: list[str] = Field(default_factory=list)


class IncidentReport(Contract):
    incident: Incident
    headline: str
    matched: list[Impact] = Field(default_factory=list)
    affected: list[Impact] = Field(default_factory=list)
    broken: list[BrokenDependency] = Field(default_factory=list)
    dependencies: int = 0
    monthly_usd: float = 0.0
    regions: list[str] = Field(default_factory=list)
    nodes: dict[str, NodeInfo] = Field(default_factory=dict)
