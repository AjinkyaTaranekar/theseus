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
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol
from urllib.parse import quote

from theseus.agent.labels import severity
from theseus.agent.render import verdict
from theseus.config import Settings
from theseus.contracts.incident import Incident, IncidentReport
from theseus.contracts.posture import OutageBasis, PostureReport
from theseus.contracts.result import AnalysisResult
from theseus.contracts.schema import PATH_TYPES
from theseus.engine.analyze import step_evidence, valid_paths
from theseus.engine.incident import blast
from theseus.engine.simulate import candidate_graph
from theseus.errors import GraphError
from theseus.graph.store import rows_from_view

log = logging.getLogger(__name__)

SIGNATURE_CHARS = 32
CACHE_TTL = 30.0  # seconds a page read is reused; another process that re-saves shows up within this long
CACHE_SIZE = 64


class ReviewStore(Protocol):
    """The two things the page needs from a store, besides the graphs it already holds."""

    def view(self, graph: str) -> dict[str, list[dict[str, Any]]]: ...
    def put_doc(self, key: str, text: str) -> None: ...
    def get_doc(self, key: str) -> str | None: ...
    def docs(self, prefix: str) -> list[str]: ...
    def read_docs(self, prefix: str) -> dict[str, str]: ...
    def list_graphs(self) -> list[str]: ...
    def paths(self, graph: str, actor: str) -> list[list[str]]: ...


class ReadCache:
    """A small process-local cache of the page's store reads: entries expire after `ttl` seconds, at most
    `size` are kept (the oldest is dropped first), and an entry is served only to the store that made it."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = CACHE_TTL,
        size: int = CACHE_SIZE,
    ) -> None:
        self.clock = clock
        self.ttl = ttl
        self.size = size
        self._entries: OrderedDict[tuple[str, str], tuple[float, object, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, store: object, doc_key: str, part: str = "") -> Any | None:
        """The value kept for this document (and fix, when `part` names one), or None if none is fresh."""
        with self._lock:
            entry = self._entries.get((doc_key, part))
            if entry is None:
                return None
            expires, owner, value = entry
            if owner is not store or self.clock() >= expires:
                del self._entries[(doc_key, part)]
                return None
            return value

    def put(self, store: object, doc_key: str, part: str, value: Any) -> None:
        with self._lock:
            self._entries.pop((doc_key, part), None)
            self._entries[(doc_key, part)] = (self.clock() + self.ttl, store, value)
            while len(self._entries) > self.size:
                self._entries.popitem(last=False)

    def clear(self, doc_key: str) -> None:
        """Forgets everything kept for this document, its fixes included."""
        with self._lock:
            for entry_key in [k for k in self._entries if k[0] == doc_key]:
                del self._entries[entry_key]


_cache = ReadCache()


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
    _cache.clear(key(repo, number))
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
    _cache.clear(finding_key(finding_id))
    log.info("finding %s: kept for its page", finding_id)


def page_doc(store: ReviewStore, doc_key: str) -> dict[str, Any] | None:
    """A page's newest result and its graphs as the store holds them now (up to CACHE_TTL seconds ago), or
    None if there is none. The graphs are read at the same time, in the result's order; a graph the store no
    longer holds is left out."""
    cached = _cache.get(store, doc_key)
    if cached is not None:
        log.info("%s: page served from the cache", doc_key)
        return cached  # type: ignore[no-any-return]
    started = time.perf_counter()
    text = store.get_doc(doc_key)
    if text is None:
        return None
    doc: dict[str, Any] = json.loads(text)
    named = list((doc["result"].get("graphs") or {}).items())

    def read(name: str) -> dict[str, Any] | None:
        try:
            return {"name": name, **store.view(name)}
        except GraphError as e:  # deleted since: the page shows what is left
            log.warning("%s: graph %s is gone: %s", doc_key, name, e)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        views = list(pool.map(read, [name for _, name in named]))
    graphs = {side: view for (side, _), view in zip(named, views, strict=True) if view is not None}
    page = {**doc, "graphs": graphs}
    _cache.put(store, doc_key, "", page)
    log.info("%s: read the page in %d ms", doc_key, (time.perf_counter() - started) * 1000)
    return page


def fix_graph(store: ReviewStore, doc_key: str, candidate_id: str) -> dict[str, Any] | None:
    """One candidate fix with the graph copy the engine verified it on, read from the store now (or up to
    CACHE_TTL seconds ago) and trimmed to what the page draws: `{id, verdict, title, recommended, reason, ops,
    name, nodes, edges}`, the nodes as `{id, category, sensitivity}` and the edges as `{src, type, dst}` for
    access links only. None when the review, the candidate or its copy is gone."""
    cached = _cache.get(store, doc_key, candidate_id)
    if cached is not None:
        log.info("%s: fix %s served from the cache", doc_key, candidate_id)
        return cached  # type: ignore[no-any-return]
    started = time.perf_counter()
    doc = _load(store, doc_key)
    head = ((doc or {}).get("result") or {}).get("graphs", {}).get("head")
    candidate = (
        next((c for c in (doc or {})["result"].get("candidates") or [] if c["id"] == candidate_id), None)
        if doc
        else None
    )
    if not head or candidate is None:
        return None
    name = candidate_graph(head, candidate_id)
    try:
        view = store.view(name)
    except GraphError as e:
        if name in store.list_graphs():  # the graph is there, so the read itself failed
            raise
        log.warning("%s: fix %s's graph %s is gone: %s", doc_key, candidate_id, name, e)
        return None
    keep = ("id", "verdict", "title", "recommended", "reason", "ops")
    fix = {
        **{k: candidate.get(k) for k in keep},
        "name": name,
        "nodes": [{k: n.get(k) for k in ("id", "category", "sensitivity")} for n in view["nodes"]],
        "edges": [
            {k: e[k] for k in ("src", "type", "dst")} for e in view["edges"] if e["type"] in PATH_TYPES
        ],
    }
    _cache.put(store, doc_key, candidate_id, fix)
    log.info("%s: read fix %s in %d ms", doc_key, candidate_id, (time.perf_counter() - started) * 1000)
    return fix


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


def incidents_key(repo: str) -> str:
    return f"incidents:{repo}"


def outage_basis(store: ReviewStore, repo: str) -> OutageBasis | None:
    """The outage basis `main`'s newest posture kept, or None before a posture run that kept one."""
    raw = ((_load(store, posture_key(repo)) or {}).get("posture") or {}).get("outage")
    if not raw or not raw.get("tags"):
        return None
    return OutageBasis.model_validate(raw)


