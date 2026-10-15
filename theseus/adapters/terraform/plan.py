"""Managed plan resources and the fields that remain unknown until apply."""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from typing import Any

from theseus.contracts.adapters import IacRead, IacResource, UnknownField
from theseus.errors import IngestError

log = logging.getLogger(__name__)

READ_FIELDS = frozenset(
    {
        "name",
        "identifier",
        "domain_name",
        "function_name",
        "service_name",
        "agent_name",
        "family",
        "policy",
        "assume_role_policy",
        "role",
        "user",
        "group",
        "groups",
        "policy_arn",
        "permissions_boundary",
        "tags",
        "environment",
        "task_role_arn",
        "container_definitions",
        "task_definition",
        "bucket",
        "iam_instance_profile",
        "instance_configuration",
        "service_role",
        "role_arn",
        "agent_resource_role_arn",
    }
)
_INDEX = re.compile(r'\[(?:"(?:\\.|[^"\\])*"|[^\]])*\]')
_MODULE_PREFIX = re.compile(r'^(?:module\.[\w-]+(?:\[(?:"(?:\\.|[^"\\])*"|\d+)\])?\.)*')


def unindexed(address: str) -> str:
    """An address without count or for_each instance selectors."""
    return _INDEX.sub("", address)


def _objects(value: Any, context: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        raise IngestError(f"{context} must be a list of objects")
    return value


def _planned(module: Any) -> list[dict[str, Any]]:
    if not isinstance(module, dict):
        raise IngestError("planned module must be an object")
    rows = _objects(module.get("resources", []), "planned resources")[:]
    for child in _objects(module.get("child_modules", []), "child_modules"):
        rows.extend(_planned(child))
    return rows


def _configuration(module: Any, prefix: str = "") -> dict[str, dict[str, Any]]:
    if not isinstance(module, dict):
        raise IngestError("configuration module must be an object")
    result = {}
    for resource in _objects(module.get("resources", []), "configuration resources"):
        address = resource.get("address")
        if not isinstance(address, str):
            raise IngestError("configuration resource has no address")
        result[unindexed(prefix + address)] = resource
    calls = module.get("module_calls", {})
    if not isinstance(calls, dict):
        raise IngestError("module_calls must be an object")
    for name, call in sorted(calls.items()):
        if not isinstance(call, dict):
            raise IngestError("module call must be an object")
        result.update(_configuration(call.get("module", {}), f"{prefix}module.{name}."))
    return result


def _references(value: Any) -> list[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "references":
                if not isinstance(item, list) or any(not isinstance(r, str) for r in item):
                    raise IngestError("expression references must be strings")
                refs.update(item)
            else:
                refs.update(_references(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_references(item))
    return sorted(refs)


def _unknown(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_unknown(v) for v in value.values())
    if isinstance(value, list):
        return any(_unknown(v) for v in value)
    return value is True


def _resolve(
    resource: IacResource,
    field: str,
    references: list[str],
    resources: dict[str, IacResource],
    configurations: dict[str, dict[str, Any]],
) -> str | None:
    # Only a direct name/id expression is safe; a policy assembled from names stays unknown.
    if field in {"policy", "assume_role_policy", "container_definitions", "environment", "tags", "groups"}:
        return None
    targets: set[str] = set()
    prefix = _MODULE_PREFIX.match(resource.address).group()
    bases = {ref.rpartition(".")[0] for ref in references if ref.rpartition(".")[2] in {"name", "id"}}
    if len(bases) != 1:
        return None
    base = next(iter(bases))
    if any(ref not in {base, f"{base}.name", f"{base}.id"} for ref in references):
        return None
    for ref in references:
        base, _, attr = ref.rpartition(".")
        if attr not in {"name", "id"}:
            continue
        target = resources.get(prefix + base)
        if target is None:
            continue
        value = target.values.get("name")
        if not isinstance(value, str) or not value:
            config = configurations.get(unindexed(target.address), {})
            expressions = config.get("expressions", {})
            if not isinstance(expressions, dict) or not isinstance(expressions.get("name", {}), dict):
                raise IngestError(f"{target.address}: name expression must be an object")
            value = expressions.get("name", {}).get("constant_value")
        if isinstance(value, str) and value:
            targets.add(value)
    return next(iter(targets)) if len(targets) == 1 else None


def read_plan(plan: dict[str, Any]) -> IacRead:
    """Sorted managed resources and unresolved fields from a complete plan, without mutating its input."""
    if not isinstance(plan, dict):
        raise IngestError("plan must be an object")
    if plan.get("errored") or plan.get("complete") is False:
        raise IngestError("plan is errored or incomplete")
    planned = plan.get("planned_values")
    if not isinstance(planned, dict) or not isinstance(planned.get("root_module"), dict):
        raise IngestError("plan has no planned_values.root_module")
    resources: dict[str, IacResource] = {}
    for raw in _planned(planned["root_module"]):
        if raw.get("mode", "managed") != "managed":
            continue
        if any(not isinstance(raw.get(f), str) or not raw[f] for f in ("address", "type", "name")):
            raise IngestError("planned resource needs an address, type and name")
        values = raw.get("values", {})
        if not isinstance(values, dict):
            raise IngestError(f"{raw['address']}: values must be an object")
        address = raw["address"]
        if address in resources:
            raise IngestError(f"duplicate planned address {address}")
        resources[address] = IacResource(
            address=address,
            type=raw["type"],
            name=raw["name"],
            provider=str(raw.get("provider_name", "")).rsplit("/", 1)[-1],
            values=deepcopy(values),
        )
    configuration = plan.get("configuration", {})
    if not isinstance(configuration, dict):
        raise IngestError("configuration must be an object")
    configs = _configuration(configuration.get("root_module", {}))
    pending: list[UnknownField] = []
    for change in _objects(plan.get("resource_changes", []), "resource_changes"):
        address = change.get("address")
        if not isinstance(address, str) or not address:
            raise IngestError("resource change needs an address")
        if address not in resources:
            continue
        body = change.get("change", {})
        if not isinstance(body, dict) or not isinstance(body.get("after_unknown", {}), dict):
            raise IngestError(f"{address}: after_unknown must be an object")
        resource = resources[address]
        expressions = configs.get(unindexed(address), {}).get("expressions", {})
        if not isinstance(expressions, dict):
            raise IngestError(f"{address}: expressions must be an object")
        for field, value in sorted(body.get("after_unknown", {}).items()):
            if field not in READ_FIELDS or not _unknown(value):
                continue
            if field == "policy" and resource.type in {"aws_s3_bucket", "aws_secretsmanager_secret"}:
                continue
            refs = _references(expressions.get(field, {}))
            pending.append(UnknownField(address=address, field=field, references=refs))
            resource.values[field] = None
    # Resolve chains only from known values. Cyclic references remain unknown.
    while pending:
        remaining = []
        for item in pending:
            resource = resources[item.address]
            value = _resolve(resource, item.field, item.references, resources, configs)
            if value is None:
                remaining.append(item)
            else:
                resource.values[item.field] = value
        if len(remaining) == len(pending):
            break
        pending = remaining
    return IacRead(
        resources=[resources[a] for a in sorted(resources)],
        unknown_fields=sorted(pending, key=lambda u: (u.address, u.field)),
    )
