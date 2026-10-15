#!/usr/bin/env bash
# Deploy main to the VM: pull, rebuild, check /health, and roll back to the previous image if it fails.
#
#   deploy/deploy.sh ubuntu@<vm-ip>          or   THESEUS_VM=ubuntu@<vm-ip> deploy/deploy.sh
#
# The VM keeps a clone of this repo at ~/theseus (THESEUS_DIR to change it) and the .env next to it.
# That clone is deploy-only: this script resets it to origin/main.
set -euo pipefail

VM="${1:-${THESEUS_VM:-}}"
DIR="${THESEUS_DIR:-theseus}"
if [[ -z "$VM" ]]; then
  echo "usage: deploy/deploy.sh user@host (or set THESEUS_VM)" >&2
  exit 2
fi

ssh "$VM" bash -s -- "$DIR" <<'REMOTE'
set -euo pipefail
cd "$1"
compose() { docker compose -f deploy/docker-compose.yml "$@"; }
healthy() {
  compose exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)" >/dev/null 2>&1
}

[[ -f .env ]] || { echo "no .env in $(pwd); copy it there first (chmod 600)" >&2; exit 1; }
if docker image inspect theseus-api:latest >/dev/null 2>&1; then
  docker tag theseus-api:latest theseus-api:previous
fi

git fetch --quiet origin main
git reset --quiet --hard origin/main
echo "deploying $(git rev-parse --short HEAD)"
compose up -d --build

for _ in $(seq 1 30); do
  if healthy; then
    echo "healthy: $(git rev-parse --short HEAD) is live"
    exit 0
  fi
  sleep 2
done

echo "health check failed; rolling back" >&2
compose logs --tail 50 api >&2 || true
if docker image inspect theseus-api:previous >/dev/null 2>&1; then
  docker tag theseus-api:previous theseus-api:latest
  compose up -d --no-build
  echo "rolled back to the previous image" >&2
fi
exit 1
REMOTE
