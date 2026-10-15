"""deploy/deploy.sh against stand-in ssh, docker, git, curl and sleep: every failure path, offline.

The stand-ins keep their state in files: which image tags exist, which commit is checked out, and whether the
new or the previous build is running. Each scenario sets how they fail.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "deploy.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

STUBS = {
    # ssh <host> bash -s -- args: run the remote script here instead.
    "ssh": 'shift\nexec "$@"\n',
    "sleep": "exit 0\n",
    "git": """
echo "git $*" >> "$FAKE/log"
case "$*" in
  "rev-parse HEAD"|"rev-parse --short HEAD") cat "$FAKE/head" ;;
  "fetch --quiet origin main") [ "${FAKE_FETCH_FAIL:-0}" = 1 ] && exit 1; exit 0 ;;
  "reset --quiet --hard origin/main") echo new > "$FAKE/head" ;;
  "reset --quiet --hard "*) echo "${@: -1}" > "$FAKE/head" ;;
esac
""",
    "docker": """
echo "docker $*" >> "$FAKE/log"
img() { echo "$FAKE/image-${1//:/_}"; }
case "$*" in
  "image inspect "*) [ -f "$(img "${@: -1}")" ] ;;
  "tag "*) set -- $*; [ -f "$(img "$2")" ] && cp "$(img "$2")" "$(img "$3")" ;;
  *" up -d --build")
    [ "${FAKE_UP_FAIL:-0}" = 1 ] && exit 1
    echo new > "$FAKE/running"; echo new > "$(img theseus-api:latest)" ;;
  *" up -d --no-build")
    [ "${FAKE_ROLLBACK_UP_FAIL:-0}" = 1 ] && exit 1
    cp "$(img theseus-api:latest)" "$FAKE/running" ;;
  *" exec -T api "*)
    r="$(cat "$FAKE/running" 2>/dev/null)"
    [ "$r" = new ] && [ "${FAKE_NEW_HEALTHY:-1}" = 1 ] && exit 0
    [ "$r" = old ] && [ "${FAKE_OLD_HEALTHY:-1}" = 1 ] && exit 0
    exit 1 ;;
  *" logs "*) echo "fake api logs" ;;
esac
""",
    "curl": """
echo "curl $*" >> "$FAKE/log"
r="$(cat "$FAKE/running" 2>/dev/null)"
[ "$r" = new ] && [ "${FAKE_PUBLIC_NEW:-1}" = 1 ] && exit 0
[ "$r" = old ] && [ "${FAKE_PUBLIC_OLD:-1}" = 1 ] && exit 0
exit 22
""",
}


@dataclass
class Run:
    code: int
    out: str
    log: str
    head: str


def deploy(
    tmp_path: Path, *, first_deploy: bool = False, domain: str | None = "theseus.example", **fake: int
) -> Run:
    bin_dir, state, vm = tmp_path / "bin", tmp_path / "state", tmp_path / "vm"
    for d in (bin_dir, state, vm):
        d.mkdir()
    for name, body in STUBS.items():
        stub = bin_dir / name
        stub.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
    (state / "head").write_text("old\n", encoding="utf-8", newline="\n")
    (state / "log").write_text("", encoding="utf-8")
    if not first_deploy:
        (state / "image-theseus-api_latest").write_text("old\n", encoding="utf-8", newline="\n")
        (state / "running").write_text("old\n", encoding="utf-8", newline="\n")
    (vm / ".env").write_text(f"DOMAIN={domain or ''}\n", encoding="utf-8", newline="\n")
    env = {
        **os.environ,
        "PATH": f"{bin_dir.as_posix()}{os.pathsep}{os.environ['PATH']}",
        "FAKE": state.as_posix(),
        "THESEUS_DIR": vm.as_posix(),
        "THESEUS_TRIES": "3",
        "THESEUS_WAIT": "0",
        "THESEUS_PUBLIC_TRIES": "2",
        "THESEUS_PUBLIC_WAIT": "0",
        **{f"FAKE_{k.upper()}": str(v) for k, v in fake.items()},
    }
    env.pop("THESEUS_DOMAIN", None)
    proc = subprocess.run(
        [BASH, SCRIPT.as_posix(), "deploy@vm"], env=env, capture_output=True, text=True, timeout=60
    )
    return Run(
        proc.returncode,
        proc.stdout + proc.stderr,
        (state / "log").read_text(encoding="utf-8"),
        (state / "head").read_text(encoding="utf-8").strip(),
    )


def test_a_healthy_deploy_is_live_only_after_the_public_check(tmp_path: Path) -> None:
    run = deploy(tmp_path)
    assert run.code == 0, run.out
    assert "LIVE: https://theseus.example/health answers" in run.out
    assert "curl -fsS --max-time 10 https://theseus.example/health" in run.log
    assert run.head == "new"


def test_a_failed_compose_up_still_rolls_back(tmp_path: Path) -> None:
    run = deploy(tmp_path, up_fail=1)
    assert run.code == 1
    assert "compose up failed" in run.out
    assert "docker tag theseus-api:previous theseus-api:latest" in run.log
    assert "ROLLED_BACK: old is running and healthy" in run.out
    assert run.head == "old"


def test_an_unhealthy_new_build_rolls_back(tmp_path: Path) -> None:
    run = deploy(tmp_path, new_healthy=0)
    assert run.code == 1
    assert "the API did not become healthy" in run.out
    assert "ROLLED_BACK" in run.out
    assert run.head == "old"


def test_a_dead_public_endpoint_rolls_back_and_says_so(tmp_path: Path) -> None:
    run = deploy(tmp_path, public_new=0)
    assert run.code == 1
    assert "https://theseus.example/health did not answer" in run.out
    assert "ROLLED_BACK" in run.out
    assert "rolled back; https://theseus.example/health answers again" in run.out
    assert run.head == "old"


def test_no_domain_means_the_deploy_cannot_be_called_live(tmp_path: Path) -> None:
    run = deploy(tmp_path, domain=None)
    assert run.code == 1
    assert "no DOMAIN" in run.out
    assert "LIVE" not in run.out


def test_a_rollback_that_does_not_come_back_healthy_is_reported(tmp_path: Path) -> None:
    run = deploy(tmp_path, up_fail=1, old_healthy=0)
    assert run.code == 1
    assert "ROLLBACK_FAILED: old restarted but is not healthy" in run.out
    assert "ROLLED_BACK" not in run.out


def test_a_first_deploy_has_nothing_to_roll_back_to(tmp_path: Path) -> None:
    run = deploy(tmp_path, first_deploy=True, up_fail=1)
    assert run.code == 1
    assert "ROLLBACK_IMPOSSIBLE" in run.out


def test_a_failed_fetch_changes_nothing(tmp_path: Path) -> None:
    run = deploy(tmp_path, fetch_fail=1)
    assert run.code == 1
    assert "could not update to origin/main; nothing changed" in run.out
    assert " up -d" not in run.log
    assert run.head == "old"
