"""Things that must never be committed, and a deploy that survives one that was: a `.venv` symlink to a
teammate's own folder once reached main, and checking it out replaced the host's virtualenv. The repo goes
public, so a person's email address and the address of our host stay out of every tracked file too."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")
# `git@github.com` is the SSH clone user, a noreply address names no one, and these domains are reserved for
# examples and tests.
ALLOWED_EMAIL = re.compile(
    r"^git@github\.com$|^noreply@|@users\.noreply\.github\.com$|@example\.(?:com|org|net)$|\.(?:test|invalid)$"
)
# Tailscale gives each machine an address from 100.64.x.x to 100.127.x.x; one of them is our host's.
TAILNET_ADDRESS = re.compile(r"(?<![\d.])100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?![\d.])")

needs_git_checkout = pytest.mark.skipif(
    shutil.which("git") is None or not Path(".git").exists(), reason="needs a git checkout"
)


def tracked_text_lines() -> Iterator[tuple[str, int, str]]:
    """Each line of every tracked text file, as (path, line number, text); binary files are skipped."""
    listing = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True)
    for name in sorted(listing.stdout.decode("utf-8").split("\0")):
        path = Path(name)
        if not name or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), start=1):
            yield name, number, line


@pytest.mark.skipif(shutil.which("git") is None or not Path(".git").exists(), reason="needs a git checkout")
def test_no_virtualenv_is_tracked() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--", ".venv", "venv", "*/.venv"], capture_output=True, text=True, check=True
    )
    assert tracked.stdout == ""


def test_any_kind_of_venv_is_ignored() -> None:
    """`.venv/` matches only a directory; `.venv` also matches a file or a symlink."""
    lines = Path(".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".venv" in lines


def test_the_host_deploy_rebuilds_a_missing_venv_before_installing() -> None:
    script = Path("deploy/deploy-funnel.sh").read_text(encoding="utf-8")
    rebuild = script.index("python3.12 -m venv .venv")
    assert rebuild < script.index(".venv/bin/pip install -q .")


@needs_git_checkout
def test_no_personal_email_address_is_tracked() -> None:
    """Names the file and line only, so a failing run does not copy the address into a log."""
    found = [
        f"{name}:{number}"
        for name, number, line in tracked_text_lines()
        for match in EMAIL.finditer(line)
        if not ALLOWED_EMAIL.search(match.group())
    ]
    hint = "remove them, or add a domain that names no one to ALLOWED_EMAIL"
    assert found == [], f"email addresses in tracked files; {hint}: {found}"


@needs_git_checkout
def test_no_tailnet_address_is_tracked() -> None:
    """Write `<host-ip>` where a runbook needs the host's address; the public name is the one to publish."""
    found = [
        f"{name}:{number}" for name, number, line in tracked_text_lines() if TAILNET_ADDRESS.search(line)
    ]
    assert found == [], f"Tailscale addresses in tracked files; use a placeholder: {found}"
