"""Things that must never be committed, and a deploy that survives one that was: a `.venv` symlink to a
teammate's own folder once reached main, and checking it out replaced the host's virtualenv."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


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
