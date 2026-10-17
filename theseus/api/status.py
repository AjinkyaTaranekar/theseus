"""Providers' public status feeds, fetched for the incidents view (nightly, and on demand from the dashboard).

The URLs and the readers come from the composition root, which knows the adapters; this module only fetches.
A feed's text is untrusted: a reader keeps the service codes, regions and statuses it maps, and a title
that is shown, never followed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx

from theseus.contracts.incident import Incident

log = logging.getLogger(__name__)

Reader = Callable[[Any], list[Incident]]
TIMEOUT = 20.0


def fetch_feeds(
    feeds: dict[str, tuple[str, Reader]], client: httpx.Client | None = None
) -> tuple[list[Incident], list[str]]:
    """Every feed's current incidents, and a line for each feed that could not be read; sorted by feed."""
    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
    found: list[Incident] = []
    errors: list[str] = []
    try:
        for name in sorted(feeds):
            url, reader = feeds[name]
            try:
                response = http.get(url, headers={"Accept": "application/json"})
                response.raise_for_status()
                body = json.loads(response.text.lstrip("﻿"))
            except (httpx.HTTPError, ValueError) as e:
                log.warning("status feed %s could not be read: %s", name, e)
                errors.append(f"{name}: could not be read")
                continue
            found.extend(reader(body))
    finally:
        if own:
            http.close()
    return found, errors
