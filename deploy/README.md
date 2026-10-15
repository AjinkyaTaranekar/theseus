# Deploying Theseus

The API runs on **guest-box**, a container on an Oracle ARM host, reachable only through our tailnet. Tailscale
Funnel publishes it at **https://guest-box.tail27b7c5.ts.net**, with Tailscale's certificate, so there is no
domain to buy, no Caddy and no open port. FalkorDB is on FalkorDB Cloud. guest-box has no Docker and no
systemd, so the API runs from a venv under `deploy/run.sh`, which restarts it if it exits.

A host with Docker and public ports 80 and 443 can run the Compose stack instead (`deploy/docker-compose.yml`
with Caddy, deployed by `deploy.sh`); see the end of this file.

## The host

| Item | Value |
| --- | --- |
| Host | `guest-box`: Ubuntu 24.04 in a container on an Oracle ARM host; 4 cores, 22 GB, 50 GB disk |
| SSH | `ssh dev@100.104.51.40`, from a machine on the tailnet |
| Public URL (`DOMAIN`) | `https://guest-box.tail27b7c5.ts.net`, through Tailscale Funnel |
| Deploy clone | `~/theseus`, a read-only deploy key ("guest-box (read-only deploy)") |
| Logs | `~/theseus-logs/api.log` |

## One-time setup

1. **Tailscale.** The host is in our tailnet; join it to reach SSH. In the admin console, turn on HTTPS
   certificates and Funnel. On the host, let `dev` manage it once: `sudo tailscale set --operator=dev`.
2. **The repo.** The repo is private, so the host has its own read-only deploy key. `git clone
   git@github.com:<owner>/theseus.git ~/theseus`, then `python3 -m venv ~/theseus/.venv` and
   `~/theseus/.venv/bin/pip install ~/theseus`.
3. **Secrets.** Copy your `.env` to `~/theseus/.env` and run `chmod 600 ~/theseus/.env`. Set
   `DOMAIN=guest-box.tail27b7c5.ts.net`. Never commit it.
4. **Start and publish.** `bash ~/theseus/deploy/run.sh start`, then `tailscale funnel --bg 8000`. Funnel keeps
   its setting across restarts; the runner does not survive the container restarting, so start it again then,
   or add `su dev -c 'bash ~/theseus/deploy/run.sh start'` to the container's start script.
5. **FalkorDB Cloud.** If the instance has an IP allowlist, add the host's public address (`curl ifconfig.me`).

## Deploy

From a machine on the tailnet, after the PR is merged to `main`:

```bash
deploy/deploy-funnel.sh dev@100.104.51.40    # exits 0 only once https://<DOMAIN>/health answers
THESEUS_REF=f7-action-app deploy/deploy-funnel.sh dev@100.104.51.40    # try a branch before it merges
```

It records the running commit, resets the clone to `origin/<THESEUS_REF>` (default `main`), installs it into the
venv, restarts the runner, and waits for the API's own `/health`, then for the public one. If either never
answers, it returns to the previous commit and says whether that recovered (`ROLLED_BACK`) or not
(`ROLLBACK_FAILED`).

The API will not start without FalkorDB: startup connects and fails if it cannot. `/health` returns 503 with
`"falkordb": "unreachable"` if FalkorDB Cloud stops answering later. So a failed deploy can also mean the
database is down: read `~/theseus-logs/api.log`.

## The GitHub App

The App posts the comment and the `Theseus` check, and re-runs a review on `/theseus review` or Re-run
(`docs/spec/07-github-and-deploy.md`, "The GitHub App"). Its settings live in
[`github-app-manifest.json`](github-app-manifest.json). Register it once the API answers on `https://<DOMAIN>`:

1. **Register.** Run `python tools/github_app.py form --domain <DOMAIN>`, open the page it writes, and click
   the button. GitHub shows the settings from the manifest. If the name `Theseus` is taken, pick another;
   the check is still called `Theseus`. Click **Create GitHub App**.
2. **Save its credentials, within an hour.** GitHub sends you to the repo page with `?code=...` in the
   address bar. Run `python tools/github_app.py convert <code> --out <folder outside the repo>`. It writes
   `theseus.private-key.pem` and `github-app.env` there, readable only by you, and prints no secret.
3. **Install it on this repo only.** On the App's page: **Install App**, your account, **Only select
   repositories**, `theseus`.
4. **Give the host the key and the settings.**
   - Copy the key to `~/theseus/secrets/theseus.private-key.pem` on the host and `chmod 400` it. (With
     Compose, the container runs as user 10001, so also `sudo chown 10001` it there.)
   - Add the three lines of `github-app.env` to `~/theseus/.env`, with `GITHUB_APP_PRIVATE_KEY_PATH` set to the
     key's full path on guest-box (`/home/dev/theseus/secrets/theseus.private-key.pem`; with Compose,
     `/app/secrets/theseus.private-key.pem`), plus `THESEUS_REPOS=<owner>/theseus` and
     `THESEUS_TOKEN=<a long random string>` (`openssl rand -hex 32`).
   - Restart: `bash ~/theseus/deploy/run.sh restart` (with Compose, `docker compose -f
     deploy/docker-compose.yml up -d`).
5. **Tell the Action where to send reviews.** In the repo: `gh variable set THESEUS_URL --body https://<DOMAIN>`
   and `gh secret set THESEUS_TOKEN` (paste the same token).
6. **Try it.** Open a PR from `demo/trial-1` that edits a comment in `demo-infra/terraform/people.tf`, with
   label `demo`. Theseus's comment and the `Theseus` check should appear. Comment `/theseus review` and click
   **Re-run** on the check: each starts a new run of the Theseus workflow.
7. **Block merges on it.** Settings, **Rules**, **Rulesets**, **New branch ruleset**: target `main`, turn on
   **Require status checks to pass**, add `Theseus`, and set its source to the App. Both of you agree first.

## Rotating a secret

Edit `~/theseus/.env` on the host, then `bash ~/theseus/deploy/run.sh restart`. For a key that was exposed,
revoke it at its source first (Crusoe, TypeSafe, FalkorDB Cloud, or the GitHub App), then update `.env`.

## On a host with Docker and public ports instead

`deploy/docker-compose.yml` runs the API and Caddy, which serves HTTPS for the `DOMAIN` in `.env`.

1. **Firewall.** Allow inbound TCP 80 and 443 (and 22 from your IP only). Oracle's Ubuntu images also block
   ports in iptables: `sudo iptables -I INPUT 6 -p tcp -m multiport --dports 80,443 -m state --state NEW -j
   ACCEPT`, then `sudo netfilter-persistent save`.
2. **Docker.** Install Docker Engine and the compose plugin, and add the SSH user to the `docker` group.
3. **The repo, secrets and FalkorDB** as above; point an A record for `DOMAIN` at the public IP.
4. **Deploy** with `deploy/deploy.sh user@host`: it rebuilds with `docker compose up -d --build`, waits for
   `/health` locally and then on `https://<DOMAIN>`, and rolls back to the previous image if either fails.
