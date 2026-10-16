"""The CI adapter boundary, ready for workflow and OIDC ingestion in FM1."""

from __future__ import annotations

import logging

from theseus.contracts.adapters import CiRead

log = logging.getLogger(__name__)


class GithubAdapter:
    name = "github"

    def read(self, files: dict[str, str]) -> CiRead:
        """Empty CI rows and identities until FM1 implements workflow parsing."""
        return CiRead()
