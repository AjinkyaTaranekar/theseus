#!/usr/bin/env bash
# Deploy main to the VM, and report success only once it answers publicly.
#
#   deploy/deploy.sh ubuntu@<vm-ip>          or   THESEUS_VM=ubuntu@<vm-ip> deploy/deploy.sh
#
# 1. On the VM: remember the running commit and image, reset the deploy-only clone at ~/theseus (THESEUS_DIR)
#    to origin/main, rebuild, and wait for the API's own /health. If compose or that check fails, roll back.
# 2. From here: wait for https://<DOMAIN>/health, through DNS, Caddy and its certificate. DOMAIN comes from
#    THESEUS_DOMAIN, or from the VM's .env. If it never answers, roll back on the VM.
#
# A rollback restores the previous commit and image, and says it recovered only after they answer /health.
# Exit 0 means the new commit is live publicly; anything else is a failed deploy.
set -euo pipefail

VM="${1:-${THESEUS_VM:-}}"
DIR="${THESEUS_DIR:-theseus}"
TRIES="${THESEUS_TRIES:-30}"
WAIT="${THESEUS_WAIT:-2}"
PUBLIC_TRIES="${THESEUS_PUBLIC_TRIES:-24}"
PUBLIC_WAIT="${THESEUS_PUBLIC_WAIT:-5}"
if [[ -z "$VM" ]]; then
  echo "usage: deploy/deploy.sh user@host (or set THESEUS_VM)" >&2
  exit 2
fi

# Runs on the VM: bash -s -- <deploy|rollback> <dir> <previous commit> <tries> <wait>.
# No `set -e` here: every failure is handled where it happens, so a failed compose still reaches the rollback.
read -r -d '' REMOTE <<'SCRIPT' || true
set -uo pipefail
mode="$1"; dir="$2"; prev="$3"; tries="$4"; wait="$5"
cd "$dir" || { echo "no $dir on the VM"; exit 1; }

compose() { docker compose -f deploy/docker-compose.yml "$@"; }
healthy() {
  compose exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)" >/dev/null 2>&1
}
wait_healthy() {
  for _ in $(seq 1 "$tries"); do
    healthy && return 0
    sleep "$wait"
  done
  return 1
}
rollback() {
  local to="$1"
  if [[ -z "$to" ]] || ! docker image inspect theseus-api:previous >/dev/null 2>&1; then
    echo "ROLLBACK_IMPOSSIBLE: there is no previous deploy to return to"
    return 1
  fi
  if ! { git reset --quiet --hard "$to" && docker tag theseus-api:previous theseus-api:latest \
      && compose up -d --no-build; }; then
    echo "ROLLBACK_FAILED: could not restart $to"
    return 1
  fi
  if wait_healthy; then
    echo "ROLLED_BACK: $to is running and healthy"
    return 0
  fi
  echo "ROLLBACK_FAILED: $to restarted but is not healthy"
  return 1
}

case "$mode" in
  deploy)
    [[ -f .env ]] || { echo "no .env in $(pwd); copy it there first (chmod 600)"; exit 1; }
    prev=""
    if docker image inspect theseus-api:latest >/dev/null 2>&1; then
      prev="$(git rev-parse HEAD)"
      docker tag theseus-api:latest theseus-api:previous
    fi
    echo "PREVIOUS=$prev"
    if ! { git fetch --quiet origin main && git reset --quiet --hard origin/main; }; then
      echo "could not update to origin/main; nothing changed"
      exit 1
    fi
    echo "DEPLOYING=$(git rev-parse --short HEAD)"
    if ! compose up -d --build; then
      echo "compose up failed"
      compose logs --tail 50 api || true
      rollback "$prev"
      exit 1
    fi
    if ! wait_healthy; then
      echo "the API did not become healthy"
      compose logs --tail 50 api || true
      rollback "$prev"
      exit 1
    fi
    echo "DOMAIN=$(sed -n 's/^DOMAIN=//p' .env | tail -n 1)"
    echo "HEALTHY_ON_VM"
    ;;
  rollback)
    rollback "$prev"
    exit $?
    ;;
  *)
    echo "unknown mode $mode"
    exit 2
    ;;
esac
SCRIPT

remote() { ssh "$VM" bash -s -- "$@" <<<"$REMOTE"; }
field() { sed -n "s/^$1=//p" <<<"$2" | tail -n 1; }

public_ok() {
  for _ in $(seq 1 "$PUBLIC_TRIES"); do
    curl -fsS --max-time 10 "https://$1/health" >/dev/null 2>&1 && return 0
    sleep "$PUBLIC_WAIT"
  done
  return 1
}

set +e
out="$(remote deploy "$DIR" "" "$TRIES" "$WAIT" 2>&1)"
status=$?
set -e
printf '%s\n' "$out"
if [[ $status -ne 0 ]]; then
  echo "deploy failed on the VM; see above" >&2
  exit 1
fi

prev="$(field PREVIOUS "$out")"
domain="${THESEUS_DOMAIN:-$(field DOMAIN "$out")}"
if [[ -n "$domain" ]] && public_ok "$domain"; then
  echo "LIVE: https://$domain/health answers"
  exit 0
fi

if [[ -z "$domain" ]]; then
  echo "no DOMAIN in the VM's .env or THESEUS_DOMAIN, so the public endpoint cannot be checked" >&2
else
  echo "https://$domain/health did not answer: check DNS, the firewall, and Caddy's logs" >&2
fi
echo "rolling back on the VM" >&2
if remote rollback "$DIR" "$prev" "$TRIES" "$WAIT"; then
  if [[ -n "$domain" ]] && public_ok "$domain"; then
    echo "rolled back; https://$domain/health answers again" >&2
  else
    echo "rolled back on the VM, but the public endpoint still does not answer" >&2
  fi
fi
exit 1
