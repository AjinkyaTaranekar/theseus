#!/usr/bin/env python3
"""Check commit messages against the rules in AGENTS.md ("Commits").

    python tools/check_commit_msg.py .git/COMMIT_EDITMSG      # one message (the commit-msg hook)
    python tools/check_commit_msg.py --range origin/main..HEAD # every commit in a range (CI)

Exit code 1 lists every problem found.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TYPES = ("feat", "fix", "docs", "test", "refactor", "chore")
SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?P<scope>\([^)]*\))?: (?P<summary>.+)$")
SKIP = re.compile(r"^(Merge |Revert \"|fixup! |squash! )")
TRAILER = re.compile(r"^[A-Za-z-]+: ")
NOT_IMPERATIVE_OK = {
    "embed",
    "seed",
    "feed",
    "need",
    "shed",
    "speed",
    "proceed",
    "exceed",
    "succeed",
    "bring",
    "string",
    "ping",
    "ring",
}


def problems(message: str) -> list[str]:
    lines = [ln for ln in message.splitlines() if not ln.startswith("#")]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ["the message is empty"]
    subject = lines[0]
    if SKIP.match(subject):
        return []
    out = []
    m = SUBJECT.match(subject)
    if not m:
        return [f"subject must look like '<type>: <Summary>': {subject!r}"]
    if m["scope"]:
        out.append(
            f"drop the scope {m['scope']}; write '<type>: <Summary>' (task IDs change, commits do not)"
        )
    if m["type"] not in TYPES:
        out.append(f"type {m['type']!r} is not one of {', '.join(TYPES)}")
    summary = m["summary"]
    if len(subject) > 50:
        out.append(f"subject is {len(subject)} characters; the limit is 50")
    if not summary[:1].isupper():
        out.append("capitalize the first word after the colon")
    if summary.endswith("."):
        out.append("do not end the subject with a period")
    first = summary.split()[0].lower()
    if first not in NOT_IMPERATIVE_OK and (first.endswith("ed") or first.endswith("ing")):
        out.append(f"use the imperative mood ('Add', not {summary.split()[0]!r})")
    if len(lines) > 1 and lines[1].strip():
        out.append("leave a blank line between the subject and the body")
    for n, line in enumerate(lines[2:], start=3):
        if len(line) > 72 and "://" not in line and not TRAILER.match(line):
            out.append(f"body line {n} is {len(line)} characters; wrap at 72")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("file", nargs="?", type=Path, help="a commit message file")
    parser.add_argument("--range", help="a git revision range, such as origin/main..HEAD")
    args = parser.parse_args()
    if args.range:
        shas = subprocess.run(
            ["git", "rev-list", args.range], capture_output=True, text=True, check=True
        ).stdout.split()
        messages = {
            sha[:8]: subprocess.run(
                ["git", "log", "-1", "--format=%B", sha],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            ).stdout
            for sha in shas
        }
    elif args.file:
        messages = {"message": args.file.read_text(encoding="utf-8")}
    else:
        parser.error("give a message file or --range")
    failed = False
    for name, message in messages.items():
        for p in problems(message):
            failed = True
            print(f"{name}: {p}", file=sys.stderr)
    if failed:
        print('See AGENTS.md, "Commits", and https://cbea.ms/git-commit/', file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
