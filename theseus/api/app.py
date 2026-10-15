"""The FastAPI app: health and the analysis routes. A composition root (docs/spec/08-core-and-adapters.md).

`uvicorn theseus.api.app:app` serves it; importing it never connects to anything.
"""

from __future__ import annotations

import logging

from falkordb import FalkorDB
from fastapi import Depends, FastAPI, Response

from theseus import __version__
from theseus.api import routes
from theseus.config import get_settings
from theseus.errors import GraphError
from theseus.graph.client import get_client, server_version

log = logging.getLogger(__name__)


class _FalkorProbe:
    """Keeps one client between health checks, and drops it when the server stops answering."""

    def __init__(self) -> None:
        self._db: FalkorDB | None = None

    def version(self) -> str | None:
        try:
            if self._db is None:
                self._db = get_client(get_settings())
            return server_version(self._db)
        except GraphError as e:
            log.warning("FalkorDB unavailable: %s", e)
            self._db = None
            return None


_probe = _FalkorProbe()


def falkordb_version() -> str | None:
    """The FalkorDB server version, or None when it cannot be reached. Tests override this dependency."""
    return _probe.version()


def create_app() -> FastAPI:
    """A new app with every route."""
    app = FastAPI(title="Theseus", version=__version__)
    app.include_router(routes.router)

    @app.get("/health")
    def health(response: Response, falkordb: str | None = Depends(falkordb_version)) -> dict[str, str]:
        """{status, falkordb, version}; status 503 while FalkorDB is unreachable."""
        if falkordb is None:
            response.status_code = 503
            return {"status": "degraded", "falkordb": "unreachable", "version": __version__}
        return {"status": "ok", "falkordb": falkordb, "version": __version__}

    return app


app = create_app()
