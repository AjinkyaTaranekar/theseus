"""An outage's blast radius (engine/incident.py): reading a headline, what breaks on a tiny hand-built basis,
and the demo world's main, whose database password lives in Secrets Manager."""

from __future__ import annotations

import pytest

from tests.golden.conftest import deps_for, world
from theseus.contracts.incident import (
    DependencyRoutes,
    Incident,
    OutageBasis,
    RegionTerm,
    ServiceTag,
    ServiceTerm,
)
from theseus.contracts.posture import Dependency, OutageMap
from theseus.engine.incident import blast, read_incident
from theseus.engine.pipeline import actors, config_requirements, prepare_state
from theseus.engine.posture import posture
from theseus.graph.load import load_graph

TERMS = [
    ServiceTerm(provider="cloud", service="fn", name="Functions", aliases=["fn"], provider_names=["Cloud"]),
    ServiceTerm(
        provider="cloud", service="vault", name="Vault", aliases=["secrets"], provider_names=["Cloud"]
    ),
    ServiceTerm(
        provider="cloud", service="tokens", name="Token Service", aliases=["sts"], provider_names=["Cloud"]
    ),
    ServiceTerm(provider="ci", service="runs", name="CI Runs", aliases=["actions"], provider_names=["Hub"]),
    ServiceTerm(
        provider="cloud",
        service="actions",
        name="Cloud Actions",
        aliases=["actions"],
        provider_names=["Cloud"],
    ),
]
REGIONS = [
    RegionTerm(code="eu-west-1", name="Europe (Ireland)", aliases=["Ireland"]),
    RegionTerm(code="us-east-1", name="US East (N. Virginia)", aliases=["Virginia"]),
]


def dep(principal: str, resource: str, access: str = "read") -> Dependency:
    return Dependency(principal=principal, access=access, resource=resource, source="requirement")  # type: ignore[arg-type]


def tag(node: str, service: str, effect: str = "down", region: str | None = "eu-west-1") -> ServiceTag:
    return ServiceTag(
        node=node,
        provider="cloud",
        service=service,
        region=region,
        effect=effect,
        why="runs on it",  # type: ignore[arg-type]
    )


def basis() -> OutageBasis:
    """`api` runs on fn and reads the db through its role and the secret that unlocks it; `job` reads the db
    through its role or a second, direct grant. `web` calls `api`. Everything is in eu-west-1."""
    return OutageBasis(
        tags=[
            tag("workload:api", "fn"),
            tag("secret:key", "vault"),
            tag("role:api", "tokens"),
            tag("role:job", "tokens"),
            tag("db:main", "fn", effect="degraded"),
        ],
        terms=TERMS,
        regions=REGIONS,
        routes=[
            DependencyRoutes(
                dependency=dep("workload:api", "db:main"),
                routes=[["workload:api", "role:api", "secret:key", "db:main"]],
            ),
            DependencyRoutes(
                dependency=dep("workload:job", "db:main"),
                routes=[["workload:job", "role:job", "db:main"], ["workload:job", "role:spare", "db:main"]],
            ),
            DependencyRoutes(
                dependency=dep("workload:job", "secret:key"),
                routes=[["workload:job", "role:job", "secret:key"]],
            ),
            # A code call and a requirement for the same access: one dependency.
            DependencyRoutes(
                dependency=Dependency(
                    principal="workload:job", access="read", resource="secret:key", source="code"
                ),
                routes=[["workload:job", "role:job", "secret:key"]],
            ),
        ],
        requests=[("workload:web", "workload:api")],
        cost={"aws_lambda_function.api": 12.5},
    )


def incident(service: str, region: str | None = None, severity: str = "down") -> Incident:
    return Incident(provider="cloud", service=service, region=region, severity=severity)  # type: ignore[arg-type]


def test_a_service_s_own_node_goes_down_its_dependencies_break_and_its_callers_lose_it() -> None:
    found = blast(basis(), incident("fn"))
    assert [(m.id, m.state) for m in found.matched] == [("workload:api", "down"), ("db:main", "degraded")]
    assert [(b.dependency.principal, b.dependency.resource, b.state) for b in found.broken] == [
        ("workload:api", "db:main", "broken"),
        ("workload:job", "db:main", "degraded"),
    ]
    assert [(a.id, a.state) for a in found.affected] == [
        ("workload:web", "impaired"),
        ("workload:job", "degraded"),
    ]
    assert found.affected[0].why == "calls workload:api, which is down"
    assert found.dependencies == 3