def outage_terms(basis: OutageBasis) -> dict[str, Any]:
    """The services and regions the incident picker offers, each service with how many nodes it runs here."""
    here: dict[tuple[str, str], set[str]] = {}
    for tag in basis.tags:
        here.setdefault((tag.provider, tag.service), set()).add(tag.node)
    services = []
    for t in basis.terms:
        row: dict[str, Any] = {
            "provider": t.provider,
            "service": t.service,
            "name": t.name,
            "here": len(here.get((t.provider, t.service), set())),
        }
        if row["here"]:
            # What a full outage of it would do here, so the page can rank the services by it.
            found = blast(basis, Incident(provider=t.provider, service=t.service))
            row["down"] = sum(1 for m in found.matched if m.state == "down")
            row["affected"] = len(found.affected)
            row["breaks"] = sum(1 for b in found.broken if b.state == "broken")
            row["dependencies"] = found.dependencies
        services.append(row)
    return {
        "services": services,
        "regions": [{"code": r.code, "name": r.name} for r in basis.regions],
        "world_regions": sorted({t.region for t in basis.tags if t.region}),
    }


def save_incidents(
    store: ReviewStore,
    repo: str,
    reports: list[IncidentReport],
    errors: list[str],
    checked_at: str,
    trigger: str,
) -> dict[str, Any]:
    """Keeps the newest check of the status feeds: each incident's blast radius on `main`."""
    doc = {
        "repo": repo,
        "checked_at": checked_at,
        "trigger": trigger,
        "errors": errors,
        "reports": [r.model_dump(mode="json") for r in reports],
    }
    store.put_doc(incidents_key(repo), json.dumps(doc, sort_keys=True))
    log.info("%s: kept %d incident(s) from the status feeds", repo, len(reports))
    return doc


def blob_base(repo: str, sha: str, world_root: str) -> str:
    """Where a world file is on GitHub at a commit: append `<file>#L<line>`."""
    root = world_root.strip("/")
    return f"https://github.com/{quote(repo)}/blob/{quote(sha)}/{quote(root)}"


# What a node could reach if it were compromised -------------------------------------------------------------
SENSITIVE_RANK = {"regulated": 0, "confidential": 1, "internal": 2, "public": 3}
REACH_SHOWN = 40


