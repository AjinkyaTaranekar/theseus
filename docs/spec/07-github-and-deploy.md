# 07. GitHub and deployment

One repo holds everything: the product, and the demo world in `demo-infra/`. Demo PRs are ordinary PRs in this
repo that change only `demo-infra/`. There is no GitHub org and no second repo.

## The Theseus Action (`.github/workflows/theseus.yml`, task F7)

Two workflows, because planning runs the PR's own Terraform: a `data "external"` block runs a program during the
plan, and anything it plants (a `BASH_ENV` hook through `GITHUB_ENV`, a file) reaches every later step of that
job. So the run that plans holds no secret at all, and a separate run that never touches PR code sends the
result.

**`Theseus` (untrusted).** Runs on `pull_request` (`opened`, `synchronize`, `reopened`, `edited`) with
`paths: ["demo-infra/**"]`, so product PRs never trigger it. `edited` is a changed title or description, which
intent depends on. One run per PR at a time: `concurrency: theseus-<PR number>` with `cancel-in-progress`.
Permissions: `contents: read`. No secrets, no `THESEUS_URL`.

1. Check out the head commit, and the base commit into `./base`, without persisting credentials.
2. Install Terraform 1.16.6, the version P1 checked, with `hashicorp/setup-terraform`.
3. For base and head, in `demo-infra/terraform`: `terraform init -backend=false`, `terraform plan -out tfplan`,
   `terraform show -json tfplan > <side>.plan.json`, through `tools/plan.sh` from the base commit, never the PR.
   The provider block's mock credentials and skip flags mean no AWS account is needed (task P1 confirms).
4. Run Checkov 3.3.29 on `demo-infra/terraform/` and keep its JSON summary.
5. Write `review.json` (`pr_number`, both plans, the Checkov summary) and upload it as the artifact
   `theseus-review`.

**`Theseus publish` (trusted).** Runs on `workflow_run` when `Theseus` completes, and only when that run came
from a `pull_request` and succeeded. GitHub always runs main's copy of a `workflow_run` workflow, so a PR cannot
change it. It holds `THESEUS_TOKEN`, never checks out or runs PR code, and treats the artifact as data: it
refuses a missing file, a symlink, more than 50 MB or the wrong shape, then builds the request with `jq`. It
sends `POST $THESEUS_URL/analyze` with the repo, the PR number from the artifact, **the head commit from its own
event** (`workflow_run.head_sha`), both plans and the Checkov summary, and the header `X-Theseus-Token`.

