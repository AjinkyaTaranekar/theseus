"""Claude Code PreToolUse hook: before a command that commits, pushes or opens a PR, run Theseus's check.

Every other command passes at once: this script reads the tool call and exits without importing Theseus, so
ordinary commands are not slowed. For the rest it hands the same input to `python -m theseus check --hook`,
which answers `deny` or `ask` with the reason, or nothing when the change is clear. A check that cannot run
never stops the command. Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

# The same pattern as theseus/cli.py's SHIPS (a test keeps them equal).
SHIPS = re.compile(r"\b(git\s+(commit|push)|gh\s+pr\s+create)\b")


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw or "{}")
    except ValueError:
        return 0
    command = str((event.get("tool_input") or {}).get("command", ""))
    if event.get("tool_name") != "Bash" or not SHIPS.search(command):
        return 0
    python = os.environ.get("THESEUS_PYTHON") or sys.executable
    try:
        done = subprocess.run(
            [python, "-m", "theseus", "check", "--hook"],
            input=raw,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=event.get("cwd") or None,
            check=False,
        )
    except OSError as e:
        print(f"theseus hook: cannot run {python}: {e}; the command runs unchecked", file=sys.stderr)
        return 0
    sys.stdout.write(done.stdout)
    sys.stderr.write(done.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