def compromise(store: ReviewStore, repo: str, node: str) -> dict[str, Any] | None:
    """Everything `node` could reach on `main` if it were compromised: for each resource, the engine's
    shortest valid path from it in main's graph in FalkorDB, each hop with the file and line behind it;
    the data classes at risk; and the links on every route to sensitive data, any one of which cuts them all.
    None before main has a graph; KeyError when the graph has no such node."""
    posture = _load(store, posture_key(repo))
    name = ((posture or {}).get("scan") or {}).get("graphs", {}).get("main")
    if posture is None or not name or name not in store.list_graphs():
        return None
    rows = rows_from_view(store.view(name))
    nodes = {n.id: n for n in rows.nodes}
    if node not in nodes:
        raise KeyError(node)
    paths = valid_paths(store, name, rows, node)
    best: dict[str, Any] = {}
    for p in paths:
        if p.unknown and p.target in best:
            continue
        if p.target not in best or len(p.steps) < len(best[p.target].steps):
            best[p.target] = p
    evidence = step_evidence(rows)
    base = blob_base(repo, posture["sha"], posture.get("world_root") or "")
    required = {
        (r.get("principal"), r.get("resource"))
        for r in (posture["scan"].get("requirements") or [])
        if isinstance(r, dict)
    }

    def proof(eid: str) -> dict[str, Any]:
        ev = evidence.get(eid)
        if ev is None:
            return {"file": "unknown"}
        url = (
            f"{base}/{quote(ev.file)}" + (f"#L{ev.line}" if ev.line else "") if ev.file != "unknown" else None
        )
        return {"file": ev.file, "line": ev.line, "address": ev.address, "part": ev.part, "url": url}

    def rank(p: Any) -> tuple[int, int, str]:
        target = nodes[p.target]
        return (
            SENSITIVE_RANK.get(target.sensitivity or "", 4) if target.sensitive else 5,
            len(p.steps),
            p.target,
        )

    ranked = sorted(best.values(), key=rank)
    reaches = [
        {
            "target": p.target,
            "sensitive": nodes[p.target].sensitive,
            "sensitivity": nodes[p.target].sensitivity,
            "category": nodes[p.target].category,
            "grants": list(p.grants),
            "unknown": p.unknown,
            "required": (node, p.target) in required,
            "steps": [
                {"from": s.src, "type": s.type, "to": s.dst, "grants": s.grants, "proof": proof(s.evidence)}
                for s in p.steps
            ],
        }
        for p in ranked[:REACH_SHOWN]
    ]
    risky = [p for p in ranked if nodes[p.target].sensitive]
    common: set[tuple[str, str, str]] | None = None
    for p in risky:
        links = {(s.src, s.type, s.dst) for s in p.steps}
        common = links if common is None else common & links
    cut_proof = {(s.src, s.type, s.dst): proof(s.evidence) for p in risky for s in p.steps}
    # In the order the first route takes them: the link nearest the node first.
    order = {(s.src, s.type, s.dst): i for i, s in enumerate(risky[0].steps)} if risky else {}
    cut = [
        {"from": a, "type": t, "to": b, "proof": cut_proof[(a, t, b)]}
        for a, t, b in sorted(common or set(), key=lambda k: (order.get(k, len(order)), k))
    ]
    classes: dict[str, int] = {}
    for p in risky:
        level = nodes[p.target].sensitivity or "unclassified"
        classes[level] = classes.get(level, 0) + 1
    named = {node} | {s for r in reaches for st in r["steps"] for s in (st["from"], st["to"])}
    return {
        "node": node,
        "graph": name,
        "sha": posture["sha"],
        "routes": len(paths),
        "targets": len(best),
        "sensitive": len(risky),
        "classes": classes,
        "reaches": reaches,
        "more": max(0, len(ranked) - REACH_SHOWN),
        "cut": cut,
        "nodes": {
            n: {"category": nodes[n].category, "sensitivity": nodes[n].sensitivity, "labels": nodes[n].labels}
            for n in sorted(named)
            if n in nodes
        },
    }


def weak_routes(raw_outage: dict[str, Any], points: list[str], per_point: int = 6) -> dict[str, Any]:
    """For each single point of failure, the dependencies whose every route passes through it, with those
    routes: the engine's own routes from the posture run, so the page shows why the node is one."""
    out: dict[str, Any] = {}
    for point in points:
        found = []
        for dep in raw_outage.get("routes") or []:
            routes = [r for r in dep.get("routes") or [] if point in r[1:-1]]
            if routes and len(routes) == len(dep.get("routes") or []):
                found.append({"dependency": dep.get("dependency"), "routes": routes[:4]})
        out[point] = found[:per_point]
    return out


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
    _cache.clear(finding_key(finding_id))


