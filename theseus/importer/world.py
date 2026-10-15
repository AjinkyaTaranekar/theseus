"""A world at one revision, assembled through the supplied adapters."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from theseus.contracts.adapters import Adapters
from theseus.contracts.engine import World
from theseus.errors import IngestError

log = logging.getLogger(__name__)


def _files(root: Path, directory: str, extensions: set[str]) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted((root / directory).rglob("*"))
        if p.is_file() and p.suffix in extensions
    }


def load_world(root: Path, plan: dict[str, Any], adapters: Adapters) -> World:
    """The world's input files, plan resources, unresolved modeled fields and skipped resource counts."""
    try:
        if not root.is_dir():
            raise IngestError(f"world root does not exist: {root}")
        config = yaml.safe_load((root / "theseus.yaml").read_text(encoding="utf-8"))
        if not isinstance(config, dict) or any(not isinstance(key, str) for key in config):
            raise IngestError("world config must be an object with string keys")
        iac = adapters.iac.read(root, plan)
        ci_files = _files(root, "workflows", {".yml", ".yaml"})
        code_files = _files(root, "services", {".py"})
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise IngestError(f"cannot read world at {root}") from exc
    skipped = Counter(r.type for r in iac.resources if r.type not in adapters.cloud.modeled_types)
    modeled = {r.address for r in iac.resources if r.type in adapters.cloud.modeled_types}
    fields = sorted(
        (u for u in iac.unknown_fields if u.address in modeled), key=lambda u: (u.address, u.field)
    )
    unknowns = [
        f"{u.address}.{u.field}: unknown until apply"
        + (f"; references {', '.join(u.references)}" if u.references else "")
        for u in fields
    ]
    return World(
        root=root.as_posix(),
        iac=adapters.iac.name,
        resources=sorted(iac.resources, key=lambda r: r.address),
        unknown_fields=fields,
        skipped_types=dict(sorted(skipped.items())),
        unknowns=sorted(unknowns),
        iac_files=dict(sorted(iac.files.items())),
        ci_files=ci_files,
        code_files=code_files,
        config=config,
    )
