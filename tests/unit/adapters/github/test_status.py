"""What a GitHub Actions outage takes down (adapters/github/status.py), and githubstatus.com's feed."""

from __future__ import annotations

from theseus.adapters.github.adapter import GithubAdapter
from theseus.adapters.github.status import read_status
from theseus.contracts.result import GraphRows, NodeRow


def test_every_workflow_runs_on_actions_and_nothing_else_is_tagged() -> None:
    rows = GraphRows(
        nodes=[
            NodeRow(
                id="workflow:o/r/deploy.yml", name="deploy.yml", labels=["Node", "Principal", "Workflow"]
            ),
            NodeRow(id="action:actions/checkout", name="actions/checkout", labels=["Action", "Node"]),
        ]
    )
    found = GithubAdapter().outages(rows)
    assert [(t.node, t.provider, t.service, t.region, t.effect) for t in found.tags] == [
        ("workflow:o/r/deploy.yml", "github", "actions", None, "down")
    ]
    assert [(t.service, t.name) for t in found.terms] == [("actions", "GitHub Actions")]


def test_an_unresolved_actions_incident_is_read_at_its_worst_component_status() -> None:
    feed = {
        "incidents": [
            {
                "name": "Disruption with some GitHub services",
                "shortlink": "https://stspg.io/abc",
                "components": [
                    {"name": "Actions", "status": "partial_outage"},
                    {"name": "Pages", "status": "major_outage"},
                ],
            },
            {"name": "Actions down", "components": [{"name": "Actions", "status": "major_outage"}]},
            {"name": "Slow API", "components": [{"name": "API Requests", "status": "degraded_performance"}]},
        ]
    }
    (found,) = read_status(feed)
    assert (found.provider, found.service, found.severity, found.title) == (
        "github",
        "actions",
        "down",
        "Actions down",
    )
    assert found.url == "https://www.githubstatus.com"  # this one had no shortlink
    assert read_status({"incidents": []}) == [] and read_status(["x"]) == []
