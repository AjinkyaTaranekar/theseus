#!/usr/bin/env python3
"""Claude Code PreToolUse hook: block agent writes to files only humans may change.

Wired in .claude/settings.json for Edit, Write, MultiEdit and NotebookEdit. Exit code 2 blocks the call and
shows the message to the agent. Shell commands are not covered; AGENTS.md and CODEOWNERS cover those.
"""
from __future__ import annotations

import json
import os
import sys
from fnmatch import fnmatch
from pathlib import Path

PROTECTED = {
    "fixtures/*/expected.json": "Humans write every expected.json (AGENTS.md, Never). Report the difference instead.",
    "bench/cases/*/expected.json": "Humans write every expected.json (AGENTS.md, Never). Report the difference instead.",
    ".env": "Secrets live in .env and are never written by an agent. Use .env.example for variable names.",
}


def main() -> None:
    event = json.load(sys.stdin)
    tool_input = event.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target:
        return
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or ".").resolve()
    try:
        rel = Path(target).resolve().relative_to(root).as_posix()
    except ValueError:
        return  # outside the repo: not ours to judge
    for pattern, reason in PROTECTED.items():
        if fnmatch(rel, pattern):
            print(f"Blocked: {rel}. {reason}", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
