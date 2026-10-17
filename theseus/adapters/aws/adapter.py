"""AWS structure and the merged E2 evaluator behind the neutral cloud protocol."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from theseus.adapters.aws.access import derive_access_edges
from theseus.adapters.aws.changes import ops_for
from theseus.adapters.aws.cost import monthly_cost
from theseus.adapters.aws.kinds import MODELED_TYPES, PROVIDER, RESOURCE_KINDS
from theseus.adapters.aws.oidc import trust_edges
from theseus.adapters.aws.ops import AddPolicy, AddRole, ops_schema, parse
from theseus.adapters.aws.patch import apply_ops
from theseus.adapters.aws.resources import structural_rows
from theseus.contracts.adapters import Change, CiIdentity, IacResource, Locate, PatchTraits
from theseus.contracts.posture import CostLine
from theseus.contracts.result import GraphRows, PatchOp
from theseus.errors import IngestError

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

    def ops_for(
        self,
        change: Change,
        rows: GraphRows,
        resources: list[IacResource],
        *,
        base_resources: list[IacResource] | None = None,
    ) -> list[PatchOp]:
        """Catalog operations for an evidenced graph change, or none when it cannot be expressed."""
        return ops_for(change, rows, resources, base_resources=base_resources)

    def apply_ops(self, resources: list[IacResource], ops: list[PatchOp]) -> list[IacResource]:
        """Independent patched resources, or PatchError when an operation cannot apply."""
        return apply_ops(resources, ops, account=self.config["account"])

    def patch_traits(self, ops: list[PatchOp]) -> PatchTraits:
        """Whether an added statement uses unrestricted actions, identities or resource scope."""
        broad = False
        for operation in ops:
            parsed = parse(operation)
            if isinstance(parsed, AddRole):
                broad |= any("*" in value or "?" in value for value in parsed.trust_principals)
            if not isinstance(parsed, (AddPolicy, AddRole)):
                continue
            for statement in parsed.statements:
                broad |= any("*" in value or "?" in value for value in statement.actions)
                for resource in statement.resources:
                    parts = resource.split(":", 5)
                    if len(parts) != 6:
                        broad |= "*" in resource or "?" in resource
                        continue
                    # Exact bucket prefixes and a named secret's generated suffix are bounded scopes.
                    header, tail = parts[:5], parts[5]
                    broad |= any("*" in value or "?" in value for value in header)
                    if parts[2] == "s3":
                        bucket, _, prefix = tail.partition("/")
                        broad |= not bucket or "*" in bucket or "?" in bucket
                        broad |= bool(prefix) and (
                            not prefix.rstrip("*") or "*" in prefix.rstrip("*") or "?" in prefix
                        )
                    elif parts[2] == "secretsmanager":
                        name = tail.removeprefix("secret:")
                        bounded = name.endswith("-*") and bool(name[:-2])
                        broad |= "?" in name or "*" in (name[:-2] if bounded else name)
                    else:
                        broad |= "*" in tail or "?" in tail
        return PatchTraits(adds_broad_wildcard=broad)

    def ops_schema(self) -> dict[str, Any]:
        """The schema of the existing typed AWS operation catalog."""
        return ops_schema()

    def monthly_cost(self, resources: list[IacResource]) -> list[CostLine]:
        """List-price estimates from `cost.py`; a type it cannot price is left out."""
        return monthly_cost(resources)
