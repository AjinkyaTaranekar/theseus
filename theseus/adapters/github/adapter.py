"""The CI adapter: GitHub Actions workflow files under `workflows/<org>/<repo>/`."""

from __future__ import annotations

import logging

import yaml

from theseus.adapters.github.status import outages
from theseus.adapters.github.workflows import parse_workflow
from theseus.contracts.adapters import CiIdentity, CiRead
from theseus.contracts.posture import OutageMap
from theseus.contracts.result import EdgeRow, GraphRows, NodeRow

log = logging.getLogger(__name__)


class GithubAdapter:
    name = "github"

    def read(self, files: dict[str, str]) -> CiRead:
        """Workflow and Action nodes, USES edges and unknowns, sorted, and each workflow's OIDC identity."""
        nodes: dict[str, NodeRow] = {}
        edges: list[EdgeRow] = []
        identities: list[CiIdentity] = []
        unknowns: list[str] = []
        versions: dict[str, set[str]] = {}
        for path in sorted(files):
            parts = path.split("/")
            if len(parts) < 4 or parts[0] != "workflows":
                log.info("%s is not a workflow file; skipped", path)
                unknowns.append(f"ci: {path} is not under workflows/<org>/<repo>/")
                continue
            try:
                parsed = parse_workflow(parts[1], parts[2], path, files[path])
            except yaml.YAMLError:
                log.info("%s does not parse; skipped", path)
                unknowns.append(f"ci: {path} does not parse")
                continue
            nodes[parsed.node.id] = parsed.node
            edges.extend(parsed.uses)
            unknowns.extend(parsed.unknowns)
            if parsed.identity is not None:
                identities.append(parsed.identity)
            for use in parsed.lines:
                versions.setdefault(f"action:{use.action}", set()).add(use.version)
        for aid, seen in versions.items():
            # The node carries the version every workflow uses; when they differ, each USES edge says its own.
            props = {"version": next(iter(seen))} if len(seen) == 1 else {}
            nodes[aid] = NodeRow(
                id=aid, name=aid.removeprefix("action:"), labels=["Action", "Node"], props=props
            )
        rows = GraphRows(
            nodes=[nodes[k] for k in sorted(nodes)],
            edges=sorted(edges, key=lambda e: (e.type, e.src, e.dst)),
            unknowns=sorted(set(unknowns)),
        )
        return CiRead(rows=rows, identities=sorted(identities, key=lambda i: i.workflow))

    def outages(self, rows: GraphRows) -> OutageMap:
        """Every workflow runs on GitHub Actions (`status.py`)."""
        return outages(rows)
