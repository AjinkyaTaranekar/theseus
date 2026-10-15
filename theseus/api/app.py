"""The FastAPI app: health and the analysis routes. A composition root (docs/spec/08-core-and-adapters.md).

`uvicorn theseus.api.app:app` serves it. Importing it connects to nothing; starting it connects to FalkorDB
and fails if it cannot, so the API never runs without FalkorDB however it is launched (rule 3).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request, Response

from theseus import __version__
from theseus.api import routes
from theseus.config import get_settings
from theseus.errors import GraphError
from theseus.graph.client import get_client, server_version

log = logging.getLogger(__name__)


def connect_falkordb() -> Any:
    """A FalkorDB client from the environment and .env. Raises GraphError when it cannot connect."""
    return get_client(get_settings())


def falkordb_version(request: Request) -> str | None:
    """The version of the FalkorDB the app connected to at startup, or None if it stopped answering."""
    db = getattr(request.app.state, "falkordb", None)
    if db is None:
        return None
    try:
        return server_version(db)
    except GraphError as e:
        log.warning("FalkorDB stopped answering: %s", e)
        return None


def create_app(connect: Callable[[], Any] = connect_falkordb) -> FastAPI:
    """A new app with every route. `connect` runs at startup; tests pass a stand-in."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            app.state.falkordb = connect()
        except GraphError as e:
            log.error("not starting: %s", e)
            raise
        yield

    app = FastAPI(title="Theseus", version=__version__, lifespan=lifespan)
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
