"""Each review's graph page (05-contracts.md, "The review page"): what a reviewer opens from the comment to
see the graphs Theseus reasoned on. The result is kept next to the graphs in the store, and the graphs are
read from the store when the page asks, never from a copy.

The page shows a private repo's infrastructure, so its link carries a signature only the backend can make: an
HMAC of the repo and PR number with THESEUS_TOKEN. Anyone who can read the PR comment can open it; anyone else
gets a 404.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Protocol
from urllib.parse import quote

from theseus.agent.labels import severity
from theseus.agent.render import verdict
from theseus.config import Settings
from theseus.contracts.posture import PostureReport
from theseus.contracts.result import AnalysisResult
from theseus.errors import GraphError

log = logging.getLogger(__name__)

SIGNATURE_CHARS = 32


class ReviewStore(Protocol):
    """The two things the page needs from a store, besides the graphs it already holds."""

    def view(self, graph: str) -> dict[str, list[dict[str, Any]]]: ...
    def put_doc(self, key: str, text: str) -> None: ...
    def get_doc(self, key: str) -> str | None: ...
    def docs(self, prefix: str) -> list[str]: ...
    def list_graphs(self) -> list[str]: ...


def key(repo: str, number: int) -> str:
    return f"review:{repo}#{number}"


def finding_key(finding_id: str) -> str:
    return f"finding:{finding_id}"


def sign(settings: Settings, doc_key: str) -> str | None:
    """A page link's signature for this document, or None when THESEUS_TOKEN is not set."""
    if settings.theseus_token is None:
        return None
    secret = settings.theseus_token.get_secret_value().encode()
    return hmac.new(secret, doc_key.encode(), hashlib.sha256).hexdigest()[:SIGNATURE_CHARS]


def signature(settings: Settings, repo: str, number: int) -> str | None:
    """The link's signature for this PR, or None when THESEUS_TOKEN is not set."""
    return sign(settings, key(repo, number))


def signed_key(settings: Settings, doc_key: str, given: str | None) -> bool:
    expected = sign(settings, doc_key)
    return expected is not None and given is not None and hmac.compare_digest(given, expected)


def signed(settings: Settings, repo: str, number: int, given: str | None) -> bool:
    return signed_key(settings, key(repo, number), given)


def page_url(settings: Settings, repo: str, number: int) -> str | None:
    """The page's public link for the comment, or None without a public hostname or THESEUS_TOKEN."""
    sig = signature(settings, repo, number)
    if not settings.domain or sig is None:
        return None
    return f"https://{settings.domain}/reviews/{quote(repo)}/{number}?k={sig}"


def save(
    store: ReviewStore,
    repo: str,
    number: int,
    shas: tuple[str, str],
    world_root: str,
    result: AnalysisResult,
    title: str = "",
    updated_at: str = "",
) -> None:
    """Keeps the PR's newest result for its page, with its verdict and the base and head commits and world
    root its links need; the PR's title and when it was reviewed are for the dashboard."""
    base_sha, head_sha = shas
    doc = {
        "repo": repo,
        "number": number,
        "title": title,
        "updated_at": updated_at,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "world_root": world_root,
        "verdict": verdict(result).model_dump(),
        "result": result.model_dump(mode="json", by_alias=True),
    }
    store.put_doc(key(repo, number), json.dumps(doc, sort_keys=True))
    log.info("%s#%d: kept the review of %s for its page", repo, number, head_sha[:7])


def finding_url(settings: Settings, finding_id: str) -> str | None:
    """A finding page's public link, or None without a public hostname or THESEUS_TOKEN."""
    sig = sign(settings, finding_key(finding_id))
    if not settings.domain or sig is None:
        return None
    return f"https://{settings.domain}/findings/{quote(finding_id)}?k={sig}"


def save_finding(
    store: ReviewStore,
    repo: str,
    world_root: str,
    result: AnalysisResult,
    sha: str = "main",
    updated_at: str = "",
) -> None:
    """Keeps a finding's newest result for its page, its files linked at `sha` (a fixture's on main)."""
    finding_id = (result.finding or {})["id"]
    doc = {
        "kind": "finding",
        "id": finding_id,
        "repo": repo,
        "updated_at": updated_at,
        "base_sha": sha,
        "head_sha": sha,
        "world_root": world_root,
        "verdict": verdict(result).model_dump(),
        "result": result.model_dump(mode="json", by_alias=True),
    }
    store.put_doc(finding_key(finding_id), json.dumps(doc, sort_keys=True))
    log.info("finding %s: kept for its page", finding_id)


