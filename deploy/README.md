# Deploying Theseus

The API runs on **guest-box**, a container on an Oracle ARM host that is reachable only through our Tailscale
network (tailnet). Tailscale Funnel publishes it at **https://guest-box.tail27b7c5.ts.net**, with Tailscale's
certificate, so there is no domain to buy, no Caddy and no open port. FalkorDB is on FalkorDB Cloud. guest-box
has no Docker and no systemd, so the API runs from a venv under `deploy/run.sh`, which restarts it if it exits.

Deploy by hand with `deploy/deploy-funnel.sh`, or from GitHub with the **Deploy** workflow (Actions, Deploy,
Run workflow). A host with Docker and public ports 80 and 443 can run the Compose stack instead; see the end of
this file.

## The host

| Item | Value |
| --- | --- |
| Host | `guest-box`: Ubuntu 24.04 in a container on an Oracle ARM host; 4 cores, 22 GB, 50 GB disk; Python 3.12 |
| Tailnet | `tail27b7c5.ts.net`, owned by `ajinkyataranekar26@gmail.com` |
| SSH | `ssh dev@100.104.51.40` over Tailscale SSH, from a device on the tailnet; no key needed |
| Public URL (`DOMAIN`) | `https://guest-box.tail27b7c5.ts.net`, through Tailscale Funnel |
| API | `127.0.0.1:8000` on the host, under `deploy/run.sh` |
| Deploy clone | `~/theseus` on the host, pulled with a read-only deploy key ("guest-box (read-only deploy)") |
| Secrets | `~/theseus/.env`, `chmod 600`; the App's key in `~/theseus/secrets/` |
| Logs | `~/theseus-logs/api.log` |

## Setting up guest-box from scratch

Do these once, in order. Steps 1 to 4 need a person: they sign in to Tailscale or type a password.

1. **Join the tailnet.** Install Tailscale and sign in with an account in the tailnet above.
   - Windows: the Tailscale app, or in a terminal
     `"C:\Program Files\Tailscale\tailscale.exe" login --login-server=https://controlplane.tailscale.com`
     and open the link it prints. A machine that was set up for another tailnet (a university VPN, say) keeps
     that profile; `tailscale switch --list` shows both, and `tailscale switch <ID>` moves between them.
   - Check it worked: `tailscale status` lists `guest-box` at `100.104.51.40`. If the list is empty, you are
     signed in to a different tailnet: compare the tailnet name in `tailscale switch --list`.
2. **SSH in.** `ssh dev@100.104.51.40`. Tailscale SSH answers (the banner says `SSH-2.0-Tailscale`) and
   decides by your tailnet identity and the tailnet policy, so no key is needed. If the policy's rule is a
   `check`, the first login opens a browser to confirm.
3. **Let `dev` manage Tailscale on the host.** Once, with `dev`'s sudo password:
   `ssh -t dev@100.104.51.40 "sudo tailscale set --operator=dev"`. Without it, `tailscale funnel` fails with
   "Access denied: serve config denied". Someone with access to the Oracle host can do the same with
   `docker exec <container> tailscale set --operator=dev`.
4. **Allow Funnel in the tailnet.** In the Tailscale admin console, under DNS, turn on MagicDNS and HTTPS
   certificates. The first `tailscale funnel` on the host prints a link to enable Funnel for that machine;
   open it and approve. (The policy file then holds a `nodeAttrs` entry with `"attr": ["funnel"]`.)
5. **Clone the repo.** It is private, so the host has its own key, added to the repo as a read-only deploy key:
   ```bash
   ssh-keygen -t ed25519 -N "" -C "guest-box deploy" -f ~/.ssh/id_ed25519   # on the host
   gh repo deploy-key add <the .pub file> --title "guest-box (read-only deploy)"   # where gh is signed in
   ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts                    # on the host
   git clone git@github.com:<owner>/theseus.git ~/theseus
   ```
6. **Install.** `python3 -m venv ~/theseus/.venv && ~/theseus/.venv/bin/pip install ~/theseus`.
7. **Secrets.** Copy your `.env` without printing it, then lock it down and set the public name:
   ```bash
   ssh dev@100.104.51.40 'umask 077; cat > ~/theseus/.env' < .env
   ssh dev@100.104.51.40 'chmod 600 ~/theseus/.env; sed -i "s/^DOMAIN=.*/DOMAIN=guest-box.tail27b7c5.ts.net/" ~/theseus/.env'
   ```
   If FalkorDB Cloud has an IP allowlist, add the host's public address (`curl ifconfig.me` on the host).
