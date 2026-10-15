"""The IAM subset (docs/spec/04-engine.md section 5): statements, matching, evaluation and trust.

Pure functions. Anything outside the subset makes a statement "uncertain", and an uncertain statement that
could decide an answer turns it into UNKNOWN instead of a guess.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field

from theseus.contracts.result import Contract
from theseus.errors import IngestError

log = logging.getLogger(__name__)

ASSUME = "sts:AssumeRole"
UNKNOWN_POLICY = "unknown policy"


class PolicyStatement(Contract):
    """One statement, normalized: lists everywhere, principals by type ("*" for anyone), and every reason the
    subset cannot evaluate it ("NotAction", "NotResource", "NotPrincipal", "unknown policy")."""

    sid: str | None = None
    effect: Literal["Allow", "Deny"]
    actions: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    principals: dict[str, list[str]] | None = None
    condition: dict[str, Any] | None = None
    unsupported: list[str] = Field(default_factory=list)

    @property
    def certain(self) -> bool:
        """True when the subset can evaluate it exactly: no condition and nothing unsupported."""
        return not self.condition and not self.unsupported


class Decision(Contract):
    """What a principal's statements say about one action on one ARN, and the statements that decided it."""

    result: Literal["allow", "deny", "unknown", "none"]
    statements: list[PolicyStatement] = Field(default_factory=list)


class TrustDecision(Contract):
    """How a role's trust policy treats one caller, and the statements that decided it. `naming` holds the
    Allows that name the caller's own ARN, conditional or not: such trust needs no permission from the caller,
    so it can let the caller in even when the caller's own policies say nothing."""

    kind: Literal["explicit", "account", "unknown"] | None
    statements: list[PolicyStatement] = Field(default_factory=list)
    naming: list[PolicyStatement] = Field(default_factory=list)

    @property
    def names_caller(self) -> bool:
        return bool(self.naming)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _principals(value: Any) -> dict[str, list[str]]:
    if value == "*":
        return {"*": ["*"]}
    if isinstance(value, dict):
        return {str(k): _as_list(v) for k, v in value.items()}
    raise IngestError(f"cannot read the principal {value!r}")


def unknown_policy() -> list[PolicyStatement]:
    """A policy not known until apply: Allow everything, but uncertain (04-engine.md section 2)."""
    return [
        PolicyStatement(
            effect="Allow",
            actions=["*"],
            resources=["*"],
            principals={"*": ["*"]},
            unsupported=[UNKNOWN_POLICY],
        )
    ]


def statements(policy: str | dict[str, Any] | None) -> list[PolicyStatement]:
    """The statements of a policy document, given as JSON text or parsed. None means unknown until apply."""
    if policy is None:
        return unknown_policy()
    try:
        doc = json.loads(policy) if isinstance(policy, str) else policy
    except json.JSONDecodeError as e:
        raise IngestError(f"cannot read a policy document: {e}") from e
    raw = doc.get("Statement", []) if isinstance(doc, dict) else []
    out: list[PolicyStatement] = []
    for s in raw if isinstance(raw, list) else [raw]:
        effect = s.get("Effect")
        if effect not in ("Allow", "Deny"):
            raise IngestError(f"a statement's Effect must be Allow or Deny, not {effect!r}")
        unsupported = [k for k in ("NotAction", "NotResource", "NotPrincipal") if k in s]
        principal = s.get("Principal")
        out.append(
            PolicyStatement(
                sid=s.get("Sid"),
                effect=effect,
                actions=_as_list(s.get("Action")),
                resources=_as_list(s.get("Resource")),
                principals=_principals(principal) if principal is not None else None,
                condition=s.get("Condition") or None,
                unsupported=unsupported,
            )
        )
    return out


@lru_cache(maxsize=4096)
def _pattern(pattern: str, ignore_case: bool) -> re.Pattern[str]:
    body = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.compile(body, re.IGNORECASE | re.DOTALL if ignore_case else re.DOTALL)


def glob_match(pattern: str, value: str, ignore_case: bool = False) -> bool:
    """IAM wildcards: `*` matches any run of characters, `/` and `:` included; `?` matches exactly one."""
    return _pattern(pattern, ignore_case).fullmatch(value) is not None