def page_doc(store: ReviewStore, doc_key: str) -> dict[str, Any] | None:
    """A page's newest result and its graphs as the store holds them now, or None if there is none. A
    graph the store no longer holds is left out."""
    text = store.get_doc(doc_key)
    if text is None:
        return None
    doc: dict[str, Any] = json.loads(text)
    graphs: dict[str, Any] = {}
    for side, name in (doc["result"].get("graphs") or {}).items():
        try:
            graphs[side] = {"name": name, **store.view(name)}
        except GraphError as e:  # deleted since: the page shows what is left
            log.warning("%s: graph %s is gone: %s", doc_key, name, e)
    return {**doc, "graphs": graphs}


def page_data(store: ReviewStore, repo: str, number: int) -> dict[str, Any] | None:
    """The PR's newest result and both graphs as the store holds them now, or None if it was never
    reviewed."""
    return page_doc(store, key(repo, number))


# The organisation's dashboard (issues O1 to O5) ------------------------------------------------------------


def posture_key(repo: str) -> str:
    return f"posture:{repo}"


def dashboard_key(repo: str) -> str:
    return f"dashboard:{repo}"


def history_key(repo: str) -> str:
    return f"history:{repo}"


def org_key(owner: str) -> str:
    return f"dashboard:org:{owner.lower()}"


def org_url(settings: Settings, owner: str) -> str | None:
    """The organisation dashboard's public link, or None without a public hostname or THESEUS_TOKEN."""
    sig = sign(settings, org_key(owner))
    if not settings.domain or sig is None:
        return None
    return f"https://{settings.domain}/org/{quote(owner)}?k={sig}"


HISTORY_KEPT = 365  # posture runs kept per repo: a year of nightly runs


def snapshot(report: PostureReport, sha: str, trigger: str, at: str) -> dict[str, Any]:
    """The numbers one posture run adds to the repo's history."""
    posture = report.posture
    return {
        "at": at,
        "sha": sha,
        "trigger": trigger,
        "dangerous": len(report.scan.unchanged),
        "actors_exposed": len({p.actor for p in report.scan.unchanged}),
        "unused_grants": len(report.scan.unused_grants),
        "single_points": len(posture.single_points),
        "articulation": len(posture.articulation),
        "findings": len(report.findings),
        "monthly_usd": posture.cost.monthly_usd,
        "nodes": report.scan.coverage.nodes,
        "edges": report.scan.coverage.edges,
    }


def dashboard_url(settings: Settings, repo: str) -> str | None:
    """The dashboard's public link, or None without a public hostname or THESEUS_TOKEN."""
    sig = sign(settings, dashboard_key(repo))
    if not settings.domain or sig is None:
        return None
    return f"https://{settings.domain}/dashboard/{quote(repo)}?k={sig}"


def save_posture(
    store: ReviewStore,
    repo: str,
    sha: str,
    world_root: str,
    report: PostureReport,
    trigger: str,
    updated_at: str,
) -> None:
    """Keeps `main`'s newest posture for the dashboard, and each finding it raised for its own page."""
    doc = {
        "repo": repo,
        "sha": sha,
        "world_root": world_root,
        "trigger": trigger,
        "updated_at": updated_at,
        "scan": report.scan.model_dump(mode="json", by_alias=True),
        "posture": report.posture.model_dump(mode="json"),
        "findings": sorted((f.finding or {}).get("id", "") for f in report.findings),
    }
    store.put_doc(posture_key(repo), json.dumps(doc, sort_keys=True))
    history = (_load(store, history_key(repo)) or {}).get("runs", [])
    history = [*history, snapshot(report, sha, trigger, updated_at)][-HISTORY_KEPT:]
    store.put_doc(history_key(repo), json.dumps({"repo": repo, "runs": history}, sort_keys=True))
    for finding in report.findings:
        save_finding(store, repo, world_root, finding, sha=sha, updated_at=updated_at)
    log.info("%s: kept the posture of %s (%s)", repo, sha[:7], trigger)


def mark_contained(store: ReviewStore, finding_id: str, pr: str, pr_number: int, issue: str | None) -> None:
    """Records on the finding's document where its containment PR and rotate issue are."""
    doc = _load(store, finding_key(finding_id))
    if doc is None:
        log.warning("finding %s: no document to record its containment on", finding_id)
        return
    doc["containment"] = {"pr": pr, "pr_number": pr_number, "issue": issue}
    store.put_doc(finding_key(finding_id), json.dumps(doc, sort_keys=True))


