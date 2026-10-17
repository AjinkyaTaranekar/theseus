#!/bin/sh
# Runs a Python script with whichever interpreter this machine has:  sh tools/py.sh <script> [args...]
# The hooks in .githooks/ and .claude/settings.json cannot assume a bare `python`: a stock macOS has only
# `python3`. Order: $THESEUS_PYTHON, this repo's .venv, python3, python, then the Windows launcher `py -3`.
# A candidate counts only if it runs; the Windows Store's `python3` is on PATH but only prints an install hint.
# With none found it exits 2, which Claude Code reads as "block", so the guard hook never fails open.
# Shell builtins only, so it needs nothing on PATH but the interpreter.
case $0 in
*/*) here=${0%/*} ;;
*) here=. ;;
esac
root=$(cd "$here/.." && pwd)

for py in "${THESEUS_PYTHON:-}" "$root/.venv/bin/python" "$root/.venv/Scripts/python.exe" python3 python; do
    if [ -n "$py" ] && "$py" -c 'import sys' >/dev/null 2>&1; then
        exec "$py" "$@"
    fi
done
if py -3 -c 'import sys' >/dev/null 2>&1; then
    exec py -3 "$@"
fi
echo "No working Python found. Install Python 3 or set THESEUS_PYTHON to an interpreter (see tools/py.sh)." >&2
exit 2
