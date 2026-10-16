#!/usr/bin/env bash
# Keeps the API running on 127.0.0.1:8000 on a host without systemd or Docker, such as guest-box, where
# Tailscale Funnel publishes it (deploy/README.md). Restarts the API whenever it exits, after a short pause.
#
#   deploy/run.sh start | stop | restart | status
#
# THESEUS_DIR is the deploy clone (default ~/theseus), with its venv in .venv and its .env beside it.
set -uo pipefail

DIR="${THESEUS_DIR:-$HOME/theseus}"
LOGS="$HOME/theseus-logs"
LOG="$LOGS/api.log"
PIDFILE="$LOGS/runner.pid"
mkdir -p "$LOGS"

running() { [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

loop() {
  cd "$DIR" || exit 1
  while true; do
    echo "$(date -u +%FT%TZ) starting theseus serve at $(git rev-parse --short HEAD)" >> "$LOG"
    .venv/bin/python -m theseus serve >> "$LOG" 2>&1
    status=$?  # before the $(date) below, which would reset $?
    echo "$(date -u +%FT%TZ) theseus serve exited with $status; restarting in 5 s" >> "$LOG"
    sleep 5
  done
}

start() {
  if running; then
    echo "already running (runner $(cat "$PIDFILE"))"
    return 0
  fi
  setsid bash "$0" loop < /dev/null > /dev/null 2>&1 &
  echo $! > "$PIDFILE"
  echo "started runner $!"
}

stop() {
  if running; then
    # setsid made the runner a process group leader, so this stops it and the API together.
    kill -- -"$(cat "$PIDFILE")" 2>/dev/null || kill "$(cat "$PIDFILE")"
    echo "stopped"
  else
    echo "not running"
  fi
  rm -f "$PIDFILE"
}

case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  loop) loop ;;
  status)
    if running; then echo "running (runner $(cat "$PIDFILE"))"; else echo "not running"; fi
    curl -s -m 5 http://127.0.0.1:8000/health; echo
    ;;
  *) echo "usage: deploy/run.sh start|stop|restart|status" >&2; exit 2 ;;
esac
