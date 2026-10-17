# Connect a repository to Theseus

Theseus reviews every pull request that changes your infrastructure, keeps a graph of `main` in FalkorDB,
and shows both on one dashboard. Connecting a repository takes five steps. The dashboard ticks each one off
as Theseus sees it done.

## 1. Run the backend

Theseus is one FastAPI service next to FalkorDB. `deploy/README.md` covers the VM and Docker Compose. It
needs these settings (`.env.example` lists them all):

| Setting | What it is |
| --- | --- |
| `FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_PASSWORD` | Where the graphs live. The API refuses to start without FalkorDB |
| `THESEUS_TOKEN` | A long random string. The workflows send it, and it signs every page link |
| `THESEUS_REPOS` | The repositories Theseus acts on, such as `my-org/infra` |
| `THESEUS_WORLD_ROOT` | The folder that holds the infrastructure, such as `demo-infra` |
| `DOMAIN` | The public hostname, for page links |
| `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_WEBHOOK_SECRET` | The GitHub App from step 2 |

## 2. Install the GitHub App

Create the App from `deploy/github-app-manifest.json` (`deploy/README.md`, "The GitHub App") and install it
on the repository. It reads the world root, posts the comment and the `Theseus` check, and commits a fix only
after a person with write access asks for it.

## 3. Add `theseus.yaml` and the workflows

- **`<world root>/theseus.yaml`** says which cloud account and region the code describes, what must keep
  working (`requirements`: who needs which access to what), and any data class you want to set by hand.
  `demo-infra/theseus.yaml` is a full example.
- **`.github/workflows/theseus.yml` and `theseus-publish.yml`** review pull requests. Copy them as they are.
- **`.github/workflows/theseus-main.yml`** builds `main`'s graph on every push to `main`, every night and on
  demand.
- In the repository settings, add the variable `THESEUS_URL` (the backend's address) and the secret
  `THESEUS_TOKEN`.
- Require the `Theseus` check on `main` (a ruleset), so a blocked review blocks the merge.

## 4. Build `main`'s graph

Open **Actions → Theseus main → Run workflow**. Theseus plans `main` and loads it into FalkorDB. It then
works out who can reach which sensitive data, the single points of failure and articulation points, the
grants no code uses, an estimated monthly cost, and any advisory in the feed that affects your workflows. The
run prints the dashboard's link, and the dashboard shows the result.

## 5. Open a pull request

Change something under the world root and open a PR. Within seconds the `Theseus` check reads "Reviewing:
planning both commits". A few minutes later the PR has the comment, the labels and a link to its review page.

## How each part runs

| What | When | By hand |
| --- | --- | --- |
| PR review | Every push to a PR that changes the world root, and every edit of its title or description | Comment `/theseus review`, or **Re-run** on the check |
| Apply a fix | When a person with write access comments `/theseus apply <ID>` on a fix that passed | `POST /apply` |
| Posture of `main` | Every push to `main` that changes the world root, and every night at 03:17 UTC | **Run workflow** on `Theseus main`, or `python -m theseus posture <world root> <plan.json>` |
| Advisories | Each posture run checks every file in `advisories/` | `python -m theseus finding fixtures/compromised-action` |

The CLI commands need the same FalkorDB settings as the API.