**Fork PRs** get a review the same way: GitHub withholds secrets from the fork's own run, but not from
`Theseus publish`. (GitHub may ask a maintainer to approve the first run of a new contributor's fork.)

**What the backend trusts.** The commit comes from the trusted event; the PR number comes from the untrusted
artifact, so the backend reads the PR from the API and writes the comment only when that PR's head is the
reviewed commit. The check always goes on the reviewed commit, so a wrong PR number can only check that
commit, never another PR. The PR's title and body are read from the API, never from the request.

**No `run:` step in either workflow uses `${{ }}`;** values reach the shell through `env:`. Unit tests check
this, that `Theseus` mentions no secret, and that `Theseus publish` never checks out code.

**Before it is on `main`,** `Theseus publish` does not run, because `workflow_run` workflows run only from the
default branch.

The backend, not the Action, posts the comment and the check, using the GitHub App. Commits made with the
Action's `GITHUB_TOKEN` would not trigger a new run; commits made by the App do.

**The demo world's own workflows** (`demo-infra/workflows/demo-org/...`) are files Theseus reads. GitHub runs
workflows only from the repo root's `.github/workflows/`, so they never run, and the fictional
`demo-thirdparty/file-diff` Action is never fetched.

## The GitHub App (task F7, then A9)

| Setting | Value |
| --- | --- |
| Name | Theseus Graph Review (`theseus-graph-review`, App ID 5336067): GitHub reserves "Theseus" for an existing account. The check it posts is still named `Theseus` |
| Installed on | This repo only (`THESEUS_REPOS`) |
| Permissions | Contents read and write; Pull requests read and write; Issues read and write; Checks read and write; Actions read and write (to re-run the Theseus workflow); Metadata read |
| Events | `pull_request`, `issue_comment`, `push`, and `check_run` (sent to any App with Checks write) |
| Webhook URL | `https://<DOMAIN>/webhooks/github`, with `GITHUB_WEBHOOK_SECRET` |
| Auth | A JWT signed with the App's private key, exchanged for an installation token (httpx and PyJWT) |

**Reading files at a commit.** The backend reads `terraform/`, `services/`, `workflows/` and `theseus.yaml` under
the world root (`THESEUS_WORLD_ROOT`, default `demo-infra`) at both SHAs: one tree request lists them, then one
GraphQL query per 100 files reads them, each path passed as a variable (`<sha>:<path>`), never inside the query.
A file GraphQL cannot give whole (binary or truncated) is read through the contents API.

**Writing is fenced to the world root.** Every commit the App makes (apply, containment, scan fixes) may change
only files under the world root. The backend checks each path before committing and refuses the whole commit
otherwise. The App can write to the product code in principle; this rule is why it never does.

**The comment** is created once and then edited in place. Find it by the marker `<!-- theseus:pr-comment -->`,
in a comment the App itself wrote: a person who pastes the marker into their own comment never gets it edited.
A review of a commit that is no longer the PR's head (a re-run of an old run) updates that commit's check but
leaves the comment to the newer run.
Evidence links add the world root to each file (`blob/<head_sha>/demo-infra/terraform/roles.tf#L31`).

**The check run** is named `Theseus`. Conclusion: `success` when nothing opened and no use beyond intent;
`failure` when a dangerous path opened or a use beyond intent appeared and no passing fix is applied;
`neutral` when the only issue is UNKNOWN. "Blocking a merge" below makes it required.

## When Theseus reviews (tasks F7 and A5)

| Moment | What starts it | What happens |
| --- | --- | --- |
| A PR that changes `demo-infra/` is opened or reopened, drafts included | The Action (`opened`, `reopened`) | A full review: plans, Checkov, analysis, the comment and the check. The App shows the check in progress at once (below) |
| A commit is pushed to it | The Action (`synchronize`) | A full review of the new head. The newest run cancels an older one still running |
| Its title or description is edited | The Action (`edited`) | A full review. Intent comes from that text, and the headline asks authors who said nothing to say what the PR is for |
| A fix is applied with `/theseus apply <ID>` | The App's commit (`synchronize`) | A full review of the fixed head |
| Someone with write access comments `/theseus review` | The App (`issue_comment`) | The App re-runs the PR's latest Theseus workflow run for the head commit |
| Someone clicks **Re-run** on the `Theseus` check | The App (`check_run`, `rerequested`) | The same as `/theseus review` |
| A PR changes nothing under `demo-infra/` | The App (`pull_request`) | No review: a `success` check, "Nothing under demo-infra changed" |
| The Theseus workflow fails or times out before its review | `Theseus publish` (`POST /review-failed`) | The check fails, "Review could not run", with a link to the run, unless a verdict is already on the commit. A run cancelled by a newer push is left alone |
| A PR is closed | The App (`pull_request`, `closed`) | Its graphs are deleted |
| A push to `main` | The App (`push`) | A scan of `main` |

**Re-running** repeats the newest Theseus workflow run for the PR's head commit, so the plans are made
again. If that run is still going, nothing more starts. A check on a PR that changes nothing under the world
root has no run to repeat; Re-run posts its `success` check again.

**While a review runs, the check says so.** From the moment a PR that changes the world root is opened, pushed
to, edited or reviewed again, the App shows the commit's `Theseus` check in progress, so the merge box waits
and says why:

| Stage | Set by | Check title |
| --- | --- | --- |
| The Action plans both commits | The `pull_request` webhook | Reviewing: planning both commits |
| `/theseus review` or Re-run | The webhook, after it re-runs the workflow | Reviewing again: planning both commits |
| The backend builds the graphs and traces paths | `/analyze`, as it starts | Reviewing: tracing paths in FalkorDB |
| Done | `/analyze` | The verdict, or "Review could not finish" with the reason |

Each summary says in a sentence what Theseus is doing. A check already in progress is updated; a finished one
gets a new check run, so the commit's earlier verdict stays in its history.

**Webhooks** are checked against `GITHUB_WEBHOOK_SECRET` (`X-Hub-Signature-256`) before anything in them is
read, and an event from a repo outside `THESEUS_REPOS` is refused. Registering the App, installing it and
setting its secrets: `deploy/README.md`, "The GitHub App", from `deploy/github-app-manifest.json`.

**Requesting a review from the App is not relied on.** GitHub documents review requests for people and teams,
not Apps. F7 tests it once the App exists; if GitHub allows it, the App treats a `review_requested` event that
names it like `/theseus review`.

**A review reads the PR's current title and body** from the API, not the copy the Action sends: re-running a
workflow replays the event that first started it, and that copy may be out of date.

## Blocking a merge (tasks F7 and A5)

A comment cannot stop a merge; a required check can.

**The ruleset "main: reviewed by the other human"** (active) requires a PR with one approving review, so the
other human signs off every change, and the `Theseus` check. A "Request changes" review blocks the merge until
it is resolved. A push dismisses an earlier approval, and `main` cannot be force-pushed or deleted. Repo admins
may bypass it through the PR in an emergency, and GitHub records that.

- **The ruleset requires the `Theseus` check,** with its source set to the Theseus App (ID 5336067), so a
  workflow in a PR cannot post a passing check of the same name. `failure` blocks the merge; `success` and
  `neutral` let it through; a check still in progress keeps it waiting. A person added the check to the
  ruleset with A5.
- **Every PR gets the check** (the table above). Without that, a PR that never runs the Action would wait for
  the check forever.
- **A check belongs to one commit.** Each push needs a new review, so a pass never covers code it did not see.
- **It fails closed.** If the backend is down, no check arrives, and the merge box shows it as expected and
  waiting. When the backend is back, `/theseus review` starts the review. A review that cannot finish, or a
  workflow that fails before it, fails the check with the reason and how to try again.
- **Applying a fix unblocks the merge.** The App's commit starts a new review; when the fixed head opens no
  dangerous path, the check passes.
- **The check's title is the verdict in plain words,** because the merge box shows it. Its summary is the
  comment's first section.

## The review page

The card ends with **Open the graph Theseus checked →**, a link to
`https://<DOMAIN>/reviews/<owner>/<repo>/<number>?k=<signature>`. The page (`theseus/web/review.html`) draws
the PR's head and base graphs with Cytoscape.js (cdnjs, a pinned version with SRI): the opened paths
highlighted, the hop the PR adds in red, each node's class and who set it, and each arrow's evidence linked to
its line. "Before it" shows the base graph and the paths the PR closes.

- **Everything comes from FalkorDB.** After each review of the PR's current head, the backend keeps the result in
  the store (`theseus__docs`, one document per PR) before it posts the comment, so the link works at once. The
  page reads the result and both graphs from the store when it is opened. A restart or a redeploy changes
  nothing; a newer review replaces them, and closing the PR deletes the graphs.
- **The link is signed.** `k` is the first 32 hex characters of HMAC-SHA256 of `review:<owner>/<repo>#<number>`
  with `THESEUS_TOKEN`. Anyone who can read the comment can open the page; a wrong or missing `k`, another PR,
  or a repo outside `THESEUS_REPOS` gets a 404 that says nothing about what exists. Without `DOMAIN` or
  `THESEUS_TOKEN` the comment has no link.
- **The page carries no data in its URL.** A review's graphs are about 100 KB; a URL holds a few KB, and a copy
  in a link could never be taken back.

## Labels

After each review of a PR's current head, the App sets its labels from the result (`agent/labels.py`), so the PR
list shows what Theseus found at a glance and the labels can be counted later. Every label starts with
`theseus: `. The App adds and removes only those, never `demo` or a person's labels, and creates any the repo
lacks with its colour and description. A re-run of an old commit leaves the labels to the newer run.

| Labels | When |
| --- | --- |
| `theseus: S0` to `theseus: S6`, exactly one | Severity, by the first rule that holds (below) |
| `theseus: blocked`, `theseus: needs a look`, `theseus: clear`, exactly one | The verdict, as the check run's |
| `theseus: regulated data` or `theseus: confidential data` | The most sensitive class an opened path or a code read beyond intent reaches |
| `theseus: grants more than it says` | The PR states a purpose, and the change reaches data its intent does not ask for |
| `theseus: steering text` | The intent is suspicious |

**Severity.** Code that reads data beyond intent counts like a path to that data: it is use, not only the
chance of it.

| Severity | The first that holds |
| --- | --- |
| S0 | Anyone on the internet can reach regulated data |
| S1 | Someone inside reaches regulated data, or the internet reaches confidential data |
| S2 | A new path or code read reaches confidential data |
| S3 | A new path or code read reaches data of unknown sensitivity |
| S4 | Theseus could not check part of the change |
| S5 | No new access, but the PR states no purpose or its text steers the review |
| S6 | No new access to sensitive data |

## Demo PRs

| Rule | Why |
| --- | --- |
| Branch `demo/<scenario>-<take>`, label `demo`, title as in `02-demo-world.md` | Easy to find, filter and close; product PRs never use the label |
| A demo PR changes only `demo-infra/` | The Action's `paths` filter, and a clean diff on screen |
| CI skips a `demo/` branch; its only check is `Theseus` | CI's tests pin `demo-infra/` to `main`, so they fail by design on a PR that changes it |
| A product PR never changes `demo-infra/` (except tasks F4 and C1) | CODEOWNERS sends `demo-infra/` to both humans |
| Practice: open, check, close. Record on a fresh branch per take | Closing deletes the PR's graphs; old takes never clutter the video |
| `main` holds the world with no scenario applied | Each PR starts from the same `main` the fixtures were made from |

## The apply command (task A9)

1. An `issue_comment` on a PR matches `^/theseus apply ([A-Z][0-9]*)\s*$` (a rule's or the LLM's letter, or a
   person's `H1`, `H2`, ...).
2. The commenter must have write or admin permission on the repo; otherwise reply that they cannot.
3. Load the latest result for that PR and head SHA (cached in memory, keyed by repo, PR and SHA), or re-run the analysis.
4. The candidate must exist and have verdict `pass`. Otherwise reply with its verdict and reason.
5. Render the candidate's ops on the head `.tf` files with the IaC adapter (`adapters/terraform/render.py`),
   check every changed path is under the world root, and commit the changed files to the PR branch with the
   App. The message follows the commit rules in `AGENTS.md`: subject `fix: Apply Theseus fix <ID>`, a body
   naming the paths it closes and the requirements it keeps, and two trailers: `Proposed-by:` (the
   candidate's `proposed_by`) and `Requested-by: @<user>` (who approved it).
6. The commit triggers the Action, which re-runs the analysis; the comment updates and the check turns green.

### Proposing a fix (task A9, stretch)

A person with write access can propose their own fix for Theseus to check before anyone commits it:
`/theseus propose` followed by a fenced JSON block holding a list of patch ops (`{provider, op, args}`, the
cloud adapter's catalog). Theseus validates the ops, simulates them like any candidate, gives them the next
`H<n>` ID with `source: "human"` and the commenter as `proposed_by`, and updates the comment's fix table.
`/theseus apply H<n>` then works like any other ID. Pushing a commit to the PR is the other way to fix it
by hand; that is not a candidate, just a new head that the Action analyzes again.

## Finding and scan outputs (tasks FM6, C3)

- **Containment PR:** branch `theseus/contain-<finding-id>` from `main`, label `demo`, title and commit subject
  `fix: Contain <finding-id>`; it changes `demo-infra/terraform/ci.tf` only. The body holds the blast radius,
  the cut, the verification and the rotate list.
- **Rotate issue:** title `Rotate these secrets: <finding-id>`, label `demo`, listing exactly the secrets from the
  rotate list.
- **Scan issue:** title `Theseus scan: <n> dangerous paths in main`, label `demo`, plus one PR per passing U
  candidate, titled and committed as `fix: Remove unused grant <Sid>`.

## Where FalkorDB runs

FalkorDB Cloud, for development, tests and the deployed API. Nobody needs Docker on a laptop. The app reads
the instance's connection settings from `.env` (`FALKORDB_*` below). CI runs the `falkordb` marked tests
against a `falkordb/falkordb:v4.22.0` service container, the version the Cloud instance reports, so both
run the same procedures. Upgrade both together.

**The instance (P1):** FalkorDB 4.22.0 (graph module version 42200, the enterprise build) on Redis 8.10.2,
Linux arm64. It speaks plain TCP on its port, with no TLS, and needs a username and password. Its
`algo.maxFlow` takes one relationship type at a time (`03-graph.md`, "What FalkorDB 4.22 requires").

## Docker Compose (`deploy/docker-compose.yml`, task F3)

For a host with Docker and public ports 80 and 443. guest-box, where we run today, has neither: see "The VM".

| Service | Image | Notes |
| --- | --- | --- |
| `api` | Built from `deploy/Dockerfile` (`python:3.12-slim`, `pip install .`, `uvicorn theseus.api.app:app`) | Reads `.env`, including the FalkorDB Cloud settings |
| `caddy` | `caddy:2` | Ports 80 and 443. Caddyfile: `{$DOMAIN} { reverse_proxy api:8000 }` with automatic HTTPS |

`deploy/deploy.sh` connects to the VM over SSH, pulls `main`, runs `docker compose up -d --build`, then checks
`GET /health`. If the check fails, it rolls back to the previous image tag.

## Environment variables (`theseus/config.py`, `.env.example`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `THESEUS_MODE` | `replay` | `replay`, `record` or `live` for model calls |
| `LLM_MODEL` | `openai/zai-org/GLM-5.3` | Intent and fixes, as a LiteLLM model string (`06-agent.md`) |
| `LLM_FAST_MODEL` | `openai/zai-org/GLM-5.3-Flash` | Jev fallback only |
| `LLM_API_BASE` | `https://api.inference.crusoecloud.com/v1` | Crusoe's OpenAI-compatible endpoint, or the endpoint of whichever provider `LLM_MODEL` names |
| `LLM_API_KEY` | | The Crusoe key, or the key of whichever provider `LLM_MODEL` names |
| `TYPESAFE_API_KEY` | | Jev |
| `JEV_BASE_URL` | `https://api.typesafe.ai` | Jev |
| `JEV_MODEL` | `jev-latest` | Jev |
| `FALKORDB_HOST`, `FALKORDB_PORT` | `localhost`, `6379` | The FalkorDB Cloud instance |
| `FALKORDB_USERNAME`, `FALKORDB_PASSWORD` | empty | Its credentials |
| `FALKORDB_TLS` | `false` | Connect over TLS. Our instance speaks plain TCP, so it stays `false` |
| `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_WEBHOOK_SECRET` | | The GitHub App |
| `THESEUS_TOKEN` | | Shared secret the Action sends |
| `THESEUS_REPOS` | empty | Repos the backend will act on (this repo, as `owner/theseus`); everything else is refused |
| `THESEUS_WORLD_ROOT` | `demo-infra` | Folder read for analysis; the only folder the App may write to |
| `DOMAIN` | | The public hostname: the Funnel name on guest-box (`guest-box.tail27b7c5.ts.net`), or Caddy's under Compose |

## The VM

**guest-box**, a container (Ubuntu 24.04, arm64, 4 cores, 22 GB) on an Oracle ARM host, runs the API; FalkorDB
is on FalkorDB Cloud. It has no Docker, no systemd and no public port, and is reached over our tailnet
(`ssh dev@100.104.51.40`). **Tailscale Funnel** publishes the API at `https://guest-box.tail27b7c5.ts.net`, with
Tailscale's certificate: the only public way in, which GitHub's webhooks and the Action's `THESEUS_URL` use. The
API runs from a venv on `127.0.0.1:8000` under `deploy/run.sh`, which restarts it when it exits;
`deploy/deploy-funnel.sh` deploys a commit and rolls back if the public `/health` never answers. Secrets live in
`.env` on the host, readable by `dev` only. `deploy/README.md` has the setup.

**Deploys are manual.** The `Deploy` workflow (`.github/workflows/deploy.yml`, `workflow_dispatch` with a
`ref`) runs that script from GitHub: the runner joins the tailnet as an ephemeral `tag:ci` node through a
Tailscale OAuth client and logs in over Tailscale SSH, which the tailnet policy allows for `tag:ci` as `dev` on
`tag:server`. No SSH key is stored in GitHub, and the OAuth secret sits in the `production` environment, which
only workflows on `main` may use.
Rate-limit `POST /try/*` to 10 requests a minute per IP.
