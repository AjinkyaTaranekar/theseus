"""What a GitHub Actions outage takes down, and GitHub's public status feed read as incidents.

Every workflow runs on GitHub Actions, so an Actions outage takes each one down: whatever it deploys or
writes waits. The feed is githubstatus.com's unresolved incidents (a Statuspage API), whose components name
the part of GitHub that is out.
"""

from __future__ import annotations

import logging
from typing import Any

from theseus.contracts.incident import Effect, Incident, OutageMap, ServiceTag, ServiceTerm
from theseus.contracts.result import GraphRows

log = logging.getLogger(__name__)

PROVIDER = "github"
TERMS = [
    ServiceTerm(
        provider=PROVIDER,
        service="actions",
        name="GitHub Actions",
        aliases=["Actions", "workflows", "workflow runs"],
        provider_names=["GitHub"],
    )
]
# The status page's component names, and the service each one is.
COMPONENTS = {"actions": "actions"}
STATUS: dict[str, Effect] = {
    "degraded_performance": "degraded",
    "partial_outage": "degraded",
    "major_outage": "down",
}
PAGE = "https://www.githubstatus.com"


def outages(rows: GraphRows) -> OutageMap:
    """A tag for every workflow: each runs on GitHub Actions."""
    tags = [
        ServiceTag(node=n.id, provider=PROVIDER, service="actions", why="runs on GitHub Actions")
        for n in rows.nodes
        if "Workflow" in n.labels
    ]
    return OutageMap(tags=sorted(tags, key=lambda t: t.node), terms=TERMS)


def read_status(feed: Any) -> list[Incident]:
    """An incident for each component of an unresolved GitHub incident that Theseus maps, the worst status
    of each, sorted. Anything else is skipped."""
    incidents = feed.get("incidents", []) if isinstance(feed, dict) else []
    found: dict[str, Incident] = {}
    for incident in incidents if isinstance(incidents, list) else []:
        if not isinstance(incident, dict):
            continue
        title = " ".join(str(incident.get("name") or "").split())[:200]
        for component in incident.get("components") or []:
            if not isinstance(component, dict):
                continue
            service = COMPONENTS.get(str(component.get("name", "")).strip().lower())
            effect = STATUS.get(str(component.get("status", "")))
            if service is None or effect is None:
                continue
            old = found.get(service)
            if old is None or (old.severity == "degraded" and effect == "down"):
                link = incident.get("shortlink")
                found[service] = Incident(
                    provider=PROVIDER,
                    service=service,
                    severity=effect,
                    title=title or "GitHub Actions incident",
                    source="feed",
                    url=link if isinstance(link, str) and link.startswith("https://") else PAGE,
                )
    log.info("GitHub status: %d incident(s) in services Theseus maps", len(found))
    return [found[k] for k in sorted(found)]
