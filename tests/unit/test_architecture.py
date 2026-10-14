"""Keep the core vendor-neutral (docs/spec/08-core-and-adapters.md). These rules hold for every task."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "theseus"
ADAPTERS = PACKAGE / "adapters"
# Composition roots: the only modules outside adapters/ that may pick an adapter.
ROOTS = {PACKAGE / "cli.py", PACKAGE / "api" / "app.py"}
# Words that name a vendor, an IaC format, a CI system or an SDK. None may appear in contracts/.
VENDOR = re.compile(
    r"\b(aws|amazon|s3|dynamodb|iam|arn|terraform|hcl|github|gitlab|boto3?|gcp|azure)\b", re.I
)


def modules(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


CORE = [p for p in modules(PACKAGE) if ADAPTERS not in p.parents and p not in ROOTS]


@pytest.mark.parametrize("path", CORE, ids=lambda p: p.relative_to(PACKAGE).as_posix())
def test_core_never_imports_an_adapter(path: Path) -> None:
    bad = sorted(m for m in imports(path) if m == "theseus.adapters" or m.startswith("theseus.adapters."))
    assert not bad, f"{path.name} imports {bad}; pass adapters in through Deps instead"


@pytest.mark.parametrize("path", modules(ADAPTERS), ids=lambda p: p.relative_to(PACKAGE).as_posix())
def test_an_adapter_imports_only_contracts_errors_and_itself(path: Path) -> None:
    own = (
        "theseus.adapters." + path.relative_to(ADAPTERS).parts[0]
        if path.parent != ADAPTERS
        else "theseus.adapters"
    )
    allowed = ("theseus.contracts", "theseus.errors", own)
    bad = sorted(
        m
        for m in imports(path)
        if m.startswith("theseus") and not any(m == a or m.startswith(a + ".") for a in allowed)
    )
    assert not bad, f"{path.name} imports {bad}"


@pytest.mark.parametrize(
    "path", modules(PACKAGE / "contracts"), ids=lambda p: p.relative_to(PACKAGE).as_posix()
)
def test_contracts_name_no_vendor(path: Path) -> None:
    hits = sorted({m.group(0) for m in VENDOR.finditer(path.read_text(encoding="utf-8"))})
    assert not hits, f"{path.name} names {hits}; that belongs in an adapter"
