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

from theseus.agent.render import verdict
from theseus.config import Settings
from theseus.contracts.result import AnalysisResult
from theseus.errors import GraphError

log = logging.getLogger(__name__)

SIGNATURE_CHARS = 32


class ReviewStore(Protocol):
    """The two things the page needs from a store, besides the graphs it already holds."""

    def view(self, graph: str) -> dict[str, list[dict[str, Any]]]: ...
    def put_doc(self, key: str, text: str) -> None: ...
    def get_doc(self, key: str) -> str | None: ...


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
) -> None:
    """Keeps the PR's newest result for its page, with its verdict and the base and head commits and world
    root its links need."""
    base_sha, head_sha = shas
    doc = {
        "repo": repo,
        "number": number,
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


def save_finding(store: ReviewStore, repo: str, world_root: str, result: AnalysisResult) -> None:
    """Keeps a finding's newest result for its page. A fixture's files are linked on the repo's main."""
    finding_id = (result.finding or {})["id"]
    doc = {
        "kind": "finding",
        "id": finding_id,
        "repo": repo,
        "base_sha": "main",
        "head_sha": "main",
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
