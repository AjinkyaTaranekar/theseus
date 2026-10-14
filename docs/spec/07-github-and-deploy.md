# 07. GitHub and deployment

One repo holds everything: the product, and the demo world in `demo-infra/`. Demo PRs are ordinary PRs in this
repo that change only `demo-infra/`. There is no GitHub org and no second repo.

## The Theseus Action (`.github/workflows/theseus.yml`, task F7)

Runs on `pull_request` (`opened`, `synchronize`, `reopened`) with `paths: ["demo-infra/**"]`, so product PRs never
trigger it. Permissions: `contents: read`, `pull-requests: read`.

1. Check out the head commit, and the base commit into `./base`.
2. Install Terraform 1.16.6, the version P1 checked, with `hashicorp/setup-terraform`.
3. For base and head, in `demo-infra/terraform`: `terraform init -backend=false`, `terraform plan -out tfplan`,
   `terraform show -json tfplan > <side>.plan.json`. The provider block's mock credentials and skip flags mean
   no AWS account is needed (task P1 confirms).
4. Run Checkov on `demo-infra/terraform/` (a pinned version) and keep its JSON summary.
5. `POST $THESEUS_URL/analyze` with the repo, PR number, both SHAs, title, body, both plans and the Checkov
   summary, and the header `X-Theseus-Token: ${{ secrets.THESEUS_TOKEN }}`.

**Never put `${{ github.event.pull_request.title }}` or `.body` inside a `run:` script.** Pass them through
`env:` and read them as variables. Inlining them lets a PR title inject shell commands.

The backend, not the Action, posts the comment and the check, using the GitHub App. Commits made with the
Action's `GITHUB_TOKEN` would not trigger a new run; commits made by the App do.

**The demo world's own workflows** (`demo-infra/workflows/demo-org/...`) are files Theseus reads. GitHub runs
workflows only from the repo root's `.github/workflows/`, so they never run, and the fictional
`demo-thirdparty/file-diff` Action is never fetched.

## The GitHub App (task F7, then A9)

| Setting | Value |
| --- | --- |
| Name | Theseus |
| Installed on | This repo only (`THESEUS_REPOS`) |
| Permissions | Contents read and write; Pull requests read and write; Issues read and write; Checks read and write; Metadata read |
| Events | `pull_request`, `issue_comment`, `push` |
| Webhook URL | `https://<DOMAIN>/webhooks/github`, with `GITHUB_WEBHOOK_SECRET` |
| Auth | A JWT signed with the App's private key, exchanged for an installation token (httpx and PyJWT) |

**Reading files at a commit.** The backend reads `terraform/`, `services/`, `workflows/` and `theseus.yaml` under
the world root (`THESEUS_WORLD_ROOT`, default `demo-infra`) at both SHAs through the contents API.

**Writing is fenced to the world root.** Every commit the App makes (apply, containment, scan fixes) may change
only files under the world root. The backend checks each path before committing and refuses the whole commit
otherwise. The App can write to the product code in principle; this rule is why it never does.

**The comment** is created once and then edited in place. Find it by the marker `<!-- theseus:pr-comment -->`.
Evidence links add the world root to each file (`blob/<head_sha>/demo-infra/terraform/roles.tf#L31`).

**The check run** is named `Theseus`. Conclusion: `success` when nothing opened and no use beyond intent;
`failure` when a dangerous path opened or a use beyond intent appeared and no passing fix is applied;
`neutral` when the only issue is UNKNOWN. The summary is the headline.

## Demo PRs

| Rule | Why |
| --- | --- |
| Branch `demo/<scenario>-<take>`, label `demo`, title as in `02-demo-world.md` | Easy to find, filter and close; product PRs never use the label |
| A demo PR changes only `demo-infra/` | The Action's `paths` filter, and a clean diff on screen |
| A product PR never changes `demo-infra/` (except tasks F4 and C1) | CODEOWNERS sends `demo-infra/` to both humans |
| Practice: open, check, close. Record on a fresh branch per take | Closing deletes the PR's graphs; old takes never clutter the video |
| `main` holds the world with no scenario applied | Each PR starts from the same `main` the fixtures were made from |

## The apply command (task A9)

1. An `issue_comment` on a PR matches `^/theseus apply ([A-Z])\s*$`.
2. The commenter must have write or admin permission on the repo; otherwise reply that they cannot.
3. Load the latest result for that PR and head SHA (cached in memory, keyed by repo, PR and SHA), or re-run the analysis.
4. The candidate must exist and have verdict `pass`. Otherwise reply with its verdict and reason.
5. `render_tf` the candidate's ops on the head `.tf` files, check every changed path is under the world root, and
   commit the changed files to the PR branch with the App. The message follows the commit rules in `AGENTS.md`:
   subject `fix: Apply Theseus fix <ID>`, a body naming the paths it closes and the requirements it keeps, and a
   `Requested-by: @<user>` trailer.
6. The commit triggers the Action, which re-runs the analysis; the comment updates and the check turns green.

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
against a FalkorDB service container pinned to the version the Cloud instance reports (P1 records it), so
both run the same procedures.

## Docker Compose (`deploy/docker-compose.yml`, task F3)

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
| `ANTHROPIC_API_KEY` | | Claude |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Intent and fixes |
| `CLAUDE_FAST_MODEL` | `claude-haiku-5-5` | Jev fallback only |
| `TYPESAFE_API_KEY` | | Jev |
| `JEV_BASE_URL` | `https://api.typesafe.ai` | Jev |
| `JEV_MODEL` | `jev-latest` | Jev |
| `FALKORDB_HOST`, `FALKORDB_PORT` | `localhost`, `6379` | The FalkorDB Cloud instance |
| `FALKORDB_USERNAME`, `FALKORDB_PASSWORD` | empty | Its credentials |
| `FALKORDB_TLS` | `false` | Connect over TLS when the instance requires it (P1 records which) |
| `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_WEBHOOK_SECRET` | | The GitHub App |
| `THESEUS_TOKEN` | | Shared secret the Action sends |
| `THESEUS_REPOS` | empty | Repos the backend will act on (this repo, as `owner/theseus`); everything else is refused |
| `THESEUS_WORLD_ROOT` | `demo-infra` | Folder read for analysis; the only folder the App may write to |
| `DOMAIN` | | Caddy's public hostname |

## The VM

Oracle Always Free Ampere A1 (2 OCPUs, 12 GB) runs the API and Caddy; FalkorDB is on FalkorDB Cloud. Only port
443 is public. Secrets live in `.env` on the VM, readable by the deploy user only.
Rate-limit `POST /try/*` to 10 requests a minute per IP.
