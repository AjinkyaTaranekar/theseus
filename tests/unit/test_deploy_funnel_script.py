"""deploy/deploy-funnel.sh against stand-in ssh, git, curl, pip and the runner: every failure path, offline.

The stand-ins keep their state in files: which commit is checked out and which one the API is running. Each
scenario sets how they fail.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "deploy-funnel.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

STUBS = {
    # ssh <host> <command...>: like real ssh, join the rest into one command for the remote shell, so an
    # argument that is not quoted for it splits or vanishes; or fail for one mode.
    "ssh": 'shift\ncase " $* " in *" ${FAKE_SSH_FAIL:-none} "*) exit 255 ;; esac\nexec bash -c "$*"\n',
    "sleep": "exit 0\n",
    "git": """
echo "git $*" >> "$FAKE/log"
case "$*" in
  "rev-parse HEAD"|"rev-parse --short HEAD") cat "$FAKE/head" ;;
  "fetch --quiet origin "*) [ "${FAKE_FETCH_FAIL:-0}" = 1 ] && exit 1; exit 0 ;;
  "reset --quiet --hard FETCH_HEAD") echo new > "$FAKE/head" ;;
  "reset --quiet --hard "*) echo "${@: -1}" > "$FAKE/head" ;;
esac
""",
    "curl": """
echo "curl $*" >> "$FAKE/log"
r="$(cat "$FAKE/running" 2>/dev/null)"
case "$*" in
  *127.0.0.1*)
    [ "$r" = new ] && [ "${FAKE_NEW_HEALTHY:-1}" = 1 ] && exit 0
    [ "$r" = old ] && exit 0
    exit 7 ;;
  *)
    [ "$r" = new ] && [ "${FAKE_PUBLIC_NEW:-1}" = 1 ] && exit 0
    [ "$r" = old ] && [ "${FAKE_PUBLIC_OLD:-1}" = 1 ] && exit 0
    exit 22 ;;
esac
""",
}


@dataclass
class Run:
    code: int
    out: str
    log: str
    head: str
    running: str


def deploy(
    tmp_path: Path, *, domain: str | None = "guest-box.example", ref: str = "main", **fake: int | str
) -> Run:
    bin_dir, state, vm, home = tmp_path / "bin", tmp_path / "state", tmp_path / "vm", tmp_path / "home"
    for d in (bin_dir, state, vm, home, vm / ".venv" / "bin", vm / "deploy"):
        d.mkdir(parents=True, exist_ok=True)
    stubs = {
        **{bin_dir / name: body for name, body in STUBS.items()},
        vm / ".venv" / "bin" / "pip": 'echo "pip $*" >> "$FAKE/log"\nexit "${FAKE_PIP_FAIL:-0}"\n',
        # The runner: a restart starts whatever is checked out.
        vm / "deploy" / "run.sh": 'echo "run.sh $*" >> "$FAKE/log"\ncp "$FAKE/head" "$FAKE/running"\n',
    }
    for path, body in stubs.items():
        path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
        path.chmod(0o755)
    for name, text in (("head", "old"), ("running", "old"), ("log", "")):
        (state / name).write_text(text + ("\n" if text else ""), encoding="utf-8", newline="\n")
    (vm / ".env").write_text(f"DOMAIN={domain or ''}\n", encoding="utf-8", newline="\n")
    env = {
        **os.environ,
        "PATH": f"{bin_dir.as_posix()}{os.pathsep}{os.environ['PATH']}",
        "HOME": home.as_posix(),
        "FAKE": state.as_posix(),
        "THESEUS_DIR": vm.as_posix(),
        "THESEUS_REF": ref,
        "THESEUS_TRIES": "2",
        "THESEUS_PUBLIC_TRIES": "2",
        "THESEUS_PUBLIC_WAIT": "0",
        **{f"FAKE_{k.upper()}": str(v) for k, v in fake.items()},
    }
    env.pop("THESEUS_DOMAIN", None)
    proc = subprocess.run(
        [BASH, SCRIPT.as_posix(), "dev@guest-box"], env=env, capture_output=True, text=True, timeout=60
    )
    read = lambda name: (state / name).read_text(encoding="utf-8").strip()  # noqa: E731
    return Run(proc.returncode, proc.stdout + proc.stderr, read("log"), read("head"), read("running"))


def test_a_healthy_deploy_is_live_only_after_the_public_check(tmp_path: Path) -> None:
    run = deploy(tmp_path)
    assert run.code == 0, run.out
    assert "LIVE: https://guest-box.example/health" in run.out
    assert (run.head, run.running) == ("new", "new")


def test_a_missing_domain_stops_before_anything_changes(tmp_path: Path) -> None:
    """Without a public name the deploy could never be called live, so it must stop before the restart."""
    run = deploy(tmp_path, domain=None)
    assert run.code == 1
    assert "no DOMAIN" in run.out and "nothing changed" in run.out
    assert "git fetch" not in run.log and "run.sh" not in run.log
    assert (run.head, run.running) == ("old", "old")


def test_a_failed_domain_lookup_stops_before_anything_changes(tmp_path: Path) -> None:
    run = deploy(tmp_path, ssh_fail="domain")
    assert run.code == 1
    assert "could not read DOMAIN" in run.out and "nothing changed" in run.out
    assert "git fetch" not in run.log
    assert (run.head, run.running) == ("old", "old")


def test_a_dead_public_endpoint_returns_to_the_previous_commit(tmp_path: Path) -> None:
    run = deploy(tmp_path, public_new=0)
    assert run.code == 1
    assert "never answered" in run.out and "returning to old" in run.out
    assert "ROLLED_BACK: old" in run.out
    assert (run.head, run.running) == ("old", "old")


def test_an_unhealthy_new_build_is_rolled_back_on_the_host(tmp_path: Path) -> None:
    run = deploy(tmp_path, new_healthy=0)
    assert run.code == 1
    assert "ROLLED_BACK: old" in run.out
    assert (run.head, run.running) == ("old", "old")
    assert run.out.count("ROLLED_BACK") == 1  # the host's own rollback, not a second one from here


def test_a_failed_install_is_rolled_back_on_the_host(tmp_path: Path) -> None:
    run = deploy(tmp_path, pip_fail=1)
    assert run.code == 1
    assert "ROLLED_BACK" in run.out or "ROLLBACK_FAILED" in run.out
    assert run.head == "old"


def test_a_failed_fetch_changes_nothing(tmp_path: Path) -> None:
    run = deploy(tmp_path, fetch_fail=1)
    assert run.code == 1
    assert "nothing changed" in run.out
    assert "run.sh" not in run.log
    assert (run.head, run.running) == ("old", "old")


@pytest.mark.parametrize("ref", ["--upload-pack=touch /tmp/x", "-x", "a..b", "main;id"])
def test_a_ref_that_is_not_a_name_is_refused(tmp_path: Path, ref: str) -> None:
    run = deploy(tmp_path, ref=ref)
    assert run.code == 2
    assert "not a branch, tag or commit name" in run.out
    assert run.log == ""
