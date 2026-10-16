"""The code adapter: Python service code read with `ast` (04-engine.md section 7)."""

from __future__ import annotations

import logging

from theseus.adapters.python.code import read_code
from theseus.contracts.adapters import CodeRead, IacResource
from theseus.contracts.result import GraphRows

log = logging.getLogger(__name__)


class PythonAdapter:
    name = "python"

    def read(self, files: dict[str, str], rows: GraphRows, resources: list[IacResource]) -> CodeRead:
        """CALLS, REQUESTS and HAS_ENV edges from the service code, its unknowns and the calls it skipped."""
        return read_code(files, rows, resources)
