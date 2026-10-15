"""The code adapter boundary, ready for static code ingestion in C2."""

from __future__ import annotations

import logging

from theseus.contracts.adapters import CodeRead, IacResource
from theseus.contracts.result import GraphRows

log = logging.getLogger(__name__)


class PythonAdapter:
    name = "python"

    def read(self, files: dict[str, str], rows: GraphRows, resources: list[IacResource]) -> CodeRead:
        """Empty code edges, unknowns and skipped-call count until C2 implements static analysis."""
        return CodeRead()
