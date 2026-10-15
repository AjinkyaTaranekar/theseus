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
deploy/deploy.sh ubuntu@<vm-ip>
curl https://<DOMAIN>/health    # {"status": "ok", "falkordb": "4.22.0", "version": ...}
```

`deploy.sh` tags the running image as `previous`, pulls `main`, runs `docker compose up -d --build`, and waits
up to a minute for `/health`. If the check fails, it prints the API's last log lines and starts the previous
image again.

`/health` returns 503 with `"falkordb": "unreachable"` when FalkorDB Cloud cannot be reached, so a failed deploy
can also mean the database is down: check `docker compose -f deploy/docker-compose.yml logs api`.

## Rotating a secret

Edit `~/theseus/.env` on the VM, then `docker compose -f deploy/docker-compose.yml up -d`. Compose recreates
the containers with the new values; no rebuild is needed. For a key that was exposed, revoke it at its source
first (Crusoe, TypeSafe, FalkorDB Cloud, or the GitHub App), then update `.env`.
