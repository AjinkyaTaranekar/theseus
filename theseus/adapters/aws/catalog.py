"""The AWS catalog (catalog.yaml): which data resources and workloads Theseus models. See README.md."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from theseus.contracts.result import Access, Category, Contract
from theseus.contracts.schema import WORKLOAD_LABELS
from theseus.errors import IngestError

CATALOG = Path(__file__).with_name("catalog.yaml")
ACTION_ARN_VARS = {"arn"}
RESOURCE_ARN_VARS = {"partition", "region", "account", "name", "name_path", "bucket", "prefix"}
_SLUG = re.compile(r"[a-z][a-z0-9-]*")


def _vars(template: str) -> set[str]:
    return set(re.findall(r"{(\w+)}", template))


def value_at(values: dict[str, Any], path: str) -> Any:
    """The value at a dotted path, such as `tags.Name` or `configuration.0.role_arn`, or None."""
    current: Any = values
    for part in path.split("."):
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


class CatalogAction(Contract):
    """One action, the access it grants, and the ARN forms to test it on. `arns` use {arn}, the node's ARN."""

    action: str
    access: Access
    resource_type: str
    arns: list[str] = Field(default_factory=lambda: ["{arn}"])

    def arns_for(self, node_arn: str) -> list[str]:
        """The ARNs to evaluate this action on, for a node whose ARN is `node_arn`."""
        return [a.format(arn=node_arn) for a in self.arns]


class DataEntry(Contract):
    """One AWS type that holds data (see the field list in README.md)."""

    type: str
    kind: str
    category: Category
    service: str
    resource_type: str
    per: Literal["resource", "location"] = "resource"
    name: str = "name"
    arn: str
    read: list[str | dict[str, Any]] = Field(default_factory=list)
    write: list[str | dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> DataEntry:
        if not _SLUG.fullmatch(self.kind):
            raise ValueError(f"{self.type}: kind {self.kind!r} is not a node ID prefix")
        if bad := _vars(self.arn) - RESOURCE_ARN_VARS:
            raise ValueError(f"{self.type}: unknown ARN variables {sorted(bad)}")
        for a in self.actions():
            if not a.action.startswith(f"{self.service}:"):
                raise ValueError(f"{self.type}: {a.action} is not a {self.service} action")
            for template in a.arns:
                if bad := _vars(template) - ACTION_ARN_VARS:
                    raise ValueError(
                        f"{self.type}: {a.action} uses {sorted(bad)}; action ARNs may use only {{arn}}"
                    )
        return self

    def actions(self) -> list[CatalogAction]:
        """Every action, reads first, in catalog order."""
        out = []
        for access, entries in (("read", self.read), ("write", self.write)):
            for e in entries:
                spec = {"action": e} if isinstance(e, str) else dict(e)
                spec.setdefault("resource_type", self.resource_type)
                out.append(CatalogAction(access=access, **spec))
        return out

    def resource_arn(self, values: dict[str, Any], config: dict[str, Any]) -> str:
        """The representative ARN for one node. `values` holds `name`, or `bucket` and `prefix`."""
        name = str(values.get("name", ""))
        fields = {
            "partition": config.get("partition", "aws"),
            "region": config.get("region", ""),
            "account": config.get("account", ""),
            "name": name,
            "name_path": name.lstrip("/"),
            "bucket": values.get("bucket", ""),
            "prefix": values.get("prefix", ""),
        }
        return self.arn.format(**{k: str(v) for k, v in fields.items()})


class RoleRef(Contract):
    """Where a workload's role is named: `field` on the workload, or on the resource of type `via`
    whose `match` value equals the workload's `join` value."""

    field: str
    via: str | None = None
    join: str | None = None
    match: str | None = None

    @model_validator(mode="after")
    def _check(self) -> RoleRef:
        if (self.via is None) != (self.join is None) or (self.via is None) != (self.match is None):
            raise ValueError("a role found through another resource needs via, join and match together")
        return self


class WorkloadEntry(Contract):
    """One AWS type that runs code as a role (see the field list in README.md)."""

    type: str
    name: str = "name"
    runtime: str
    label: str | None = None
    role: RoleRef

    @model_validator(mode="after")
    def _check(self) -> WorkloadEntry:
        if not _SLUG.fullmatch(self.runtime):
            raise ValueError(f"{self.type}: runtime {self.runtime!r} must be lowercase words joined by -")
        if self.label is not None and self.label not in WORKLOAD_LABELS:
            raise ValueError(f"{self.type}: label {self.label!r} is not one of {WORKLOAD_LABELS}")
        return self


class Catalog(Contract):
    version: Literal[1]
    data: list[DataEntry]
    workloads: list[WorkloadEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> Catalog:
        checks = {
            "data types": [d.type for d in self.data],
            "kinds": [d.kind for d in self.data],
            "workload types": [w.type for w in self.workloads],
        }
        for what, values in checks.items():
            if dupes := sorted({v for v in values if values.count(v) > 1}):
                raise ValueError(f"catalog {what} must be unique; repeated: {dupes}")
        if both := sorted(set(checks["data types"]) & set(checks["workload types"])):
            raise ValueError(f"a type is either data or a workload, not both: {both}")
        return self

    @property
    def by_kind(self) -> dict[str, DataEntry]:
        return {d.kind: d for d in self.data}

    @property
    def types(self) -> set[str]:
        """Every Terraform type the catalog reads: data, workloads, and the types roles are found through."""
        via = {w.role.via for w in self.workloads if w.role.via}
        return {d.type for d in self.data} | {w.type for w in self.workloads} | via


def load_catalog(path: Path = CATALOG) -> Catalog:
    """The catalog at `path`. Raises IngestError when it cannot be read or does not validate."""
    return _load(str(path))


@lru_cache(maxsize=8)
def _load(path: str) -> Catalog:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return Catalog.model_validate(raw)
    except (OSError, yaml.YAMLError, ValueError) as e:
        raise IngestError(f"cannot load the AWS catalog {path}: {e}") from e