def test_a_dependency_breaks_when_every_route_goes_through_something_down() -> None:
    found = blast(basis(), incident("vault"))
    (broken, secret) = found.broken
    assert (broken.dependency.principal, broken.state, broken.via) == (
        "workload:api",
        "broken",
        ["secret:key"],
    )
    assert broken.why == "every route to it goes through secret:key"
    assert (secret.dependency.principal, secret.why) == ("workload:job", "secret:key is down")
    # job keeps the db: one of its two routes avoids the secret.
    assert ("workload:job", "db:main") not in {
        (b.dependency.principal, b.dependency.resource) for b in found.broken
    }
    assert {a.id for a in found.affected} == {"workload:api", "workload:job", "workload:web"}


def test_one_route_left_keeps_a_dependency_and_the_headline_counts_what_breaks() -> None:
    found = blast(basis(), incident("tokens"))
    cut = {(b.dependency.principal, b.dependency.resource) for b in found.broken if b.state == "broken"}
    assert cut == {("workload:api", "db:main"), ("workload:job", "secret:key")}
    assert (
        found.headline
        == "Token Service down: 2 down, 3 more lose something they need, 2 of 3 dependencies break."
    )


def test_a_degraded_outage_breaks_nothing_and_says_so() -> None:
    found = blast(basis(), incident("fn", severity="degraded"))
    assert {m.state for m in found.matched} == {"degraded"}
    assert {b.state for b in found.broken} == {"degraded"}
    assert found.headline.startswith("Functions degraded: 2 degraded,")
    assert found.headline.endswith("0 of 3 dependencies break.")


def test_another_region_reaches_nothing_and_names_where_this_world_runs() -> None:
    found = blast(basis(), incident("fn", region="us-east-1"))
    assert not found.matched and not found.broken and not found.affected
    assert found.headline == "Nothing here runs on Functions in us-east-1: this world runs in eu-west-1."
    assert blast(basis(), incident("fn", region="eu-west-1")).matched


def test_the_cost_counts_each_matched_address_once() -> None:
    b = basis()
    b.tags[0].address = "aws_lambda_function.api"
    assert blast(b, incident("fn")).monthly_usd == 12.5


@pytest.mark.parametrize(
    ("text", "service", "region", "severity"),
    [
        ("Cloud fn is having downtime in eu-west-1", "fn", "eu-west-1", "down"),
        ("Increased error rates for Functions in Ireland", "fn", "eu-west-1", "degraded"),
        ("secrets unavailable", "vault", None, "down"),
        ("Hub actions are down", "runs", None, "down"),
        ("Cloud actions are down in Virginia", "actions", "us-east-1", "down"),
    ],
)
def test_a_headline_names_its_service_region_and_severity(
    text: str, service: str, region: str | None, severity: str
) -> None:
    found = read_incident(text, TERMS, REGIONS)
    assert found is not None
    assert (found.service, found.region, found.severity, found.source) == (service, region, severity, "text")
    assert found.title == text


def test_a_headline_naming_no_service_is_none_and_words_inside_others_never_match() -> None:
    assert read_incident("Everything is fine", TERMS, REGIONS) is None
    assert read_incident("refund processing", TERMS, REGIONS) is None  # "fn" inside a word
    long = read_incident("fn " + "x" * 400, TERMS, REGIONS)
    assert long is not None and len(long.title) == 200


def test_the_demo_world_s_main_loses_the_customer_db_when_secrets_manager_is_down() -> None:
    deps = deps_for("unused-grant")
    w = world("unused-grant", "base")
    s, _ = prepare_state(w, "main", deps)
    load_graph(deps.store, s)
    maps: list[OutageMap] = [
        deps.adapters.cloud.outages(w.resources, s.rows),
        deps.adapters.ci.outages(s.rows),
    ]
    lines = deps.adapters.cloud.monthly_cost(w.resources)
    b = posture(deps.store, s, config_requirements(w), actors(s), lines, maps).outage
    found = blast(b, read_incident("AWS Secrets Manager is down in eu-west-1", b.terms, b.regions))  # type: ignore[arg-type]
    cut = {(x.dependency.principal, x.dependency.resource) for x in found.broken if x.state == "broken"}
    # The database itself is up; its password is not, and every route to the data goes through it.
    assert {("user:sam-support", "db:customer-db"), ("workload:billing-api", "db:customer-db")} <= cut
    assert "db:customer-db" not in {m.id for m in found.matched}
    assert {a.id: a.state for a in found.affected}["workload:orders-api"] == "impaired"  # calls billing-api
    actions = blast(b, read_incident("GitHub Actions is down", b.terms, b.regions))  # type: ignore[arg-type]
    assert {x.dependency.resource for x in actions.broken} == {
        "db:customer-db",
        "s3://demo-company-files/public/",
        "s3://demo-terraform-state/",
    }
    elsewhere = blast(b, read_incident("Amazon EC2 outage in us-east-1", b.terms, b.regions))  # type: ignore[arg-type]
    assert elsewhere.headline == "Nothing here runs on Amazon EC2 in us-east-1: this world runs in eu-west-1."
