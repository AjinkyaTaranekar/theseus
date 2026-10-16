"""deploy/deploy-funnel.sh against stand-in ssh, git, curl, pip and the runner: every failure path, offline.

The stand-ins keep their state in files: which commit is checked out and which one the API is running. Each
scenario sets how they fail.
"""

from __future__ import annotations

import os
import runpy
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "deploy-funnel.sh"
BASH = shutil.which("bash")
if sys.platform == "win32":
    # Git's own usr/bin/bash.exe: its bin/bash.exe launcher puts Git's /usr/bin, and its real ssh, first.
    BASH = runpy.run_path(str(SCRIPT.parents[1] / "tools/make_fixture.py"))["resolve_bash"]()
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")
TOOLS = ("ssh", "git", "curl", "sleep")

STUBS = {
    # ssh <host> <command...>: like real ssh, join the rest into one command for the remote shell, so an
    # argument that is not quoted for it splits or vanishes; or fail for one mode.
    # The command always runs to the end on the host. FAKE_SSH_DROP then loses the connection after every line
    # arrived; FAKE_SSH_CUT loses it after the host's first two lines (PREVIOUS and DEPLOYING), so the rest of
    # its answer never arrives.
    "ssh": (
        'shift\ncase " $* " in *" ${FAKE_SSH_FAIL:-none} "*) exit 255 ;; esac\n'
        'for m in ${FAKE_SSH_DROP:-}; do case " $* " in *" $m "*) bash -c "$*"; exit 255 ;; esac; done\n'
        'for m in ${FAKE_SSH_CUT:-}; do case " $* " in *" $m "*)\n'
        '  bash -c "$*" > "$FAKE/answer"\n'
        '  grep -E "^(PREVIOUS|DEPLOYING)=" "$FAKE/answer"; exit 255 ;; esac; done\n'
        'exec bash -c "$*"\n'
    ),
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


def bash_path(path: Path) -> str:
    """The path in the native shell's namespace."""
    if sys.platform != "win32":
        return path.as_posix()
    result = subprocess.run(
        [BASH, "-c", 'PATH="/usr/bin:$PATH"; cygpath -u -- "$1"', "theseus-test", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=30,
    )
    return result.stdout.rstrip("\r\n")


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
        "HOME": bash_path(home),
        "FAKE": bash_path(state),
        "THESEUS_DIR": bash_path(vm),
        "THESEUS_REF": ref,
        "THESEUS_TRIES": "2",
        "THESEUS_PUBLIC_TRIES": "2",
        "THESEUS_PUBLIC_WAIT": "0",
        **{f"FAKE_{k.upper()}": str(v) for k, v in fake.items()},
    }
    env.pop("THESEUS_DOMAIN", None)
    # PATH is set inside the shell with the stand-ins first, and the run stops if one is not found there: a
    # test must never reach a real ssh or curl.
    proc = subprocess.run(
        [
            BASH,
            "-c",
            'export PATH="$1:/usr/bin:/bin"; '
            f"for tool in {' '.join(TOOLS)}; do "
            '[[ "$(command -v "$tool")" == "$1/$tool" ]] || '
            '{ echo "offline stand-in missing: $tool" >&2; exit 90; }; '
            'done; shift; exec "$BASH" -- "$@"',
            "theseus-funnel-test",
            bash_path(bin_dir),
            bash_path(SCRIPT),
            "dev@guest-box",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
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


def test_a_host_that_cannot_return_to_the_previous_commit_needs_a_person(tmp_path: Path) -> None:
    """pip fails for the new build and for the rollback: the host says so, so nothing counts as handled."""
    run = deploy(tmp_path, pip_fail=1)
    assert run.code == 3
    assert "ROLLBACK_FAILED" in run.out and "UNCERTAIN: the host could not return to old" in run.out


def test_a_lost_answer_after_the_restart_is_rolled_back_over_a_new_connection(tmp_path: Path) -> None:
    """The host restarted the new build and was healthy, but SSH dropped before it said so."""
    run = deploy(tmp_path, ssh_cut="deploy")
    assert run.code == 1
    assert "no answer from the host" in run.out and "returning to old" in run.out
    assert "ROLLED_BACK: old" in run.out and "UNCERTAIN" not in run.out
    assert (run.head, run.running) == ("old", "old")


def test_a_healthy_answer_that_arrived_still_goes_through_the_public_check(tmp_path: Path) -> None:
    """The host's HEALTHY line arrived before the connection dropped: believe it, and still check publicly."""
    run = deploy(tmp_path, ssh_drop="deploy")
    assert run.code == 0, run.out
    assert "reported HEALTHY before the connection dropped" in run.out and "LIVE:" in run.out
    assert (run.head, run.running) == ("new", "new")


@pytest.mark.parametrize("rollback", ["fail", "cut"])
def test_an_unconfirmed_rollback_needs_a_person(tmp_path: Path, rollback: str) -> None:
    """The rollback cannot connect, or its answer is lost too: the state is unknown, so exit 3."""
    fake = (
        {"ssh_cut": "deploy", "ssh_fail": "rollback"}
        if rollback == "fail"
        else {"ssh_cut": "deploy rollback"}
    )
    run = deploy(tmp_path, **fake)
    assert run.code == 3
    assert "UNCERTAIN: the rollback was not confirmed" in run.out
    assert "LIVE" not in run.out


def test_a_dead_public_endpoint_with_no_rollback_answer_needs_a_person(tmp_path: Path) -> None:
    run = deploy(tmp_path, public_new=0, ssh_fail="rollback")
    assert run.code == 3
    assert "never answered" in run.out and "UNCERTAIN: the rollback was not confirmed" in run.out
    assert (run.head, run.running) == ("new", "new")


def test_ssh_that_fails_before_the_host_reports_is_uncertain(tmp_path: Path) -> None:
    run = deploy(tmp_path, ssh_fail="deploy")
    assert run.code == 3
    assert "UNCERTAIN: SSH failed before the host reported its commit" in run.out


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


def test_a_missing_stand_in_never_falls_back_to_a_real_ssh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real ssh earlier on PATH (Git for Windows has one) must never be reached: the run stops first."""
    outside = tmp_path / "outside test bin"
    outside.mkdir()
    marker = tmp_path / "real-ssh-called"
    ssh = outside / "ssh"
    ssh.write_text(
        '#!/usr/bin/env bash\necho called > "$THESEUS_TEST_REAL_SSH"\nexit 91\n',
        encoding="utf-8",
        newline="\n",
    )
    ssh.chmod(0o755)
    chmod = Path.chmod

    def drop_the_ssh_stand_in(path: Path, mode: int, **kwargs: object) -> None:
        chmod(path, mode, **kwargs)
        if path == tmp_path / "bin/ssh":
            path.unlink()

    monkeypatch.setattr(Path, "chmod", drop_the_ssh_stand_in)
    monkeypatch.setenv("PATH", str(outside) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("THESEUS_TEST_REAL_SSH", marker.as_posix())
    run = deploy(tmp_path)
    assert run.code == 90
    assert "offline stand-in missing: ssh" in run.out
    assert not marker.exists()
