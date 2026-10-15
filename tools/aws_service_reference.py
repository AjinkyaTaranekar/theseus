#!/usr/bin/env python3
"""Refresh tests/data/aws_service_reference.json from AWS's service reference, for the actions the AWS
catalog (theseus/adapters/aws/catalog.yaml) names, plus sts:AssumeRole.

The snapshot is what tests/contract/test_aws_catalog.py checks the catalog against, offline. Run this after
changing the catalog, with the project's environment (it needs PyYAML):

    .venv/bin/python tools/aws_service_reference.py        # Windows: .venv\\Scripts\\python

Source: https://docs.aws.amazon.com/service-authorization/latest/reference/service-reference.html
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "theseus" / "adapters" / "aws" / "catalog.yaml"
OUT = ROOT / "tests" / "data" / "aws_service_reference.json"
BASE = "https://servicereference.us-east-1.amazonaws.com/v1"
EXTRA = {"sts": {"AssumeRole": "role"}}  # actions outside the catalog: action name -> resource type


def wanted() -> dict[str, dict[str, set[str]]]:
    """service -> action name -> the resource types the catalog applies it to."""
    out: dict[str, dict[str, set[str]]] = {}
    for entry in yaml.safe_load(CATALOG.read_text(encoding="utf-8"))["data"]:
        for access in ("read", "write"):
            for item in entry.get(access, []):
                spec = {"action": item} if isinstance(item, str) else item
                service, name = spec["action"].split(":", 1)
                rtype = spec.get("resource_type", entry["resource_type"])
                out.setdefault(service, {}).setdefault(name, set()).add(rtype)
        out.setdefault(entry["service"], {})
    for service, actions in EXTRA.items():
        for name, rtype in actions.items():
            out.setdefault(service, {}).setdefault(name, set()).add(rtype)
    return out


def entry_types() -> dict[str, set[str]]:
    """service -> the resource types catalog entries are, whether or not any action names them."""
    out: dict[str, set[str]] = {}
    for entry in yaml.safe_load(CATALOG.read_text(encoding="utf-8"))["data"]:
        out.setdefault(entry["service"], set()).add(entry["resource_type"])
    return out


def trim(doc: dict[str, Any], actions: dict[str, set[str]], extra_types: set[str]) -> dict[str, Any]:
    """What the tests need: each wanted action's flags and resource types, and those types' ARN formats."""
    by_name = {a["Name"]: a for a in doc.get("Actions", [])}
    kept: dict[str, Any] = {}
    types: set[str] = set(extra_types)
    for name in sorted(actions):
        a = by_name.get(name)
        if a is None:
            continue
        props = a.get("Annotations", {}).get("Properties", {})
        resources = sorted(r["Name"] for r in a.get("Resources", []))
        kept[name] = {
            "write": bool(props.get("IsWrite")),
            "list": bool(props.get("IsList")),
            "permissions": bool(props.get("IsPermissionManagement")),
            "tagging": bool(props.get("IsTaggingOnly")),
            "resources": resources,
        }
        types |= set(resources) | actions[name]
    formats = {
        r["Name"]: sorted(r.get("ARNFormats", [])) for r in doc.get("Resources", []) if r["Name"] in types
    }
    return {"version": doc.get("Version"), "actions": kept, "resources": dict(sorted(formats.items()))}


def fetch(service: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{BASE}/{service}/{service}.json", timeout=60) as r:
        return json.load(r)


def main() -> None:
    types = entry_types()
    snapshot = {
        service: trim(fetch(service), actions, types.get(service, set()))
        for service, actions in sorted(wanted().items())
    }
    missing = [
        f"{s}:{a}" for s, actions in wanted().items() for a in actions if a not in snapshot[s]["actions"]
    ]
    OUT.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {sum(len(s['actions']) for s in snapshot.values())} actions")
    if missing:
        print("not in AWS's service reference: " + ", ".join(missing), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