def _load(store: ReviewStore, doc_key: str) -> dict[str, Any] | None:
    text = store.get_doc(doc_key)
    if text is None:
        return None
    try:
        doc: dict[str, Any] = json.loads(text)
    except ValueError as e:
        log.warning("%s cannot be read back: %s", doc_key, e)
        return None
    return doc


def _review_row(settings: Settings, repo: str, doc: dict[str, Any]) -> dict[str, Any]:
    result = AnalysisResult.model_validate(doc["result"])
    return {
        "number": doc["number"],
        "title": doc.get("title") or "",
        "head_sha": doc.get("head_sha", ""),
        "updated_at": doc.get("updated_at") or "",
        "verdict": doc["verdict"],
        "severity": severity(result),
        "headline": result.headline,
        "opened": [
            {"actor": p.actor, "target": p.target, "sensitivity": p.sensitivity} for p in result.opened
        ],
        "beyond_intent": len(result.use_beyond_intent),
        "fixes": [{"id": c.id, "verdict": c.verdict, "title": c.title} for c in result.candidates],
        "url": page_url(settings, repo, int(doc["number"])),
    }


def _finding_row(settings: Settings, doc: dict[str, Any]) -> dict[str, Any]:
    result = AnalysisResult.model_validate(doc["result"])
    finding = result.finding or {}
    cut = result.min_cut.cut if result.min_cut is not None else []
    # Jev's urgency is kept as {"p", "source"}; the dashboard ranks and shows the probability.
    urgency = finding.get("urgency")
    if isinstance(urgency, dict):
        urgency = urgency.get("p")
    return {
        "id": doc["id"],
        "action": finding.get("action", ""),
        "workflows": finding.get("workflows", []),
        "urgency": urgency if isinstance(urgency, int | float) else None,
        "headline": result.headline,
        "reaches": sorted({p.target for p in result.opened}),
        "rotate": result.rotate,
        "cut": [{"src": e.src, "type": e.type, "dst": e.dst} for e in cut],
        "updated_at": doc.get("updated_at") or "",
        "containment": doc.get("containment"),
        "fix": next(
            ({"id": c.id, "verdict": c.verdict, "title": c.title} for c in result.candidates if c.id == "K"),
            None,
        ),
        "url": finding_url(settings, doc["id"]),
    }


def onboarding(
    posture: dict[str, Any] | None, reviews: list[dict[str, Any]], graphs: list[str]
) -> list[dict[str, Any]]:
    """Each onboarding step and whether Theseus can see it done, from what it holds (O5)."""
    main_graph = ((posture or {}).get("scan") or {}).get("graphs", {}).get("main")
    seen = posture is not None or bool(reviews)
    return [
        {
            "step": "Install the Theseus GitHub App on the repository",
            "done": seen,
            "detail": "Theseus has read this repository." if seen else "Nothing read yet.",
        },
        {
            "step": "Add theseus.yaml and the Theseus workflows",
            "done": posture is not None,
            "detail": "main was planned and scanned." if posture else "No scan of main has arrived yet.",
        },
        {
            "step": "Build main's graph in FalkorDB",
            "done": bool(main_graph) and main_graph in graphs,
            "detail": f"Graph {main_graph}." if main_graph else "Runs on every push to main and nightly.",
        },
        {
            "step": "Review a first pull request",
            "done": bool(reviews),
            "detail": f"{len(reviews)} reviewed." if reviews else "Open a PR that changes the world root.",
        },
    ]


def dashboard_data(store: ReviewStore, settings: Settings, repo: str) -> dict[str, Any]:
    """Everything the dashboard shows for one repo, read from the store now: `main`'s posture, every PR
    review and every finding, and the onboarding steps."""
    posture = _load(store, posture_key(repo))
    rows = []
    for doc_key in store.docs(f"review:{repo}#"):
        doc = _load(store, doc_key)
        if doc is not None:
            rows.append(_review_row(settings, repo, doc))
    rows.sort(key=lambda r: (r["updated_at"], r["number"]), reverse=True)
    findings = []
    for doc_key in store.docs("finding:"):
        doc = _load(store, doc_key)
        if doc is not None and doc.get("repo") == repo:
            findings.append(_finding_row(settings, doc))
    findings.sort(key=lambda f: (-(f["urgency"] or 0), f["id"]))
    graphs = store.list_graphs()
    main_graph = None
    if posture is not None:
        name = (posture["scan"].get("graphs") or {}).get("main")
        if name and name in graphs:
            view = store.view(name)
            main_graph = {"name": name, "nodes": len(view["nodes"]), "edges": len(view["edges"])}
    return {
        "repo": repo,
        "org": repo.split("/", 1)[0],
        "org_url": org_url(settings, repo.split("/", 1)[0]),
        "history": (_load(store, history_key(repo)) or {}).get("runs", []),
        "posture": posture,
        "main_graph": main_graph,
        "reviews": rows,
        "findings": findings,
        "onboarding": onboarding(posture, rows, graphs),
    }


