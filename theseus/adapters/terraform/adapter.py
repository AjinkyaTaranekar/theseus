"""Terraform plan, source evidence and verified text edits."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from theseus.adapters.terraform.plan import read_plan
from theseus.adapters.terraform.render import render
from theseus.adapters.terraform.source_index import locate
from theseus.contracts.adapters import IacRead
from theseus.contracts.result import Evidence, PatchOp
from theseus.errors import IngestError

log = logging.getLogger(__name__)


class TerraformAdapter:
    name = "terraform"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._account = config.get("account") if config is not None else None

    def read(self, root: Path, plan: dict[str, Any]) -> IacRead:
        """The plan's resources, unresolved fields and source files relative to the world root."""
        result = read_plan(plan)
        try:
            files = {
                p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
                for p in sorted((root / "terraform").rglob("*.tf"))
                if p.is_file()
            }
        except (OSError, UnicodeError) as exc:
            raise IngestError(f"cannot read source under {root}") from exc
        return result.model_copy(update={"files": files})

    def locate(self, files: dict[str, str], address: str, part: str | None = None) -> Evidence:
        """The source evidence for an address and optional statement Sid."""
        return locate(files, address, part)

    def render(self, files: dict[str, str], ops: list[PatchOp]) -> dict[str, str]:
        """The source files with verified edits, or PatchError when an edit cannot be verified."""
        return render(files, ops, account=self._account)
