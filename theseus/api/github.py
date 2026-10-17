"""The GitHub App's calls (docs/spec/07-github-and-deploy.md, "The GitHub App"): its JWT and installation
tokens, files under the world root, the PR comment and replies to commands, the `Theseus` check run,
re-running the Theseus workflow, and commits, which may change only files under the world root.

Every request goes through `GitHub._call`, which turns any failure into a GitHubError naming the method, the
path and the status. Only repos in THESEUS_REPOS are touched: anything else is refused before a request is
sent.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx
import jwt

from theseus.agent.labels import Label
from theseus.agent.render import MARKER
from theseus.config import Settings
from theseus.errors import GitHubError

log = logging.getLogger(__name__)

API = "https://api.github.com"
CHECK_NAME = "Theseus"
# A check run's external_id says which of our two writers set it: a review's verdict, or the pass for a PR
# that changes nothing under the world root. Only the second may be withdrawn.
REVIEW, NOTHING_CHANGED = "review", "nothing-changed"
WORKFLOW = "theseus.yml"
# `maintain` reports permission "write", so these two cover admin, maintain and write.
WRITE = frozenset({"admin", "write"})
JWT_TTL_S = 540  # GitHub allows at most 10 minutes
TOKEN_MARGIN_S = 300  # renew an installation token this long before it expires
PER_PAGE = 100
MAX_PAGES = 30  # GitHub lists at most 3,000 files on a PR
TITLE_MAX = 255
SUMMARY_MAX = 65_000
ANNOTATIONS_MAX = 50  # per request
BLOB_BATCH = 100  # files per GraphQL query


def _read(rel: str) -> bool:
    """Whether a review reads this file, by its path under the world root."""
    if rel == "theseus.yaml":
        return True
    folder, _, rest = rel.partition("/")
    endings = {"terraform": (".tf", ".tf.json"), "services": (".py",), "workflows": (".yml", ".yaml")}
    return bool(rest) and folder in endings and rel.endswith(endings[folder])


class GitHub:
    """The one way to call GitHub. `client` and `clock` are for tests."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.world_root = settings.theseus_world_root.strip("/")
        self._client = client or httpx.Client(base_url=API, timeout=30.0)
        self._clock = clock
        self._installations: dict[str, int] = {}
        self._tokens: dict[int, tuple[str, float]] = {}
        self._key: str | None = None

    # Auth -------------------------------------------------------------------------------------------------

    @property
    def app_id(self) -> str:
        if not self.settings.github_app_id:
            raise GitHubError("GITHUB_APP_ID is not set")
        return self.settings.github_app_id

    def allowed(self, repo: str) -> bool:
        """Whether THESEUS_REPOS lists the repo (`owner/name`, any case)."""
        return repo.lower() in {r.lower() for r in self.settings.repos}

    def _require(self, repo: str) -> None:
        if not self.allowed(repo):
            raise GitHubError(f"{repo} is not in THESEUS_REPOS; refusing to act on it")

    def app_jwt(self) -> str:
        """A JWT for the App, signed with its private key: issued a minute back, for clock drift, and
        short-lived."""
        if self._key is None:
            path = self.settings.github_app_private_key_path
            if path is None:
                raise GitHubError("GITHUB_APP_PRIVATE_KEY_PATH is not set")
            try:
                self._key = path.read_text(encoding="utf-8")
            except OSError as e:
                raise GitHubError(f"cannot read the App's private key at {path}: {e}") from e
        now = int(self._clock())
        claims = {"iat": now - 60, "exp": now + JWT_TTL_S, "iss": self.app_id}
        return jwt.encode(claims, self._key, algorithm="RS256")

    def installation_token(self, repo: str) -> str:
        """A token for the App's installation on the repo, reused until five minutes before it expires."""
        self._require(repo)
        if repo not in self._installations:
            found = self._call("GET", f"/repos/{repo}/installation", bearer=self.app_jwt()).json()
            self._installations[repo] = int(found["id"])
        installation = self._installations[repo]
        cached = self._tokens.get(installation)
        if cached is not None and cached[1] - self._clock() > TOKEN_MARGIN_S:
            return cached[0]
        body = self._call(
            "POST", f"/app/installations/{installation}/access_tokens", bearer=self.app_jwt()
        ).json()
        expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00")).timestamp()
        self._tokens[installation] = (body["token"], expires)
        return body["token"]

    # Requests ---------------------------------------------------------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        *,
        bearer: str,
        params: dict[str, Any] | None = None,
        json: Any = None,
        accept: str = "application/vnd.github+json",
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "theseus",
        }
        try:
            res = self._client.request(method, path, params=params, json=json, headers=headers)
        except httpx.HTTPError as e:
            raise GitHubError(f"{method} {path}: {type(e).__name__}: {e}") from e
        if res.status_code >= 400:
            try:
                message = res.json().get("message", "")
            except ValueError:
                message = res.text[:200]
            raise GitHubError(f"{method} {path}: {res.status_code} {message}".rstrip())
        return res

    def _repo(self, repo: str, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self._call(method, f"/repos/{repo}{path}", bearer=self.installation_token(repo), **kwargs)

    def _pages(self, repo: str, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            rows = self._repo(
                repo, "GET", path, params={**(params or {}), "per_page": PER_PAGE, "page": page}
            ).json()
            out += rows
            if len(rows) < PER_PAGE:
                break
        return out

    # Reading ----------------------------------------------------------------------------------------------

    def pull_request(self, repo: str, number: int) -> dict[str, Any]:
        """The PR as GitHub has it now: its current title, body and head, not the copy an event carried."""
        return self._repo(repo, "GET", f"/pulls/{number}").json()

    def pull_states(self, repo: str) -> dict[int, str]:
        """Every PR GitHub lists for the repo by number: `open`, `merged`, or `closed` without a merge.
        A PR older than the newest 3,000 is not listed, so a caller treats a missing number as unknown."""
        states: dict[int, str] = {}
        for pull in self._pages(repo, "/pulls", {"state": "all"}):
            if pull.get("state") == "open":
                states[int(pull["number"])] = "open"
            else:
                states[int(pull["number"])] = "merged" if pull.get("merged_at") else "closed"
        return states

    def changed_files(self, repo: str, number: int) -> list[str]:
        """Every path the PR changes, a renamed file's old path included, sorted."""
        files: set[str] = set()
        for f in self._pages(repo, f"/pulls/{number}/files"):
            files.add(f["filename"])
            if f.get("previous_filename"):
                files.add(f["previous_filename"])
        return sorted(files)

    def open_pulls_at(self, repo: str, head_sha: str) -> list[int]:
        """The open PRs whose head is this commit, sorted. Several PRs can share a head and differ in base."""
        pulls = self._pages(repo, "/pulls", {"state": "open"})
        return sorted(int(p["number"]) for p in pulls if (p.get("head") or {}).get("sha") == head_sha)

    def touches_world_root(self, repo: str, number: int) -> bool:
        return any(self._under_world_root(f) for f in self.changed_files(repo, number))

    def _under_world_root(self, path: str) -> bool:
        parts = path.split("/")
        return len(parts) > 1 and parts[0] == self.world_root and ".." not in parts

    def writable(self, path: str) -> bool:
        """Whether the App may write this repo path: a file under the world root, spelled plainly (no empty,
        `.` or `..` part, no backslash, no NUL), so the path written is the path checked."""
        parts = path.split("/")
        return (
            len(parts) > 1
            and parts[0] == self.world_root
            and all(part not in ("", ".", "..") for part in parts)
            and "\\" not in path
            and "\x00" not in path
        )

    def read_file(self, repo: str, path: str, sha: str) -> str:
        """The text of a file under the world root at a commit. Any other path is refused."""
        if not self._under_world_root(path):
            raise GitHubError(f"{path} is not under the world root {self.world_root}/")
        res = self._repo(
            repo,
            "GET",
            f"/contents/{quote(path)}",
            params={"ref": sha},
            accept="application/vnd.github.raw+json",
        )
        return res.text

    def world_files(self, repo: str, sha: str) -> dict[str, str]:
        """Every file a review reads under the world root at a commit, by path relative to the root, sorted:
        `theseus.yaml`, `terraform/*.tf`, `services/**/*.py` and `workflows/**/*.yml`. One tree request,
        then the files in GraphQL batches; a file GraphQL cannot give whole is read on its own. Raises
        GitHubError when the commit's tree is too large to list in one answer."""
        tree = self._repo(repo, "GET", f"/git/trees/{quote(sha)}", params={"recursive": "1"}).json()
        if tree.get("truncated"):
            raise GitHubError(f"{repo}@{sha[:7]}: the tree is too large to list")
        prefix = f"{self.world_root}/"
        wanted = sorted(
            e["path"]
            for e in tree.get("tree") or []
            if e.get("type") == "blob"
            and str(e.get("path", "")).startswith(prefix)
            and self._under_world_root(e["path"])
            and _read(e["path"][len(prefix) :])
        )
        texts = self._blobs(repo, sha, wanted)
        alone = [path for path in wanted if texts[path] is None]
        files = {
            path[len(prefix) :]: text
            if (text := texts[path]) is not None
            else self.read_file(repo, path, sha)
            for path in wanted
        }
        log.info(
            "%s@%s: read %d files under %s/ (%d on their own)",
            repo,
            sha[:7],
            len(files),
            self.world_root,
            len(alone),
        )
        return files

    def _blobs(self, repo: str, sha: str, paths: list[str]) -> dict[str, str | None]:
        """Each file's text at the commit through GraphQL, BLOB_BATCH files a query, or None for one it cannot
        give whole (binary, truncated or missing). Paths reach the query only as variables."""
        owner, name = repo.split("/", 1)
        out: dict[str, str | None] = {}
        for start in range(0, len(paths), BLOB_BATCH):
            chunk = paths[start : start + BLOB_BATCH]
            names = ", ".join(f"$e{n}: String!" for n in range(len(chunk)))
            fields = " ".join(
                f"f{n}: object(expression: $e{n}) {{ ... on Blob {{ text isBinary isTruncated }} }}"
                for n in range(len(chunk))
            )
            query = (
                f"query($owner: String!, $name: String!, {names}) "
                f"{{ repository(owner: $owner, name: $name) {{ {fields} }} }}"
            )
            variables = {"owner": owner, "name": name} | {f"e{n}": f"{sha}:{p}" for n, p in enumerate(chunk)}
            found = self._graphql(repo, query, variables).get("repository") or {}
            for n, path in enumerate(chunk):
                blob = found.get(f"f{n}") or {}
                whole = (
                    blob.get("text") is not None and not blob.get("isBinary") and not blob.get("isTruncated")
                )
                out[path] = blob["text"] if whole else None
        return out

    def _graphql(self, repo: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = {"query": query, "variables": variables}
        found = self._call("POST", "/graphql", bearer=self.installation_token(repo), json=body).json()
        if found.get("errors"):
            raise GitHubError(f"POST /graphql: {found['errors'][0].get('message', 'error')}")
        return found.get("data") or {}

    def can_write(self, repo: str, user: str) -> bool:
        """Whether the user has write, maintain or admin permission on the repo."""
        found = self._repo(repo, "GET", f"/collaborators/{quote(user)}/permission").json()
        return found.get("permission") in WRITE

    # Writing ----------------------------------------------------------------------------------------------

    def commit_files(self, repo: str, branch: str, parent: str, files: dict[str, str], message: str) -> str:
        """Commits the files (repo path to text) to the branch as one commit on `parent`, and returns its SHA.

        Every commit the App makes is fenced to the world root (07, "Writing is fenced to the world root"): a
        path outside it refuses the whole commit before any request. The branch moves only forward from
        `parent`, never forced, so a push since the review makes GitHub refuse the update."""
        self._require(repo)
        if not files:
            raise GitHubError(f"{repo}: nothing to commit")
        outside = sorted(path for path in files if not self.writable(path))
        if outside:
            named = ", ".join(map(repr, outside))
            raise GitHubError(f"{repo}: refusing a commit outside the world root {self.world_root}/: {named}")
        if not branch or not parent:
            raise GitHubError(f"{repo}: a commit needs a branch and its parent commit")
        tree = self._repo(repo, "GET", f"/git/commits/{quote(parent)}").json()["tree"]["sha"]
        entries = [{"path": p, "mode": "100644", "type": "blob", "content": files[p]} for p in sorted(files)]
        made = self._repo(repo, "POST", "/git/trees", json={"base_tree": tree, "tree": entries}).json()["sha"]
        body = {"message": message, "tree": made, "parents": [parent]}
        commit = self._repo(repo, "POST", "/git/commits", json=body).json()["sha"]
        self._repo(
            repo, "PATCH", f"/git/refs/heads/{quote(branch, safe='/')}", json={"sha": commit, "force": False}
        )
        log.info("%s: committed %s on %s (%d files)", repo, commit[:7], branch, len(files))
        return commit

    def default_branch(self, repo: str) -> str:
        """The repo's default branch, such as `main`."""
        return str(self._repo(repo, "GET", "").json()["default_branch"])

    def branch_head(self, repo: str, branch: str) -> str | None:
        """The commit the branch points at, or None when there is no such branch."""
        self._require(repo)
        for ref in self._repo(repo, "GET", f"/git/matching-refs/heads/{quote(branch, safe='/')}").json():
            if ref.get("ref") == f"refs/heads/{branch}":
                return str(ref["object"]["sha"])
        return None

    def create_branch(self, repo: str, branch: str, sha: str) -> None:
        """Creates the branch at `sha`. Raises GitHubError if it already exists."""
        self._require(repo)
        self._repo(repo, "POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha})
        log.info("%s: created branch %s at %s", repo, branch, sha[:7])

    def open_pull_from(self, repo: str, branch: str) -> dict[str, Any] | None:
        """The open PR whose head is this branch of the repo, or None."""
        self._require(repo)
        owner = repo.split("/", 1)[0]
        found = self._repo(
            repo, "GET", "/pulls", params={"state": "open", "head": f"{owner}:{branch}"}
        ).json()
        return found[0] if found else None

    def open_pull(
        self, repo: str, branch: str, base: str, title: str, body: str, labels: list[str]
    ) -> dict[str, Any]:
        """Opens a PR from the branch into `base` with these labels, and returns it."""
        self._require(repo)
        pr = self._repo(
            repo, "POST", "/pulls", json={"title": title, "head": branch, "base": base, "body": body}
        ).json()
        if labels:
            self._repo(repo, "POST", f"/issues/{pr['number']}/labels", json={"labels": labels})
        log.info("%s: opened #%s from %s", repo, pr["number"], branch)
        return pr

    def open_issue_titled(
        self, repo: str, title: str, body: str, labels: list[str]
    ) -> tuple[dict[str, Any], bool]:
        """The open issue with this exact title, or a new one with these labels; and whether it is new. Pull
        requests, which the issues API also lists, never count."""
        self._require(repo)
        for issue in self._pages(repo, "/issues", {"state": "open", "labels": ",".join(labels)}):
            if issue.get("title") == title and "pull_request" not in issue:
                return issue, False
        created = self._repo(
            repo, "POST", "/issues", json={"title": title, "body": body, "labels": labels}
        ).json()
        log.info("%s: opened issue #%s, %s", repo, created["number"], title)
        return created, True

    def pull_patches(self, repo: str, number: int) -> dict[str, str]:
        """Each file the PR changes and its patch (the diff GitHub shows), by repo path."""
        self._require(repo)
        return {f["filename"]: f.get("patch") or "" for f in self._pages(repo, f"/pulls/{number}/files")}

    def has_review_with(self, repo: str, number: int, marker: str) -> bool:
        """Whether a review on the PR already carries this marker in its text."""
        self._require(repo)
        return any(marker in (r.get("body") or "") for r in self._pages(repo, f"/pulls/{number}/reviews"))

    def post_review(
        self, repo: str, number: int, head_sha: str, body: str, comments: list[dict[str, Any]]
    ) -> int:
        """Posts a review that only comments, on the head commit, with these line comments. Returns its ID."""
        self._require(repo)
        payload = {"commit_id": head_sha, "event": "COMMENT", "body": body, "comments": comments}
        made = self._repo(repo, "POST", f"/pulls/{number}/reviews", json=payload).json()
        log.info("%s#%d: posted review %s with %d comment(s)", repo, number, made["id"], len(comments))
        return int(made["id"])

    def reply(self, repo: str, number: int, body: str) -> int:
        """Posts a new comment on the PR, as the answer to a command, and returns its ID."""
        self._require(repo)
        created = self._repo(repo, "POST", f"/issues/{number}/comments", json={"body": body}).json()
        log.info("%s#%d: replied in comment %s", repo, number, created["id"])
        return int(created["id"])

    def upsert_comment(self, repo: str, number: int, body: str) -> int:
        """Edits the App's own comment carrying the marker, or creates it. Returns the comment's ID. A comment
        someone else wrote with the marker in it is never edited."""
        self._require(repo)
        for c in self._pages(repo, f"/issues/{number}/comments"):
            app = c.get("performed_via_github_app") or {}
            if MARKER in (c.get("body") or "") and str(app.get("id")) == self.app_id:
                self._repo(repo, "PATCH", f"/issues/comments/{c['id']}", json={"body": body})
                log.info("%s#%d: edited comment %s", repo, number, c["id"])
                return int(c["id"])
        created = self._repo(repo, "POST", f"/issues/{number}/comments", json={"body": body}).json()
        log.info("%s#%d: created comment %s", repo, number, created["id"])
        return int(created["id"])

    def set_labels(self, repo: str, number: int, wanted: list[Label], managed: tuple[Label, ...]) -> None:
        """Makes the PR carry exactly the `wanted` labels among `managed` ones, creating any the repo lacks
        with its colour and description. A label outside `managed` (`demo`, a person's) is never touched."""
        self._require(repo)
        names = {label.name for label in managed}
        if not {label.name for label in wanted} <= names:
            raise GitHubError(f"{repo}#{number}: refusing to set a label Theseus does not manage")
        current = {label["name"] for label in self._pages(repo, f"/issues/{number}/labels")}
        for name in sorted((current & names) - {label.name for label in wanted}):
            self._repo(repo, "DELETE", f"/issues/{number}/labels/{quote(name, safe='')}")
        add = [label for label in wanted if label.name not in current]
        if not add:
            return
        existing = {label["name"] for label in self._pages(repo, "/labels")}
        for label in add:
            if label.name not in existing:
                body = {"name": label.name, "color": label.color, "description": label.description}
                self._repo(repo, "POST", "/labels", json=body)
        self._repo(repo, "POST", f"/issues/{number}/labels", json={"labels": [label.name for label in add]})
        log.info("%s#%d: labels %s", repo, number, ", ".join(label.name for label in wanted))

    def latest_check(self, repo: str, head_sha: str) -> dict[str, Any] | None:
        """The App's newest `Theseus` check run on the commit, the one a required check reads, or None."""
        found = self._repo(
            repo,
            "GET",
            f"/commits/{head_sha}/check-runs",
            params={"check_name": CHECK_NAME, "app_id": self.app_id, "filter": "all"},
        ).json()
        runs = found.get("check_runs") or []
        return max(runs, key=lambda r: int(r["id"])) if runs else None

    def upsert_check(
        self,
        repo: str,
        head_sha: str,
        conclusion: str,
        title: str,
        summary: str,
        *,
        source: str = REVIEW,
        annotations: list[dict[str, Any]] | None = None,
    ) -> int:
        """Completes the App's newest `Theseus` check run on the commit, creating it if there is none. Returns
        its ID. `source` is REVIEW for a review's verdict, NOTHING_CHANGED for the pass that needs none.
        `annotations` are notes GitHub shows beside those lines in Files changed."""
        self._require(repo)
        output: dict[str, Any] = {"title": title[:TITLE_MAX], "summary": summary[:SUMMARY_MAX]}
        if annotations:
            output["annotations"] = annotations[:ANNOTATIONS_MAX]
        done = {"status": "completed", "conclusion": conclusion, "output": output, "external_id": source}
        latest = self.latest_check(repo, head_sha)
        if latest is not None:
            cid = int(latest["id"])
            self._repo(repo, "PATCH", f"/check-runs/{cid}", json=done)
        else:
            cid = int(
                self._repo(
                    repo, "POST", "/check-runs", json={"name": CHECK_NAME, "head_sha": head_sha, **done}
                ).json()["id"]
            )
        log.info("%s@%s: check %s is %s", repo, head_sha[:7], cid, conclusion)
        return cid

    def pending_check(self, repo: str, head_sha: str, title: str, summary: str) -> int:
        """Shows the commit's `Theseus` check as in progress with this title, so the merge waits and says why.
        Updates the App's newest check when it is already in progress, else posts a new one, so a finished
        verdict stays in the check's history. Returns its ID."""
        self._require(repo)
        output = {"title": title[:TITLE_MAX], "summary": summary[:SUMMARY_MAX]}
        latest = self.latest_check(repo, head_sha)
        if latest is not None and latest.get("status") != "completed":
            cid = int(latest["id"])
            self._repo(repo, "PATCH", f"/check-runs/{cid}", json={"output": output})
        else:
            body = {
                "name": CHECK_NAME,
                "head_sha": head_sha,
                "status": "in_progress",
                "external_id": REVIEW,
                "output": output,
            }
            cid = int(self._repo(repo, "POST", "/check-runs", json=body).json()["id"])
        log.info("%s@%s: check %s in progress: %s", repo, head_sha[:7], cid, title)
        return cid

    def withdraw_pass(self, repo: str, head_sha: str, number: int) -> bool:
        """When the commit's newest check is the pass for a PR that changes nothing under the world root, and
        PR `number` (same head, another base) does change it, posts a new in-progress check so the required
        check waits for that review. It stays pending, never green, until a review completes it. Returns
        whether it withdrew one."""
        self._require(repo)
        latest = self.latest_check(repo, head_sha)
        if latest is None:
            return False
        title = (latest.get("output") or {}).get("title") or ""
        if (
            latest.get("external_id") != NOTHING_CHANGED
            and title != f"Nothing under {self.world_root} changed"
        ):
            return False
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            return False
        output = {
            "title": "Review pending",
            "summary": f"#{number} changes `{self.world_root}/` at this commit, so the earlier pass for a "
            "pull request that changed nothing there no longer counts. Theseus reviews it next.",
        }
        created = self._repo(
            repo,
            "POST",
            "/check-runs",
            json={
                "name": CHECK_NAME,
                "head_sha": head_sha,
                "status": "in_progress",
                "external_id": REVIEW,
                "output": output,
            },
        ).json()
        log.info(
            "%s@%s: withdrew pass %s for #%d; check %s pending",
            repo,
            head_sha[:7],
            latest["id"],
            number,
            created["id"],
        )
        return True

    # Re-running a review ----------------------------------------------------------------------------------

    def latest_run(self, repo: str, head_sha: str) -> dict[str, Any] | None:
        """The newest run of the Theseus workflow for the commit, or None if it never ran there."""
        found = self._repo(
            repo, "GET", f"/actions/workflows/{WORKFLOW}/runs", params={"head_sha": head_sha, "per_page": 1}
        ).json()
        runs = found.get("workflow_runs") or []
        return runs[0] if runs else None

    def rerun_review(self, repo: str, head_sha: str) -> str:
        """Re-runs the newest Theseus workflow run for the commit: "rerun", "running" when one is still going,
        or "none" when the workflow never ran on that commit."""
        run = self.latest_run(repo, head_sha)
        if run is None:
            return "none"
        if run.get("status") != "completed":
            log.info(
                "%s@%s: run %s is %s; not starting another", repo, head_sha[:7], run["id"], run.get("status")
            )
            return "running"
        self._repo(repo, "POST", f"/actions/runs/{run['id']}/rerun")
        log.info("%s@%s: re-ran run %s", repo, head_sha[:7], run["id"])
        return "rerun"
