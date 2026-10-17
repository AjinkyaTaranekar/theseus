"""Staging to prod: a staging actor's path to sensitive prod data (04-engine.md sections 8 and 16).

Core reasons on the `env` and `sensitive` fields every node carries, never on what the node is called.
"""

from __future__ import annotations

import logging

from theseus.contracts.engine import Analysis, GraphState
from theseus.contracts.result import StagingToProd

log = logging.getLogger(__name__)


def staging_to_prod(analysis: Analysis, state: GraphState) -> list[StagingToProd]:
    """One flag per dangerous path whose actor is in staging and whose target is sensitive prod data,
    each citing its path's ID, sorted by (actor, target)."""
    nodes = {n.id: n for n in state.rows.nodes}
    flags = []
    for path in analysis.dangerous:
        actor, target = nodes.get(path.actor), nodes.get(path.target)
        if actor is None or target is None:
            log.warning("path %s names a node the graph lacks; not checked for staging to prod", path.id)
        elif actor.env == "staging" and target.env == "prod" and target.sensitive:
            flags.append(StagingToProd(actor=path.actor, target=path.target, path_id=path.id))
    return sorted(flags, key=lambda f: (f.actor, f.target))
