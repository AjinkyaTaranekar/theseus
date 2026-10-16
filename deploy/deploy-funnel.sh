#!/usr/bin/env bash
# Deploy to a host that runs the API from a venv behind Tailscale Funnel (guest-box), and report success only
# once it answers publicly. deploy.sh is the same for a host with Docker Compose and Caddy.
#
#   deploy/deploy-funnel.sh dev@100.104.51.40       or   THESEUS_VM=dev@100.104.51.40 deploy/deploy-funnel.sh
#
# 1. Before anything changes: check the ref, reach the host, and read DOMAIN (THESEUS_DOMAIN, or the host's .env).
#    If any of these fails, stop: nothing on the host has changed.
# 2. On the host: remember the running commit, reset the deploy-only clone (THESEUS_DIR, default ~/theseus) to
#    origin/<THESEUS_REF> (default main), install it into its venv, restart deploy/run.sh, and wait for the API's
#    own /health. If any of that fails, the host returns to the previous commit itself.
# 3. From here: wait for https://<DOMAIN>/health, the Funnel address. From the restart on, any failure, this one
#    or anything unexpected, returns the host to the previous commit. A failure only counts as handled when the
#    host's own answer says so: if SSH drops before the host reports, the outcome is unknown, so this script
#    rolls back over a new connection and believes only the host's ROLLED_BACK line.
#
# Exit 0: the new commit is live publicly.
# Exit 1: the deploy failed, and the host confirmed it runs its previous commit (or nothing changed).
# Exit 3: the host's state is not confirmed (its rollback failed, or no answer came back). A person must check.
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

# Runs on the host: bash -s -- <domain|deploy|rollback> <dir> <ref or commit> <tries>.
read -r -d '' REMOTE <<'SCRIPT' || true
set -uo pipefail
mode="$1"; dir="$2"; target="$3"; tries="$4"
cd "$dir" || { echo "no $dir on the host"; exit 1; }
[[ -f .env ]] || { echo "no .env in $(pwd); copy it there first (chmod 600)"; exit 1; }
if [[ "$mode" == domain ]]; then sed -n 's/^DOMAIN=//p' .env | tr -d '\r' | tail -1; exit 0; fi

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

# ssh joins its arguments into one command for the remote shell, so each is quoted for it: an empty one (no
# previous commit) must stay an argument, not vanish and shift the rest.
remote() { ssh "$VM" "bash -s -- $(printf '%q ' "$@")" <<< "$REMOTE"; }

# 1. The public name to check afterwards, read before anything changes: without it a deploy can never be
#    called live, so it stops here rather than after the restart.
domain="${THESEUS_DOMAIN:-}"
if [[ -z "$domain" ]] && ! domain="$(remote domain "$DIR" "" "$TRIES")"; then
  echo "could not read DOMAIN from the host's .env over SSH; nothing changed" >&2
  exit 1
fi
if [[ -z "$domain" ]]; then
  echo "no DOMAIN in the host's .env and no THESEUS_DOMAIN; nothing changed" >&2
  exit 1
fi

# 2 and 3. From the restart on, a failed exit returns the host to the previous commit, unless the host already
# did so itself (the deploy step failed) or the new commit answered publicly.
prev=""
settled=1
uncertain() {
  echo "UNCERTAIN: $1; check the host by hand, it may still run the new commit" >&2
  exit 3
}
finish() {
  local status=$? back
  if [[ $status -ne 0 && $settled -eq 0 ]]; then
    settled=1
    echo "the deploy failed after the restart; returning to ${prev:-the previous commit}" >&2
    back="$(remote rollback "$DIR" "$prev" "$TRIES")" || true
    echo "$back"
    grep -q '^ROLLED_BACK: ' <<< "$back" || uncertain "the rollback was not confirmed"
  fi
  exit "$status"
}
trap finish EXIT

deployed=0
out="$(remote deploy "$DIR" "$REF" "$TRIES")" || deployed=$?
echo "$out"
prev="$(sed -n 's/^PREVIOUS=//p' <<< "$out")"
if [[ $deployed -ne 0 ]]; then
  # Believe only what the host said. Its PREVIOUS line comes before it changes anything.
  if grep -q '^ROLLED_BACK: ' <<< "$out" || grep -q 'nothing changed' <<< "$out"; then exit 1; fi
  if grep -q '^ROLLBACK_FAILED' <<< "$out"; then uncertain "the host could not return to $prev"; fi
  if [[ -z "$prev" ]]; then
    [[ $deployed -eq 255 ]] && uncertain "SSH failed before the host reported its commit"
    echo "the host refused the deploy; nothing changed" >&2
    exit 1
  fi
  if ! grep -q '^HEALTHY$' <<< "$out"; then
    # The host started the deploy but its answer was lost: roll back over a new connection.
    echo "no answer from the host after it started the deploy" >&2
    settled=0
    exit 1
  fi
  echo "the host reported HEALTHY before the connection dropped; checking publicly" >&2
fi
settled=0
for _ in $(seq 1 "$PUBLIC_TRIES"); do
  if curl -sf -m 10 "https://$domain/health" >/dev/null; then
    settled=1
    echo "LIVE: https://$domain/health"
    exit 0
  fi
  sleep "$PUBLIC_WAIT"
done
echo "https://$domain/health never answered" >&2
exit 1
