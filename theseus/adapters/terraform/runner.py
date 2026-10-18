"""Plan a Terraform root from Python the way `tools/plan.sh` does: a copy of its configuration, no backend,
no state and no cloud account, so a local check plans exactly as the CI does.

Each plan is cached by a hash of the configuration it was made from, so checking the same change twice plans
once. Planning happens in one work folder whose providers stay installed: the AWS provider is hundreds of
megabytes, and a plugin cache would copy it on every run on Windows.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from theseus.errors import IngestError

# A developer's profile or session must not change the mock-only provider configuration (as in plan.sh).
UNSET = ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN")
INIT = ("init", "-backend=false", "-input=false", "-no-color")
PLAN = ("plan", "-refresh=false", "-input=false", "-lock=false", "-no-color", "-out=tfplan")
SHOW = ("show", "-json", "tfplan")
TAIL = 15


def sources(terraform_dir: Path) -> list[Path]:
    """The configuration files plan.sh copies: `*.tf` and `*.tf.json`, by name."""
    return sorted([*terraform_dir.glob("*.tf"), *terraform_dir.glob("*.tf.json")])


def fingerprint(files: list[Path]) -> str:
    """A hash of the files' names and contents: the same configuration always gives the same key."""
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()[:32]


def environment(work: Path, data: Path) -> dict[str, str]:
    """The isolated environment plan.sh sets up, with Terraform's data (its providers) kept in `data`."""
    env = {k: v for k, v in os.environ.items() if k not in UNSET}
    config, credentials = work / "aws-config", work / "aws-credentials"
    config.touch()
    credentials.touch()
    env |= {
        "TF_DATA_DIR": str(data),
        "TF_IN_AUTOMATION": "1",
        "CHECKPOINT_DISABLE": "1",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_CONFIG_FILE": str(config),
        "AWS_SHARED_CREDENTIALS_FILE": str(credentials),
    }
    return env


def _run(terraform: str, work: Path, args: tuple[str, ...], env: dict[str, str]) -> str:
    try:
        done = subprocess.run(
            [terraform, f"-chdir={work}", *args],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except FileNotFoundError:
        raise IngestError(
            f"{terraform} is not installed or not on PATH; it is needed to plan the change"
        ) from None
    if done.returncode != 0:
        tail = "\n".join(done.stderr.strip().splitlines()[-TAIL:])
        raise IngestError(f"terraform {args[0]} failed:\n{tail}")
    return done.stdout


def plan_json(terraform_dir: Path, cache_dir: Path, terraform: str = "terraform") -> dict[str, Any]:
    """The plan JSON of `terraform_dir`, from the cache when this configuration was planned before."""
    files = sources(terraform_dir)
    if not files:
        raise IngestError(f"no Terraform configuration in {terraform_dir}")
    cached = cache_dir / f"{fingerprint(files)}.plan.json"
    if cached.is_file():
        return json.loads(cached.read_text(encoding="utf-8"))
    # Configuration only, as plan.sh copies it: the last run's files and lock go first, and no state is kept.
    work = cache_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    for old in [*sources(work), work / ".terraform.lock.hcl", work / "tfplan"]:
        old.unlink(missing_ok=True)
    for path in files:
        shutil.copy2(path, work / path.name)
    env = environment(work, cache_dir / "terraform")
    _run(terraform, work, INIT, env)
    _run(terraform, work, PLAN, env)
    shown = _run(terraform, work, SHOW, env)
    try:
        plan = json.loads(shown)
    except ValueError as e:
        raise IngestError(f"terraform show did not print JSON: {e}") from e
    cached.write_text(json.dumps(plan), encoding="utf-8")
    return plan
