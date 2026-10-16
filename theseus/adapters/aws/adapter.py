"""AWS structure and the merged E2 evaluator behind the neutral cloud protocol."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from theseus.adapters.aws.access import derive_access_edges
from theseus.adapters.aws.kinds import MODELED_TYPES, PROVIDER, RESOURCE_KINDS
from theseus.adapters.aws.oidc import trust_edges
from theseus.adapters.aws.ops import ops_schema
from theseus.adapters.aws.patch import apply_ops
from theseus.adapters.aws.resources import structural_rows
from theseus.contracts.adapters import Change, CiIdentity, IacResource, Locate
from theseus.contracts.result import GraphRows, PatchOp
from theseus.errors import IngestError, PatchError

log = logging.getLogger(__name__)


class AwsAdapter:
    name = PROVIDER
    modeled_types = MODELED_TYPES
    resource_kinds = RESOURCE_KINDS

    def __init__(self, config: dict[str, Any]) -> None:
        if not isinstance(config.get("account"), str) or not config["account"]:
            raise IngestError("AWS config needs a string account")
        if not isinstance(config.get("region"), str) or not config["region"]:
            raise IngestError("AWS config needs a region")
        locations = config.get("data_locations", [])
        if not isinstance(locations, list) or any(
            not isinstance(location, dict)
            or any(
                not isinstance(location.get(field), str) or not location[field] for field in ("id", "bucket")
            )
            or not isinstance(location.get("prefix", ""), str)
            for location in locations
        ):
            raise IngestError("data_locations needs objects with string id, bucket and prefix fields")
        if len({location["id"] for location in locations}) != len(locations):
            raise IngestError("duplicate data location ID")
        self.config = deepcopy(config)

    def rows(self, resources: list[IacResource], identities: list[CiIdentity], locate: Locate) -> GraphRows:
        """Structural and IAM access rows, and TRUSTS edges for the CI identities whose tokens roles admit."""
        rows = structural_rows(resources, self.config, locate)
        access = derive_access_edges(resources, rows.nodes, self.config, locate)
        trusts, trust_unknowns = trust_edges(resources, identities, locate)
        unknowns = [*rows.unknowns, *trust_unknowns]
        for edge in access:
            if edge.kind == "unknown":
                reasons = sorted({ev.note or ev.address for ev in edge.evidence})
                unknowns.append(f"{edge.type}: {edge.src} -> {edge.dst}: " + "; ".join(reasons))
        edges = sorted([*rows.edges, *access, *trusts], key=lambda e: (e.type, e.src, e.dst))
        return GraphRows(
            nodes=rows.nodes,
            edges=[e.model_copy(update={"eid": f"e{i}"}) for i, e in enumerate(edges, 1)],
            unknowns=sorted(set(unknowns)),
        )

    def ops_for(self, change: Change, rows: GraphRows, resources: list[IacResource]) -> list[PatchOp]:
        """Cloud patch ops once E6 implements their selection; currently raises PatchError."""
        raise PatchError("AWS change selection belongs to E6")

    def apply_ops(self, resources: list[IacResource], ops: list[PatchOp]) -> list[IacResource]:
        """Independent patched resources, or PatchError when an operation cannot apply."""
        return apply_ops(resources, ops, account=self.config["account"])

    def ops_schema(self) -> dict[str, Any]:
        """The schema of the existing typed AWS operation catalog."""
        return ops_schema()
