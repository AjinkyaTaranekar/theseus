"""The four adapter protocols and the neutral types they exchange with the core.

Core code reasons about a neutral graph and never names a cloud, an IaC format, a CI system or an SDK. Each of
those lives in `theseus/adapters/<name>/` behind one of these protocols (docs/spec/08-core-and-adapters.md).
The protocols are shaped by one implementation each; a second implementation may add methods, never
change them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field

from theseus.contracts.result import Contract, EdgeRow, Evidence, GraphRows, PatchOp

# What crosses the boundary ------------------------------------------------------------------------


class IacResource(Contract):
    """One resource as the IaC source declares it, with values resolved where the IaC tool resolved them."""

    address: str
    type: str
    name: str
    provider: str
    values: dict[str, Any] = Field(default_factory=dict)


class UnknownField(Contract):
    """A field that stays unknown until the change is applied, with what it refers to."""

    address: str
    field: str
    references: list[str] = Field(default_factory=list)


class IacRead(Contract):
    """What an IaC adapter reads from a world root: every resource, its unknown fields, the source files."""

    resources: list[IacResource] = Field(default_factory=list)
    unknown_fields: list[UnknownField] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)


class CiIdentity(Contract):
    """The federated identity a CI pipeline presents to a cloud: who issues it and every subject it claims."""

    workflow: str
    issuer: str
    subjects: list[str] = Field(default_factory=list)


class CiRead(Contract):
    """What a CI adapter reads: Workflow and Action nodes, USES edges, and each pipeline's identity."""

    rows: GraphRows = Field(default_factory=GraphRows)
    identities: list[CiIdentity] = Field(default_factory=list)


class CodeRead(Contract):
    """What a code adapter reads: CALLS, REQUESTS and HAS_ENV edges, and the calls it could not model."""

    edges: list[EdgeRow] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    calls_skipped: int = 0


class Change(Contract):
    """A change a candidate rule wants, in graph terms. The cloud adapter turns it into patch ops.

    remove_edge: drop the grant or membership behind `eid`. narrow_grant: keep only the resources in `values`.
    restrict_trust: accept only the subjects in `values`. deny_principal: deny the principals in `values` on
    the edge's target.
    """

    kind: Literal["remove_edge", "narrow_grant", "restrict_trust", "deny_principal"]
    eid: str
    values: list[str] = Field(default_factory=list)
    # Optional exact evidence selection: a revert must not remove pre-existing grant statements.
    evidence: list[Evidence] = Field(default_factory=list)
    added_only: bool = False


class PatchTraits(Contract):
    """Adapter-verified properties of the statements an operation adds."""

    adds_broad_wildcard: bool


Locate = Callable[[str, str | None], Evidence]
"""Evidence for an IaC address and an optional part of it, with the file and line the IaC adapter found."""


# The protocols ------------------------------------------------------------------------------------


class IacAdapter(Protocol):
    """Reads one IaC format and writes fixes back in it."""

    name: str

    def read(self, root: Path, plan: dict[str, Any]) -> IacRead:
        """Every resource in the world root's plan output, its unknown fields, and the source files."""
        ...

    def locate(self, files: dict[str, str], address: str, part: str | None) -> Evidence:
        """The file and line that declare `address` (or `part` inside it); file "unknown" when not found."""
        ...

    def render(self, files: dict[str, str], ops: list[PatchOp]) -> dict[str, str]:
        """The edited source files by relative path. Raises PatchError when an edit cannot be verified."""
        ...


class CloudAdapter(Protocol):
    """Knows one cloud: its resource kinds, its identities and permissions, and its patch-op catalog."""

    name: str
    modeled_types: frozenset[str]
    resource_kinds: dict[str, str]
    """Resource kind (the node ID prefix) -> its category in RESOURCE_CATEGORIES."""

    def rows(self, resources: list[IacResource], identities: list[CiIdentity], locate: Locate) -> GraphRows:
        """Principal and resource nodes, and MEMBER_OF, CAN_ASSUME, TRUSTS, RUNS_AS, CAN and UNLOCKS edges."""
        ...

    def ops_for(
        self,
        change: Change,
        rows: GraphRows,
        resources: list[IacResource],
        *,
        base_resources: list[IacResource] | None = None,
    ) -> list[PatchOp]:
        """Patch ops that make `change`, or [] when this cloud cannot express it."""
        ...

    def apply_ops(self, resources: list[IacResource], ops: list[PatchOp]) -> list[IacResource]:
        """The patched resources. Raises PatchError when an op cannot apply."""
        ...

    def patch_traits(self, ops: list[PatchOp]) -> PatchTraits:
        """Validated added-statement breadth, independent of model-provided metadata."""
        ...

    def ops_schema(self) -> dict[str, Any]:
        """JSON schema of this cloud's ops, for the LLM's fix tool."""
        ...


class CiAdapter(Protocol):
    """Reads one CI system's pipeline files."""

    name: str

    def read(self, files: dict[str, str]) -> CiRead: ...


class CodeAdapter(Protocol):
    """Reads service code in one language for calls through one cloud's SDK."""

    name: str

    def read(self, files: dict[str, str], rows: GraphRows, resources: list[IacResource]) -> CodeRead: ...


@dataclass(frozen=True)
class Adapters:
    """The adapters one run uses. Only the composition roots (cli.py, api/app.py) and tests build one."""

    iac: IacAdapter
    cloud: CloudAdapter
    ci: CiAdapter
    code: CodeAdapter
