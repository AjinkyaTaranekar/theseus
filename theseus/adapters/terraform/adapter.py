"""Terraform plan and source adapter; verified text edits follow in E9."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from theseus.adapters.terraform.plan import read_plan
from theseus.adapters.terraform.source_index import locate
from theseus.contracts.adapters import IacRead
from theseus.contracts.result import Evidence, PatchOp
from theseus.errors import IngestError, PatchError

log = logging.getLogger(__name__)


class TerraformAdapter:
    name = "terraform"

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
        """The edited files once E9 implements verified rendering; currently raises PatchError."""
        raise PatchError("Terraform rendering belongs to E9")