8. **Start the API.** `bash ~/theseus/deploy/run.sh start`, then `bash ~/theseus/deploy/run.sh status`: it
   should print `{"status":"ok","falkordb":"4.22.0",...}`. The API will not start without FalkorDB.
9. **Publish it.** `tailscale funnel --bg 8000`; `tailscale funnel status` shows
   `https://guest-box.tail27b7c5.ts.net (Funnel on)`. The setting survives restarts.
10. **Check it from outside the tailnet.** A device on the tailnet reaches the name through MagicDNS, not
    Funnel, so ask public DNS for the address and connect to that. A new name can take up to about 10
    minutes to appear in public DNS.
    ```bash
    IP=$(curl -s "https://dns.google/resolve?name=guest-box.tail27b7c5.ts.net&type=A" | python -c "import json,sys; print(json.load(sys.stdin)['Answer'][0]['data'])")
    curl --resolve guest-box.tail27b7c5.ts.net:443:$IP https://guest-box.tail27b7c5.ts.net/health
    ```
11. **Survive a container restart.** The runner does not: start it again, or have whoever owns the container
    add `su dev -c 'bash ~/theseus/deploy/run.sh start'` to its start script (`/usr/local/bin/start.sh`).

`deploy/run.sh start | stop | restart | status` manages the API; it writes to `~/theseus-logs/api.log`.

## Deploy by hand

From a device on the tailnet:

```bash
deploy/deploy-funnel.sh dev@100.104.51.40                              # main
THESEUS_REF=f7-action-app deploy/deploy-funnel.sh dev@100.104.51.40    # a branch, before it merges
```

It records the running commit, resets the clone to `origin/<THESEUS_REF>` (default `main`), installs it into the
venv, restarts the API, and waits for the API's own `/health`, then for `https://<DOMAIN>/health`. If either
never answers, it returns to the previous commit and says whether that recovered (`ROLLED_BACK`) or not
(`ROLLBACK_FAILED`). It accepts only a branch, tag or commit name as the ref.

## Deploying from GitHub

`.github/workflows/deploy.yml` runs the same script from GitHub, only when a person starts it: **Actions**,
**Deploy**, **Run workflow**, choose the ref (default `main`). From a terminal:
`gh workflow run deploy.yml -f ref=main`, then `gh run watch`. The workflow must be on `main` before GitHub
shows the button.

**What it does.** The runner joins the tailnet as an ephemeral node tagged `tag:ci` (Tailscale's GitHub
Action, with an OAuth client), pins guest-box's host key, and runs `deploy/deploy-funnel.sh` over Tailscale SSH.
Only one deploy runs at a time; a second waits. The ephemeral node leaves the tailnet when the job ends.

**Why it is safe to leave set up.** No SSH key is stored in GitHub: the tailnet policy is what lets `tag:ci`
log in, and only as `dev`, only to `tag:server`. The OAuth secret is in the `production` environment, which only
workflows on `main` can use, so a workflow edited on a PR branch never sees it. Only people with write access
can start a workflow.

**One-time setup.** The GitHub side is done: the `production` environment (branch `main` only) holds the
variables `DEPLOY_HOST` (`dev@100.104.51.40`), `DEPLOY_TAILNET_IP` and `DEPLOY_KNOWN_HOSTS` (guest-box's
Tailscale SSH host key, from `ssh-keyscan -t ed25519 100.104.51.40`). The tailnet's admin does the rest:

1. **Tag guest-box.** Admin console, Machines, guest-box, **Edit ACL tags**: `tag:server`. Tailscale lets a
   tagged device such as the runner SSH only into tagged devices, so the host needs a tag.
2. **Update the tailnet policy** (Access controls). Merge this into the existing file; keep its other rules:
   ```jsonc
   "tagOwners": {
     "tag:ci":     ["autogroup:admin"],
     "tag:server": ["autogroup:admin"]
   },
   "nodeAttrs": [
     // guest-box is now tagged, so it is no longer covered by an autogroup:member Funnel entry
     {"target": ["autogroup:member", "tag:server"], "attr": ["funnel"]}
   ],
   "ssh": [
     // people on the tailnet, into guest-box (a tagged device is no longer anyone's autogroup:self)
     {"action": "accept", "src": ["autogroup:member"], "dst": ["tag:server"], "users": ["dev"]},
     // the Deploy workflow
     {"action": "accept", "src": ["tag:ci"], "dst": ["tag:server"], "users": ["dev"]}
   ]
   ```
   If the policy restricts network access (`acls` or `grants` other than allow-all), also let `tag:ci` reach
   `tag:server` on port 22.
