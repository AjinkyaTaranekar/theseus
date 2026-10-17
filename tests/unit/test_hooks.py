"""The commit-msg hook and the Claude Code guard hook start on a machine whose only interpreter is `python3`.

A stock macOS has no `python` on PATH. A hook that says `python` then exits 127: the commit-msg hook fails
loudly, but the guard hook fails open, because Claude Code blocks a write only on exit code 2. Each test runs
the real hook files from a throwaway copy, with a PATH that holds only stand-ins for `sh`, `git` and the
interpreters the test names.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SH = shutil.which("sh")
GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(
    SH is None or GIT is None or sys.platform == "win32",
    reason="needs a POSIX sh and git; the Windows run is a manual check (tools/py.sh)",
)

HOOKS = json.loads((REPO / ".claude/settings.json").read_text(encoding="utf-8"))["hooks"]
GUARD_COMMAND = HOOKS["PreToolUse"][0]["hooks"][0]["command"]
COPIED = (".githooks/commit-msg", "tools/py.sh", "tools/agent_guard.py", "tools/check_commit_msg.py")


def stand_in(path: Path, target: str, *, note: str = "", skip_first_arg: bool = False) -> Path:
    """Write an executable at `path` that runs `target`, first appending `note` to $MARKER if given."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#!/bin/sh"]
    if note:
        lines.append(f'echo {note} >> "$MARKER"')
    if skip_first_arg:
        lines.append('[ "$1" = -3 ] || exit 9')
        lines.append("shift")
    lines.append(f'exec {shlex.quote(target)} "$@"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return path


@dataclass
class Machine:
    """A copy of the hooks with a PATH of our choosing."""

    root: Path
    bin: Path
    marker: Path

    def add(self, name: str, *, note: str = "", skip_first_arg: bool = False) -> None:
        """Put `name` on PATH as a stand-in for this test's own Python, recording `note` when it runs."""
        stand_in(self.bin / name, sys.executable, note=note, skip_first_arg=skip_first_arg)

    def run(self, argv: list[str], stdin: str = "", **env: str) -> subprocess.CompletedProcess[str]:
        assert SH is not None
        full = {
            "PATH": str(self.bin),
            "CLAUDE_PROJECT_DIR": str(self.root),
            "MARKER": str(self.marker),
            **env,
        }
        return subprocess.run(
            argv, cwd=self.root, env=full, input=stdin, capture_output=True, text=True, timeout=60
        )

    def guard(self, target: str, **env: str) -> subprocess.CompletedProcess[str]:
        """Run the command from .claude/settings.json as Claude Code does, for a write to `target`."""
        assert SH is not None
        event = json.dumps({"tool_input": {"file_path": str(self.root / target)}})
        return self.run([SH, "-c", GUARD_COMMAND], event, **env)

    def commit_msg(self, message: str, **env: str) -> subprocess.CompletedProcess[str]:
        """Run the commit-msg hook as git does, on a message file."""
        assert SH is not None
        path = self.root / "COMMIT_EDITMSG"
        path.write_text(message, encoding="utf-8", newline="\n")
        return self.run([SH, str(self.root / ".githooks/commit-msg"), str(path)], **env)

    def ran(self) -> set[str]:
        return set(self.marker.read_text(encoding="utf-8").split()) if self.marker.exists() else set()


@pytest.fixture
def machine(tmp_path: Path) -> Machine:
    """A throwaway repo holding the hook files, and a PATH with `sh` and `git` but no Python."""
    assert SH is not None and GIT is not None
    root, bin_dir = tmp_path / "repo", tmp_path / "bin"
    for name in COPIED:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / name, root / name)
    subprocess.run([GIT, "init", "--quiet", str(root)], check=True, capture_output=True)
    stand_in(bin_dir / "sh", SH)
    stand_in(bin_dir / "git", GIT)
    return Machine(root, bin_dir, tmp_path / "marker")


@pytest.mark.parametrize(
    ("target", "code"),
    [("fixtures/intern/expected.json", 2), (".env", 2), ("theseus/cli.py", 0)],
)
def test_the_guard_judges_a_write_when_only_python3_is_on_the_path(
    machine: Machine, target: str, code: int
) -> None:
    machine.add("python3")
    done = machine.guard(target)
    assert done.returncode == code, done.stderr
    assert ("Blocked" in done.stderr) == (code == 2)


def test_the_commit_message_hook_judges_a_message_when_only_python3_is_on_the_path(machine: Machine) -> None:
    machine.add("python3")
    assert machine.commit_msg("feat: Add a thing\n").returncode == 0
    bad = machine.commit_msg("fixed bug.\n")
    assert bad.returncode == 1
    assert "subject must look like" in bad.stderr


@pytest.mark.parametrize(
    ("present", "ran"),
    [
        ({"python3": "python3"}, {"python3"}),
        ({"python": "python"}, {"python"}),
        ({"python3": "python3", "python": "python"}, {"python3"}),
        ({"py": "py"}, {"py"}),
        ({"python3": "", "python": "python"}, {"python"}),  # a python3 that does not run, like the Store stub
    ],
    ids=["python3", "python", "python3-first", "py-launcher", "broken-python3"],
)
def test_the_first_interpreter_that_runs_is_used(
    machine: Machine, present: dict[str, str], ran: set[str]
) -> None:
    for name, note in present.items():
        if note:
            machine.add(name, note=note, skip_first_arg=name == "py")
        else:
            stand_in(machine.bin / name, "/nonexistent/python3")
    done = machine.guard("fixtures/intern/expected.json")
    assert done.returncode == 2 and "Blocked" in done.stderr, done.stderr
    assert machine.ran() == ran


def test_the_project_venv_beats_python3_and_THESEUS_PYTHON_beats_both(machine: Machine) -> None:
    machine.add("python3", note="python3")
    stand_in(machine.root / ".venv/bin/python", sys.executable, note="venv")
    chosen = stand_in(machine.root / "elsewhere/python", sys.executable, note="named")

    assert machine.guard("theseus/cli.py").returncode == 0
    assert machine.ran() == {"venv"}

    machine.marker.unlink()
    assert machine.guard("theseus/cli.py", THESEUS_PYTHON=str(chosen)).returncode == 0
    assert machine.ran() == {"named"}


def test_the_guard_blocks_the_write_when_no_python_can_be_found(machine: Machine) -> None:
    """Failing open here would switch the guard off without a word."""
    done = machine.guard("theseus/cli.py")
    assert done.returncode == 2
    assert "No working Python" in done.stderr


def test_the_commit_message_hook_refuses_the_commit_when_no_python_can_be_found(machine: Machine) -> None:
    done = machine.commit_msg("feat: Add a thing\n")
    assert done.returncode != 0
    assert "No working Python" in done.stderr


def test_the_wired_hooks_are_the_ones_these_tests_run() -> None:
    """If the commands change shape, the tests above must be pointed at the new one."""
    assert "tools/py.sh" in GUARD_COMMAND and "tools/agent_guard.py" in GUARD_COMMAND
    hook = (REPO / ".githooks/commit-msg").read_text(encoding="utf-8")
    assert "tools/py.sh" in hook and "tools/check_commit_msg.py" in hook
    assert os.access(REPO / ".githooks/commit-msg", os.X_OK)
