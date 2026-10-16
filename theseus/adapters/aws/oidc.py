"""GitHub OIDC trust on IAM roles: which CI identities may assume which roles (04-engine.md section 6).

Every condition key must be `token.actions.githubusercontent.com:aud` or `:sub`, under `StringEquals` (exact)
or `StringLike` (IAM wildcards); anything else is `unknown`. `aud` must accept `sts.amazonaws.com`. Any
failing test is `no`. With no `sub` test the result is `yes-any-repo`.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from theseus.adapters.aws.iam import PolicyStatement, glob_match, statements
from theseus.contracts.adapters import CiIdentity, IacResource, Locate
from theseus.contracts.result import EdgeRow
from theseus.errors import IngestError

log = logging.getLogger(__name__)

Match = Literal["yes", "yes-any-repo", "no", "unknown"]
GITHUB_HOST = "token.actions.githubusercontent.com"
ISSUER = f"https://{GITHUB_HOST}"
WEB_IDENTITY = "sts:AssumeRoleWithWebIdentity"
AUDIENCE = "sts.amazonaws.com"
KEYS = {f"{GITHUB_HOST}:aud": "aud", f"{GITHUB_HOST}:sub": "sub"}
OPERATORS = {"StringEquals": False, "StringLike": True}  # whether the operator takes wildcards
RANK = {"no": 0, "unknown": 1, "yes": 2}


def _provider_host(principal: str) -> str | None:
    """The OIDC provider's host in an `oidc-provider/<host>` ARN."""
    _, sep, host = principal.partition(":oidc-provider/")
    return host if sep else None


def oidc_statements(trust: list[PolicyStatement]) -> list[PolicyStatement]:
    """The trust statements about GitHub's OIDC provider and web-identity assumption, in policy order."""
    out = []
    for s in trust:
        federated = (s.principals or {}).get("Federated", [])
        if not any(_provider_host(p) == GITHUB_HOST for p in federated):
            continue
        if "NotAction" in s.unsupported or any(
            glob_match(a, WEB_IDENTITY, ignore_case=True) for a in s.actions
        ):
            out.append(s)
    return out


def _values(value: object) -> list[str] | None:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    return None


def oidc_allows(statement: PolicyStatement, sub: str, aud: str = AUDIENCE) -> Match:
    """Whether the statement's condition admits a token with this `sub` and `aud`."""
    if statement.unsupported:
        return "unknown"
    tested = False
    for operator, block in (statement.condition or {}).items():
        if operator not in OPERATORS or not isinstance(block, dict):
            return "unknown"
        for key, raw in block.items():
            name = KEYS.get(str(key).lower())
            allowed = _values(raw)
            if name is None or allowed is None:
                return "unknown"
            value = sub if name == "sub" else aud
            wildcards = OPERATORS[operator]
            if not any(glob_match(p, value) if wildcards else p == value for p in allowed):
                return "no"
            tested = tested or name == "sub"
    return "yes" if tested else "yes-any-repo"


def _admits(trust: list[PolicyStatement], sub: str) -> tuple[str, PolicyStatement | None]:
    """ "yes", "unknown" or "no" for one sub, and the Allow statement that decided it."""
    denies = {
        "no" if r == "no" else "unknown" if r == "unknown" else "yes"
        for r in (oidc_allows(s, sub) for s in trust if s.effect == "Deny")
    }
    if "yes" in denies:
        return "no", None
    best, decided = "no", None
    for s in (s for s in trust if s.effect == "Allow"):
        result = oidc_allows(s, sub)
        level = "no" if result == "no" else "unknown" if result == "unknown" or "unknown" in denies else "yes"
        if RANK[level] > RANK[best]:
            best, decided = level, s
    return best, decided


def trust_edges(
    resources: list[IacResource], identities: list[CiIdentity], locate: Locate
) -> tuple[list[EdgeRow], list[str]]:
    """TRUSTS edges from each GitHub workflow to each role its OIDC token may assume, sorted by (src, dst),
    and the unknowns. A configured edge when an Allow admits one of its subs and no Deny might refuse it; an
    unknown edge when the answer rests on a condition outside the supported subset; no edge otherwise."""
    edges: list[EdgeRow] = []
    unknowns: list[str] = []
    github = [i for i in identities if i.issuer == ISSUER and i.subjects]
    for role in sorted((r for r in resources if r.type == "aws_iam_role"), key=lambda r: r.address):
        name, policy = role.values.get("name"), role.values.get("assume_role_policy")
        if not isinstance(name, str) or policy is None:
            continue
        try:
            trust = oidc_statements(statements(json.loads(policy) if isinstance(policy, str) else policy))
        except (IngestError, json.JSONDecodeError):
            log.info("%s: trust policy unreadable; no TRUSTS edges", role.address)
            unknowns.append(f"{role.address}: trust policy unreadable; no TRUSTS edges from it")
            continue
        for identity in github if trust else []:
            best, decided, matched = "no", None, ""
            for sub in identity.subjects:
                level, statement = _admits(trust, sub)
                if RANK[level] > RANK[best]:
                    best, decided, matched = level, statement, sub
            if decided is None:
                continue
            workflow = identity.workflow.removeprefix("workflow:")
            kind = "configured" if best == "yes" else "unknown"
            note = f"{workflow} presents {matched}"
            if kind == "unknown":
                note += "; a condition is outside the supported subset"
                unknowns.append(
                    f"TRUSTS: {identity.workflow} -> role:{name}: condition outside the supported subset"
                )
            evidence = locate(role.address, decided.sid).model_copy(update={"note": note})
            edges.append(
                EdgeRow(
                    eid="",
                    type="TRUSTS",
                    src=identity.workflow,
                    dst=f"role:{name}",
                    kind=kind,
                    evidence=[evidence],
                )
            )
    return sorted(edges, key=lambda e: (e.src, e.dst)), sorted(set(unknowns))