3. **Create an OAuth client.** Admin console, Settings, OAuth clients, **Generate OAuth client**: scope
   **Auth Keys** (write), tag `tag:ci`. Store both values in the environment, pasting each when asked:
   ```bash
   gh secret set TS_OAUTH_CLIENT_ID --env production
   gh secret set TS_OAUTH_SECRET --env production
   ```
4. **Try it:** `gh workflow run deploy.yml -f ref=main`. The log should end with
   `LIVE: https://guest-box.tail27b7c5.ts.net/health`.

If guest-box's host key ever changes (a new container), refresh it:
`ssh-keyscan -t ed25519 100.104.51.40 | grep -v '^#' | gh variable set DEPLOY_KNOWN_HOSTS --env production`.

## When something goes wrong

| Symptom | Cause | Fix |
| --- | --- | --- |
| `tailscale status` shows no `guest-box` | Signed in to another tailnet | `tailscale switch --list`, then sign in to the one above |
| `ssh` times out | Not on the tailnet, or the policy does not allow you | Check `tailscale status`; check the `ssh` rules |
| `serve config denied` | `dev` is not Tailscale's operator | Step 3 |
| `Funnel is not enabled on your tailnet` | Funnel not allowed for this machine | Open the link it prints (step 4); after tagging, check `nodeAttrs` |
| Public DNS has no address yet | A new Funnel name takes a few minutes | Wait up to 10 minutes; step 10 |
| `/health` is 503, `"falkordb": "unreachable"` | FalkorDB Cloud is down or refuses the host | Read `~/theseus-logs/api.log`; check the allowlist |
| The Deploy workflow fails at "Join the tailnet" | OAuth client missing, or its tag is not `tag:ci` | Setup step 3 |
| It fails at "Deploy" with permission denied | The `ssh` rule for `tag:ci` is missing, or guest-box is untagged | Setup steps 1 and 2 |
| The API is down after the container restarted | The runner does not survive it | `bash ~/theseus/deploy/run.sh start`; step 11 |

## The GitHub App

The App posts the comment and the `Theseus` check, and re-runs a review on `/theseus review` or Re-run
(`docs/spec/07-github-and-deploy.md`, "The GitHub App"). Its settings live in
[`github-app-manifest.json`](github-app-manifest.json). 
**Where it stands:** registered, installed on this repo only (installation 171853568), and its key and settings
are on guest-box. GitHub's ping to `https://guest-box.tail27b7c5.ts.net/webhooks/github` returns 204, so the
signature check works. The repo has the variable `THESEUS_URL` and the secret `THESEUS_TOKEN`. To register it
again from scratch:

Register it once the API answers on `https://<DOMAIN>`:

1. **Register.** Run `python tools/github_app.py form --domain <DOMAIN>`, open the page it writes, and click
   the button. GitHub shows the settings from the manifest. GitHub reserves the name `Theseus`, so ours is **Theseus Graph Review** (`theseus-graph-review`, App ID 5336067, installed on this repo only); if that is taken too, pick another;
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

## Sharing the App's key

The private key lets anyone holding it act as the App on this repo: push commits, edit PRs, run workflows. So:

- **Keep it in `secrets/`, never in git.** `secrets/theseus.private-key.pem` with
  `GITHUB_APP_PRIVATE_KEY_PATH=secrets/theseus.private-key.pem` in `.env`. `.gitignore` covers `secrets/`; on a
  branch made before that line existed, add `secrets/` to `.git/info/exclude` too. The repo goes public, and a
  key once committed stays in its history.
- **Give each person their own key.** On the App's settings page
  (`https://github.com/settings/apps/theseus-graph-review`), **Generate a private key** downloads a new one; an
  App can have several at once. Deleting one there revokes only that person's, and guest-box keeps working.
  Only the App's owner can do this.
- **If you must pass one on,** use a password manager's shared vault or an end-to-end encrypted message, never
  an issue, a PR, a chat channel or email.
- **Most of the time no one needs it locally.** Tests mock GitHub, and guest-box has its own copy. A laptop needs
  it only to call GitHub as the App, and then also `GITHUB_WEBHOOK_SECRET` and `THESEUS_TOKEN`, shared the same
  way.

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