def _load_all(store: ReviewStore, prefix: str) -> list[dict[str, Any]]:
    """Every document under `prefix`, read in one query, in key order; one that can't be read is skipped."""
    found = []
    for doc_key, text in store.read_docs(prefix).items():
        try:
            found.append(json.loads(text))
        except ValueError as e:
            log.warning("%s cannot be read back: %s", doc_key, e)
    return found


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
    result = _kept_result(doc["result"])
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
        "closed": [{"actor": p.actor, "target": p.target} for p in result.closed],
        # A clear change still touches something: what it touches and who relies on it, when the engine said.
        "impact": _impact_summary(doc["result"].get("impact")),
        # The fix that passes, the one a reviewer would commit; the others are named on the PR.
        "fixes": [
            {"id": c.id, "verdict": c.verdict, "title": c.title}
            for c in result.candidates
            if c.verdict == "pass"
        ],
        "fixes_tried": len(result.candidates),
        "url": page_url(settings, repo, int(doc["number"])),
        "pr_url": f"https://github.com/{quote(repo)}/pull/{int(doc['number'])}",
    }


def _kept_result(raw: dict[str, Any]) -> AnalysisResult:
    """A kept result read back, keeping the fields this version knows: a document written by a newer
    deploy, with a field added since, still lists on the dashboard."""
    return AnalysisResult.model_validate({k: v for k, v in raw.items() if k in AnalysisResult.model_fields})


def _impact_summary(impact: Any) -> dict[str, Any] | None:
    """The few fields of a change's impact the PR list shows, or None when the result has none."""
    if not isinstance(impact, dict):
        return None
    access = [a for a in impact.get("access") or [] if isinstance(a, dict)]
    relies = [r for r in impact.get("relies") or [] if isinstance(r, dict)]
    return {
        "headline": impact.get("headline") or "",
        "most_affected": list(impact.get("most_affected") or [])[:8],
        "gained": sum(1 for a in access if a.get("change") == "gained"),
        "lost": sum(1 for a in access if a.get("change") == "lost"),
        "relies_lost": sum(1 for r in relies if r.get("state") == "lost"),
        "monthly_usd_before": impact.get("monthly_usd_before"),
        "monthly_usd_after": impact.get("monthly_usd_after"),
    }


def _finding_row(settings: Settings, doc: dict[str, Any]) -> dict[str, Any]:
    result = _kept_result(doc["result"])
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
    outage = None
    if posture is not None:
        # The basis is for the incident routes; the page gets the picker's terms and the last feed check.
        raw = (posture.get("posture") or {}).pop("outage", None)
        if raw:
            points = [s["id"] for s in (posture.get("posture") or {}).get("single_points") or []]
            posture["weak_routes"] = weak_routes(raw, points)
        posture["blob"] = blob_base(repo, posture.get("sha", ""), posture.get("world_root") or "")
        if raw and raw.get("tags"):
            outage = outage_terms(OutageBasis.model_validate(raw))
            outage["live"] = _load(store, incidents_key(repo))
    rows = [_review_row(settings, repo, doc) for doc in _load_all(store, f"review:{repo}#")]
    rows.sort(key=lambda r: (r["updated_at"], r["number"]), reverse=True)
    findings = [_finding_row(settings, d) for d in _load_all(store, "finding:") if d.get("repo") == repo]
    findings.sort(key=lambda f: (-(f["urgency"] or 0), f["id"]))
    graphs = store.list_graphs()
    main_graph = None
    if posture is not None:
        name = (posture["scan"].get("graphs") or {}).get("main")
        if name and name in graphs:
            # The size the scan built; reading the whole graph back just to count it took seconds.
            size = posture["scan"].get("coverage") or {}
            main_graph = {"name": name, "nodes": size.get("nodes", 0), "edges": size.get("edges", 0)}
    return {
        "repo": repo,
        "org": repo.split("/", 1)[0],
        "org_url": org_url(settings, repo.split("/", 1)[0]),
        "history": (_load(store, history_key(repo)) or {}).get("runs", []),
        "posture": posture,
        "outage": outage,
        "main_graph": main_graph,
        "reviews": rows,
        "findings": findings,
        "onboarding": onboarding(posture, rows, graphs),
    }


def _summary(store: ReviewStore, settings: Settings, repo: str) -> dict[str, Any]:
    """One repo's row on the organisation dashboard, from its kept posture and reviews."""
    posture = _load(store, posture_key(repo))
    verdicts = {"blocked": 0, "look": 0, "clear": 0}
    for doc in _load_all(store, f"review:{repo}#"):
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


def main_graph(store: ReviewStore, repo: str) -> dict[str, Any] | None:
    """`main`'s graph as FalkorDB holds it now, `{name, nodes, edges}`, or None before its first scan or once
    the graph is gone."""
    posture = _load(store, posture_key(repo))
    name = ((posture or {}).get("scan") or {}).get("graphs", {}).get("main")
    if not name or name not in store.list_graphs():
        return None
    return {"name": name, **store.view(name)}
