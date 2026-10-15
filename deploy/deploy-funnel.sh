#!/usr/bin/env bash
# Deploy to a host that runs the API from a venv behind Tailscale Funnel (guest-box), and report success only
# once it answers publicly. deploy.sh is the same for a host with Docker Compose and Caddy.
#
#   deploy/deploy-funnel.sh dev@100.104.51.40       or   THESEUS_VM=dev@100.104.51.40 deploy/deploy-funnel.sh
#
# 1. On the host: remember the running commit, reset the deploy-only clone (THESEUS_DIR, default ~/theseus) to
#    origin/<THESEUS_REF> (default main), install it into its venv, restart deploy/run.sh, and wait for the API's
#    own /health. If any of that fails, return to the previous commit.
# 2. From here: wait for https://<DOMAIN>/health, the Funnel address. DOMAIN comes from THESEUS_DOMAIN, or from
#    the host's .env. If it never answers, return to the previous commit on the host.
#
# Exit 0 means the new commit is live publicly; anything else is a failed deploy.
set -euo pipefail

VM="${1:-${THESEUS_VM:-}}"
DIR="${THESEUS_DIR:-theseus}"
REF="${THESEUS_REF:-main}"
TRIES="${THESEUS_TRIES:-30}"
PUBLIC_TRIES="${THESEUS_PUBLIC_TRIES:-24}"
PUBLIC_WAIT="${THESEUS_PUBLIC_WAIT:-5}"
if [[ -z "$VM" ]]; then
  echo "usage: deploy/deploy-funnel.sh user@host (or set THESEUS_VM)" >&2
  exit 2
fi
# The ref reaches `git fetch` on the host, and the Deploy workflow takes it from a person's input: allow only a
# branch, tag or commit name, never something git would read as an option.
if [[ ! "$REF" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ || "$REF" == *..* ]]; then
  echo "not a branch, tag or commit name: $REF" >&2
  exit 2
fi

# Runs on the host: bash -s -- <deploy|rollback> <dir> <ref or commit> <tries>.
read -r -d '' REMOTE <<'SCRIPT' || true
set -uo pipefail
mode="$1"; dir="$2"; target="$3"; tries="$4"
cd "$dir" || { echo "no $dir on the host"; exit 1; }
[[ -f .env ]] || { echo "no .env in $(pwd); copy it there first (chmod 600)"; exit 1; }

healthy() { curl -sf -m 5 http://127.0.0.1:8000/health >/dev/null; }
install_and_restart() {
  .venv/bin/pip install -q . && bash deploy/run.sh restart >/dev/null || return 1
  for _ in $(seq 1 "$tries"); do healthy && return 0; sleep 2; done
  return 1
}

if [[ "$mode" == rollback ]]; then
  if [[ -z "$target" ]]; then echo "ROLLBACK_IMPOSSIBLE: no previous commit"; exit 1; fi
  git reset --quiet --hard "$target" && install_and_restart \
    && { echo "ROLLED_BACK: $target is running and healthy"; exit 0; }
  echo "ROLLBACK_FAILED: $target is not healthy"; tail -20 ~/theseus-logs/api.log; exit 1
fi

prev="$(git rev-parse HEAD)"
echo "PREVIOUS=$prev"
git fetch --quiet origin "$target" && git reset --quiet --hard FETCH_HEAD \
  || { echo "could not update to origin/$target; nothing changed"; exit 1; }
echo "DEPLOYING=$(git rev-parse --short HEAD)"
if install_and_restart; then echo "HEALTHY"; exit 0; fi
echo "not healthy; the API's last log lines:"; tail -20 ~/theseus-logs/api.log
git reset --quiet --hard "$prev" && install_and_restart && echo "ROLLED_BACK: $prev" || echo "ROLLBACK_FAILED"
exit 1
SCRIPT

out="$(ssh "$VM" bash -s -- deploy "$DIR" "$REF" "$TRIES" <<< "$REMOTE")" || { echo "$out"; exit 1; }
echo "$out"
prev="$(sed -n 's/^PREVIOUS=//p' <<< "$out")"

domain="${THESEUS_DOMAIN:-$(ssh "$VM" "sed -n 's/^DOMAIN=//p' $DIR/.env" | tr -d '\r')}"
if [[ -z "$domain" ]]; then
  echo "no DOMAIN in the host's .env and no THESEUS_DOMAIN; cannot check the public URL" >&2
  exit 1
fi
for _ in $(seq 1 "$PUBLIC_TRIES"); do
  if curl -sf -m 10 "https://$domain/health" >/dev/null; then
    echo "LIVE: https://$domain/health"
    exit 0
  fi
  sleep "$PUBLIC_WAIT"
done
echo "https://$domain/health never answered; returning to $prev" >&2
ssh "$VM" bash -s -- rollback "$DIR" "$prev" "$TRIES" <<< "$REMOTE" || true
exit 1
