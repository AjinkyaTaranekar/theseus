# Deploying Theseus

The API runs on an Oracle Always Free VM behind Caddy, which serves HTTPS on the domain in `.env`. FalkorDB is
on FalkorDB Cloud, so the VM runs only two containers: `api` and `caddy`.

## Status

The image, the compose file and `deploy.sh` are written, and CI builds the image on every PR. The VM steps
below are parked until we have the VM. Fill these in as you go:

| Item | Value |
| --- | --- |
| VM shape (`uname -m`, `nproc`, `free -h`) | not checked yet |
| Public IP | not set yet |
| `DOMAIN` | not chosen yet |
| SSH user | not known yet |

## One-time VM setup

1. **Firewall.** In the VM's subnet security list, allow inbound TCP 80 and 443 (and 22 from your IP only).
   Oracle's Ubuntu images also block ports in iptables, so open them there too:
   `sudo iptables -I INPUT 6 -p tcp -m multiport --dports 80,443 -m state --state NEW -j ACCEPT`, then
   `sudo netfilter-persistent save`. Nothing else is exposed: the API listens only inside the compose network.
2. **Docker.** Install Docker Engine and the compose plugin, and add the SSH user to the `docker` group.
3. **The repo.** The repo is private, so add a read-only deploy key and `git clone` it to `~/theseus`. This
   clone is deploy-only; `deploy.sh` resets it to `origin/main` every time.
4. **Secrets.** Copy your `.env` to `~/theseus/.env` and run `chmod 600 ~/theseus/.env`. Set `DOMAIN`. Never
   commit it; the image never contains it (`.dockerignore`).
5. **DNS.** Point an A record for `DOMAIN` at the VM's public IP. Caddy gets the certificate on first start.
6. **FalkorDB Cloud.** If the instance has an IP allowlist, add the VM's public IP.

## Deploy

From your machine, after the PR is merged to `main`:

```bash
deploy/deploy.sh ubuntu@<vm-ip>    # exits 0 only once https://<DOMAIN>/health answers
```

What it does, and what each failure does:

| Step | Where | If it fails |
| --- | --- | --- |
| Remember the running commit and tag its image `previous` | VM | |
| Reset the clone to `origin/main` | VM | Stops; nothing changed |
| `docker compose up -d --build` | VM | Prints the API's last log lines, rolls back |
| Wait up to a minute for the API's own `/health` | VM | Prints the logs, rolls back |
| Wait up to two minutes for `https://<DOMAIN>/health`, through DNS, Caddy and its certificate | Your machine | Rolls back, then checks the public URL again |

A rollback resets the clone to the previous commit, starts the previous image, and reports `ROLLED_BACK` only
once that answers `/health`; otherwise it reports `ROLLBACK_FAILED`. A first deploy has nothing to roll back to
(`ROLLBACK_IMPOSSIBLE`). `DOMAIN` is read from the VM's `.env`; `THESEUS_DOMAIN` overrides it.

The API will not start without FalkorDB: startup connects and fails if it cannot, whether it is launched by
`theseus serve` or by uvicorn in the image. `/health` returns 503 with `"falkordb": "unreachable"` if FalkorDB
Cloud stops answering later. So a failed deploy can also mean the database is down: check
`docker compose -f deploy/docker-compose.yml logs api`.

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
4. **Give the VM the key and the settings.**
   - Copy the key to `~/theseus/secrets/theseus.private-key.pem` on the VM. The container runs as user
     10001, so run `sudo chown 10001 ~/theseus/secrets/theseus.private-key.pem` and
     `sudo chmod 400 ~/theseus/secrets/theseus.private-key.pem`.
   - Add the three lines of `github-app.env` to `~/theseus/.env`, plus `THESEUS_REPOS=<owner>/theseus` and
     `THESEUS_TOKEN=<a long random string>` (`openssl rand -hex 32`).
   - Restart: `docker compose -f deploy/docker-compose.yml up -d`.
5. **Tell the Action where to send reviews.** In the repo: `gh variable set THESEUS_URL --body https://<DOMAIN>`
   and `gh secret set THESEUS_TOKEN` (paste the same token).
6. **Try it.** Open a PR from `demo/trial-1` that edits a comment in `demo-infra/terraform/people.tf`, with
   label `demo`. Theseus's comment and the `Theseus` check should appear. Comment `/theseus review` and click
   **Re-run** on the check: each starts a new run of the Theseus workflow.
7. **Block merges on it.** Settings, **Rules**, **Rulesets**, **New branch ruleset**: target `main`, turn on
   **Require status checks to pass**, add `Theseus`, and set its source to the App. Both of you agree first.

## Rotating a secret

Edit `~/theseus/.env` on the VM, then `docker compose -f deploy/docker-compose.yml up -d`. Compose recreates
the containers with the new values; no rebuild is needed. For a key that was exposed, revoke it at its source
first (Crusoe, TypeSafe, FalkorDB Cloud, or the GitHub App), then update `.env`.
