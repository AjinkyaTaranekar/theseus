"""GitHub Actions workflow files into Workflow and Action nodes, USES edges and each one's OIDC identity.

The `sub` rules are 04-engine.md section 6, "Workflow `sub` values": a job with `environment: X` presents only
the environment's sub; otherwise `push` gives one per listed branch (default `main`), and `pull_request` or
`pull_request_target` gives the pull-request sub. Only jobs that can request an ID token count.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import yaml

from theseus.contracts.adapters import CiIdentity
from theseus.contracts.result import EdgeRow, Evidence, NodeRow

log = logging.getLogger(__name__)

ISSUER = "https://token.actions.githubusercontent.com"
DEFAULT_BRANCH = "main"
PR_EVENTS = ("pull_request", "pull_request_target")


@dataclass
class Use:
    """One `uses:` line: the action it names, at which ref, on which line, in which job."""

    action: str
    version: str
    line: int
    job: str


@dataclass
class ParsedWorkflow:
    node: NodeRow
    identity: CiIdentity | None
    uses: list[EdgeRow] = field(default_factory=list)
    lines: list[Use] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)


def _action(ref: str) -> tuple[str, str] | None:
    """`owner/repo` and the ref of a `uses:` value; None for a local path or a Docker image."""
    if ref.startswith(("./", "docker://")) or "@" not in ref:
        return None
    name, _, version = ref.partition("@")
    parts = name.split("/")
    if len(parts) < 2 or not all(parts[:2]):
        return None
    return f"{parts[0]}/{parts[1]}", version


def _scalar(node: yaml.Node | None) -> str | None:
    return node.value if isinstance(node, yaml.ScalarNode) else None


def _mapping(node: yaml.Node | None) -> list[tuple[yaml.Node, yaml.Node]]:
    return list(node.value) if isinstance(node, yaml.MappingNode) else []


def _uses_lines(text: str) -> list[Use]:
    """Every `uses:` in the jobs, a step's or a reusable workflow job's, with its line, in file order."""
    found: list[Use] = []
    root = yaml.compose(text)
    jobs = next((v for k, v in _mapping(root) if _scalar(k) == "jobs"), None)
    for job_key, job in _mapping(jobs):
        job_id = _scalar(job_key) or ""
        for key, value in _mapping(job):
            if _scalar(key) == "uses" and (ref := _scalar(value)) and (named := _action(ref)):
                found.append(Use(*named, value.start_mark.line + 1, job_id))
            if _scalar(key) == "steps" and isinstance(value, yaml.SequenceNode):
                for step in value.value:
                    for sk, sv in _mapping(step):
                        if _scalar(sk) == "uses" and (ref := _scalar(sv)) and (named := _action(ref)):
                            found.append(Use(*named, sv.start_mark.line + 1, job_id))
    return sorted(found, key=lambda u: u.line)


def _triggers(doc: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML reads the bare key `on` as True.
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {str(e): None for e in on}
    return {str(k): v for k, v in on.items()} if isinstance(on, dict) else {}


def _can_request_token(permissions: Any) -> bool:
    if permissions == "write-all":
        return True
    return isinstance(permissions, dict) and permissions.get("id-token") == "write"


def _job_subs(
    org: str, repo: str, job: dict[str, Any], triggers: dict[str, Any]
) -> tuple[set[str], str | None]:
    """The subs one token-requesting job presents, and a reason when one cannot be known."""
    environment = job.get("environment")
    name = environment.get("name") if isinstance(environment, dict) else environment
    if name is not None:
        if not isinstance(name, str) or "${{" in name:
            return set(), "its environment is an expression"
        return {f"repo:{org}/{repo}:environment:{name}"}, None
    subs: set[str] = set()
    if "push" in triggers:
        push = triggers["push"] if isinstance(triggers["push"], dict) else {}
        branches = push.get("branches") or [DEFAULT_BRANCH]
        subs |= {f"repo:{org}/{repo}:ref:refs/heads/{b}" for b in branches if isinstance(b, str)}
    if any(e in triggers for e in PR_EVENTS):
        subs.add(f"repo:{org}/{repo}:pull_request")
    return subs, None


def parse_workflow(org: str, repo: str, path: str, text: str) -> ParsedWorkflow:
    """One workflow's node, its OIDC identity (None when no job can request an ID token), and its USES edges.

    Raises yaml.YAMLError when the file does not parse; GithubAdapter.read turns that into an unknown.
    """
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        raise yaml.YAMLError("a workflow must be a mapping")
    wid = f"workflow:{org}/{repo}/{path.split('/', 3)[3] if path.count('/') >= 3 else path}"
    triggers = _triggers(doc)
    jobs = doc.get("jobs") if isinstance(doc.get("jobs"), dict) else {}
    unknowns: list[str] = []
    id_token = False
    subs: set[str] = set()
    for job_id, job in sorted(jobs.items(), key=lambda kv: str(kv[0])):
        job = job if isinstance(job, dict) else {}
        permissions = job["permissions"] if "permissions" in job else doc.get("permissions")
        if not _can_request_token(permissions):
            continue
        id_token = True
        job_subs, reason = _job_subs(org, repo, job, triggers)
        if reason:
            unknowns.append(f"ci: {path} job {job_id}: {reason}; its sub is unknown")
        subs |= job_subs
    if id_token and not subs and not unknowns:
        unknowns.append(f"ci: {path} can request an ID token, but no trigger gives it a known sub")
    node = NodeRow(
        id=wid,
        name=wid.removeprefix(f"workflow:{org}/"),
        labels=["Node", "Principal", "Workflow"],
        props={"repo": f"{org}/{repo}", "file": path, "subs": sorted(subs), "id_token": id_token},
    )
    identity = CiIdentity(workflow=wid, issuer=ISSUER, subjects=sorted(subs)) if id_token else None
    lines = _uses_lines(text)
    by_action: dict[str, list[Use]] = {}
    for use in lines:
        by_action.setdefault(use.action, []).append(use)
    edges = []
    for action, uses in sorted(by_action.items()):
        versions = sorted({u.version for u in uses})
        if len(versions) > 1:
            unknowns.append(f"ci: {path} uses {action} at more than one version ({', '.join(versions)})")
        edges.append(
            EdgeRow(
                eid="",
                type="USES",
                src=wid,
                dst=f"action:{action}",
                kind="configured",
                evidence=[Evidence(address=path, part=u.job, file=path, line=u.line) for u in uses],
                props={"version": uses[0].version, "line": uses[0].line},
            )
        )
    return ParsedWorkflow(node=node, identity=identity, uses=edges, lines=lines, unknowns=unknowns)