def _could_match(s: PolicyStatement, action: str, arn: str) -> bool:
    """Whether the statement may apply. Actions match without case, resources with it, as IAM does."""
    action_ok = "NotAction" in s.unsupported or any(
        glob_match(a, action, ignore_case=True) for a in s.actions
    )
    resource_ok = "NotResource" in s.unsupported or any(glob_match(r, arn) for r in s.resources)
    return action_ok and resource_ok


def evaluate(stmts: list[PolicyStatement], action: str, arn: str) -> Decision:
    """deny, allow, unknown or none for `action` on `arn` (04-engine.md section 5).

    An unconditional matching Deny wins. Otherwise an unconditional matching Allow allows, unless a Deny
    that is conditional or unsupported could also match. An uncertain Allow can only add access, so it never
    weakens a definite allow. Only uncertain Allows, or an Allow facing an uncertain Deny, give unknown.
    """
    matching = [s for s in stmts if _could_match(s, action, arn)]
    sure_deny = [s for s in matching if s.effect == "Deny" and s.certain]
    if sure_deny:
        return Decision(result="deny", statements=sure_deny)
    sure_allow = [s for s in matching if s.effect == "Allow" and s.certain]
    maybe_deny = [s for s in matching if s.effect == "Deny" and not s.certain]
    if sure_allow:
        if maybe_deny:
            return Decision(
                result="unknown", statements=[s for s in matching if s in sure_allow + maybe_deny]
            )
        return Decision(result="allow", statements=sure_allow)
    maybe_allow = [s for s in matching if s.effect == "Allow" and not s.certain]
    if maybe_allow:
        return Decision(result="unknown", statements=[s for s in matching if s in maybe_allow + maybe_deny])
    return Decision(result="none")


def _trust_level(s: PolicyStatement, caller_arn: str | None, account: str) -> str | None:
    """How a trust statement names the caller: "explicit", "account", "maybe" (cannot tell), or None."""
    if "NotPrincipal" in s.unsupported or UNKNOWN_POLICY in s.unsupported:
        return "maybe"
    named = (s.principals or {}).get("AWS", []) + (s.principals or {}).get("*", [])
    if caller_arn is not None and caller_arn in named:
        return "explicit"
    if "*" in named or account in named or f"arn:aws:iam::{account}:root" in named:
        return "account"
    return None


def trust_kind(trust: list[PolicyStatement], caller_arn: str | None, account: str) -> TrustDecision:
    """explicit, account, unknown or None: whether a role's trust policy lets this caller assume it.

    `caller_arn` is None for a group, which only the account form can match. `Principal = "*"` counts as
    account when unconditional. Web-identity and service principals are not callers here (OIDC is FM1's).
    Whatever the kind, `naming` lists the Allows that name the caller's ARN, unless a certain Deny removes
    the trust.
    """
    relevant: list[tuple[PolicyStatement, str]] = []
    for s in trust:
        action_ok = "NotAction" in s.unsupported or any(
            glob_match(a, ASSUME, ignore_case=True) for a in s.actions
        )
        level = _trust_level(s, caller_arn, account) if action_ok else None
        if level is not None:
            relevant.append((s, level))
    if any(s.effect == "Deny" and s.certain and level != "maybe" for s, level in relevant):
        return TrustDecision(kind=None, statements=[s for s, _ in relevant if s.effect == "Deny"])
    maybe_deny = [s for s, level in relevant if s.effect == "Deny"]
    naming = [s for s, level in relevant if s.effect == "Allow" and level == "explicit"]
    sure = [(s, level) for s, level in relevant if s.effect == "Allow" and s.certain and level != "maybe"]
    if sure:
        best = "explicit" if any(level == "explicit" for _, level in sure) else "account"
        deciding = [s for s, level in sure if level == best]
        if maybe_deny:
            return TrustDecision(kind="unknown", statements=deciding + maybe_deny, naming=naming)
        return TrustDecision(kind=best, statements=deciding, naming=naming)
    maybe_allow = [s for s, _ in relevant if s.effect == "Allow"]
    if maybe_allow:
        return TrustDecision(kind="unknown", statements=maybe_allow + maybe_deny, naming=naming)
    return TrustDecision(kind=None)