def _summary(store: ReviewStore, settings: Settings, repo: str) -> dict[str, Any]:
    """One repo's row on the organisation dashboard, from its kept posture and reviews."""
    posture = _load(store, posture_key(repo))
    verdicts = {"blocked": 0, "look": 0, "clear": 0}
    for doc_key in store.docs(f"review:{repo}#"):
        doc = _load(store, doc_key)
        if doc is not None:
            level = (doc.get("verdict") or {}).get("level")
            if level in verdicts:
                verdicts[level] += 1
    row: dict[str, Any] = {
        "repo": repo,
        "url": dashboard_url(settings, repo),
        "scanned": posture is not None,
        "reviews": verdicts,
        "history": (_load(store, history_key(repo)) or {}).get("runs", [])[-30:],
    }
    if posture is not None:
        scan = AnalysisResult.model_validate(posture["scan"])
        body = posture["posture"]
        row |= {
            "sha": posture["sha"],
            "updated_at": posture.get("updated_at") or "",
            "trigger": posture.get("trigger") or "",
            "graph": scan.graphs.get("main"),
            "nodes": scan.coverage.nodes,
            "edges": scan.coverage.edges,
            "dangerous": len(scan.unchanged),
            "actors_exposed": len({p.actor for p in scan.unchanged}),
            "regulated": sum(1 for p in scan.unchanged if p.sensitivity == "regulated"),
            "unused_grants": len(scan.unused_grants),
            "single_points": len(body.get("single_points") or []),
            "findings": posture.get("findings") or [],
            "monthly_usd": (body.get("cost") or {}).get("monthly_usd", 0.0),
            "top": [
                {"actor": p.actor, "target": p.target, "sensitivity": p.sensitivity, "hops": len(p.steps)}
                for p in scan.unchanged[:5]
            ],
        }
    return row


def org_data(store: ReviewStore, settings: Settings, owner: str) -> dict[str, Any]:
    """Every repo of this owner that Theseus acts on, summarised, with org-wide totals; read from the store
    now. Each row links to its own dashboard. Repos come from THESEUS_REPOS, sorted by name."""
    repos = sorted(r for r in settings.repos if r.split("/", 1)[0].lower() == owner.lower())
    rows = [_summary(store, settings, repo) for repo in repos]
    scanned = [r for r in rows if r["scanned"]]
    totals = {
        "repos": len(rows),
        "scanned": len(scanned),
        "nodes": sum(r["nodes"] for r in scanned),
        "edges": sum(r["edges"] for r in scanned),
        "dangerous": sum(r["dangerous"] for r in scanned),
        "regulated": sum(r["regulated"] for r in scanned),
        "unused_grants": sum(r["unused_grants"] for r in scanned),
        "single_points": sum(r["single_points"] for r in scanned),
        "findings": sum(len(r["findings"]) for r in scanned),
        "monthly_usd": round(sum(r["monthly_usd"] for r in scanned), 2),
        "blocked": sum(r["reviews"]["blocked"] for r in rows),
        "reviewed": sum(sum(r["reviews"].values()) for r in rows),
    }
    return {"org": owner, "repos": rows, "totals": totals}


def review_page(
    store: ReviewStore,
    settings: Settings,
    repo: str,
    *,
    q: str = "",
    verdict: str = "",
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """One page of the repo's PR reviews, newest PR first, filtered by verdict level and by a search over the
    number, title, headline and the names of what they would open; with the total that match."""
    keys = sorted(store.docs(f"review:{repo}#"), key=lambda k: -int(k.rsplit("#", 1)[1] or 0))
    needle = q.strip().lower()
    rows: list[dict[str, Any]] = []
    matched = 0
    for doc_key in keys:
        doc = _load(store, doc_key)
        if doc is None or (verdict and (doc.get("verdict") or {}).get("level") != verdict):
            continue
        row = _review_row(settings, repo, doc)
        if needle:
            haystack = " ".join(
                [str(row["number"]), row["title"], row["headline"]]
                + [f"{o['actor']} {o['target']}" for o in row["opened"]]
            ).lower()
            if needle not in haystack:
                continue
        if offset <= matched < offset + limit:
            rows.append(row)
        matched += 1
    return {"repo": repo, "total": matched, "offset": offset, "limit": limit, "reviews": rows}
