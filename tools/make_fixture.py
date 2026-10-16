#!/usr/bin/env python3
"""Generate scenario inputs from demo-infra; human answer keys are never touched.

Windows uses Git for Windows' native Bash. Set THESEUS_BASH to select another Bash executable.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath
from tempfile import mkdtemp
from typing import Literal

import yaml
from pydantic import BaseModel

from theseus.errors import IngestError

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]


class Scenario(BaseModel):
    """The mode, text and source addition for one scenario in spec 02."""

    mode: Literal["pr", "finding", "scan"]
    description: str
    title: str = ""
    body: str = ""
    file: str = ""
    addition: str = ""


SCENARIOS = {
    "intern": Scenario(
        mode="pr",
        description="Add Priya to support-engineers for prod log access.",
        title="Add Priya to support-engineers for prod log access",
        body="Priya joins support this week. Adding her to support-engineers so she can read prod logs "
        "during onboarding.",
        file="terraform/people.tf",
        addition="""
resource "aws_iam_user_group_membership" "priya_support" {
  user   = "priya-intern"
  groups = ["support-engineers"]
}
""",
    ),
    "public-bucket": Scenario(
        mode="pr",
        description="Make company-files public so marketing can link the pricing PDF.",
        title="Make company-files public so marketing can link the pricing PDF",
        body="Marketing wants to link public/pricing.pdf from the website.",
        file="terraform/data.tf",
        addition="""
resource "aws_s3_bucket_policy" "company_files_public" {
  bucket = "demo-company-files"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicRead"
      Effect    = "Allow"
      Principal = "*"
      Action    = "s3:GetObject"
      Resource  = "arn:aws:s3:::demo-company-files/*"
    }]
  })
}
""",
    ),
    "compromised-action": Scenario(
        mode="finding",
        description="Synthetic advisory for the fictional demo-thirdparty/file-diff Action; "
        "assume versions v1, v2 and v3 are compromised. Nothing here describes a real compromise.",
    ),
    "unused-grant": Scenario(mode="scan", description="Scan main for grants that service code never calls."),
    # C1 adds code-pr after its service modules exist; all deliberately generates four fixtures until then.
}

COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    ".terraform",
    ".terraform.lock.hcl",
    "*.tfstate",
    "*.tfstate.*",
    "tfplan",
    "*.plan.json",
    "__pycache__",
    "*.py[cod]",
    ".DS_Store",
    ".env",
    ".env.*",
)
OWNED = ("base", "head", "base.plan.json", "head.plan.json", "scenario.yaml", "pr.md", "advisory.json")


class _RecoveryError(IngestError):
    """A failed rollback whose staged backups must remain available for recovery."""


def resolve_bash() -> str:
    """Return the configured native Bash, preferring Git for Windows over WSL."""
    wsl_launchers = {"system32", "sysnative", "windowsapps"}
    configured = os.environ.get("THESEUS_BASH")
    if configured:
        executable = shutil.which(configured)
        if executable is None or (
            sys.platform == "win32" and PureWindowsPath(executable).parent.name.casefold() in wsl_launchers
        ):
            raise IngestError(f"THESEUS_BASH must name a native Bash executable, not WSL: {configured}")
        return executable
    if sys.platform == "win32":
        roots: list[Path] = []
        git = shutil.which("git")
        if git:
            roots.extend(Path(git).parents)
        for setting in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            directory = os.environ.get(setting)
            if directory:
                suffix = "Programs/Git" if setting == "LOCALAPPDATA" else "Git"
                roots.append(Path(directory) / suffix)
        for root in roots:
            executable = root / "usr/bin/bash.exe"
            if executable.is_file():
                return str(executable)
    executable = shutil.which("bash")
    if executable is not None:
        launcher = PureWindowsPath(executable).parent.name.casefold()
        if sys.platform != "win32" or launcher not in wsl_launchers:
            return executable
    raise IngestError("Native Bash was not found; install Git Bash or set THESEUS_BASH to its bash.exe")


def plan_world(world: Path, output: Path, *, bash: str) -> None:
    """Write deterministic Terraform plan JSON for a copied world."""
    environment = None
    if sys.platform == "win32":
        environment = dict(os.environ)
        environment["PATH"] = str(Path(bash).parent) + os.pathsep + environment.get("PATH", "")
    subprocess.run(
        [
            bash,
            "--",
            (ROOT / "tools/plan.sh").as_posix(),
            (world / "terraform").as_posix(),
            output.as_posix(),
        ],
        env=environment,
        check=True,
    )
    plan = json.loads(output.read_text(encoding="utf-8"))
    if (
        not isinstance(plan, dict)
        or plan.get("errored") is True
        or plan.get("complete") is False
        or not isinstance(plan.get("planned_values"), dict)
        or not isinstance(plan["planned_values"].get("root_module"), dict)
        or not isinstance(plan["planned_values"]["root_module"].get("resources"), list)
        or not isinstance(plan.get("resource_changes"), list)
    ):
        raise IngestError(f"Terraform did not return a complete plan object for {world}")
    # Terraform's run timestamp is metadata, not infrastructure. Keep every value and unknown-field marker.
    plan.pop("timestamp", None)
    output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _publish(staging: Path, target: Path) -> None:
    """Replace the owned inputs, restoring their previous versions if publication fails."""
    backup = staging / "previous"
    backup.mkdir()
    previous: list[str] = []
    installed: list[str] = []
    try:
        for filename in OWNED:
            destination = target / filename
            if destination.exists() or destination.is_symlink():
                os.replace(destination, backup / filename)
                previous.append(filename)
            source = staging / filename
            if source.exists():
                os.replace(source, destination)
                installed.append(filename)
    except OSError as exc:
        try:
            for filename in reversed(installed):
                os.replace(target / filename, staging / filename)
            for filename in reversed(previous):
                os.replace(backup / filename, target / filename)
        except OSError as rollback_exc:
            raise _RecoveryError(
                f"Publish failed ({exc}); rollback also failed ({rollback_exc}). "
                f"Recovery files are preserved at {staging}"
            ) from rollback_exc
        raise


def generate(name: str, world_root: Path, fixture_root: Path, *, bash: str | None = None) -> None:
    """Write one fixture's generated inputs, preserving every human-owned file."""
    if name not in SCENARIOS:
        if name == "code-pr":
            raise IngestError(
                "code-pr needs C1's service code and scenario changes; F4 generates four fixtures"
            )
        raise IngestError(f"Unknown scenario: {name}")
    scenario = SCENARIOS[name]
    staging: Path | None = None
    preserve_staging = False
    published = False
    try:
        bash = resolve_bash() if bash is None else bash
        fixture_root.mkdir(parents=True, exist_ok=True)
        # Finish both plans before replacing any existing inputs. A failed plan leaves the old fixture intact.
        staging = Path(mkdtemp(prefix=f".{name}-", dir=fixture_root))
        shutil.copytree(world_root, staging / "base", ignore=COPY_IGNORE)
        plan_world(staging / "base", staging / "base.plan.json", bash=bash)
        if scenario.mode == "pr":
            shutil.copytree(staging / "base", staging / "head")
            changed = staging / "head" / scenario.file
            with changed.open("a", encoding="utf-8", newline="\n") as source:
                source.write(scenario.addition)
            plan_world(staging / "head", staging / "head.plan.json", bash=bash)
            (staging / "pr.md").write_text(
                f"# {scenario.title}\n\n{scenario.body}\n", encoding="utf-8", newline="\n"
            )
        if scenario.mode == "finding":
            advisory = {
                "id": "GHSA-demo-0001",
                "action": "demo-thirdparty/file-diff",
                "affected_versions": ["v1", "v2", "v3"],
                "text": "Summary: Credential disclosure in demo-thirdparty/file-diff.\n\n"
                "Severity: Critical.\n\n"
                "Affected versions: v1, v2 and v3.\n"
                "Patched versions: v4.\n\n"
                "The affected Action versions execute a payload that dumps runner memory and secrets "
                "to the build log. Anyone able to read the log may recover credentials available to "
                "the runner, including workflow tokens and temporary cloud credentials.\n\n"
                "Upgrade to v4, pin the reviewed commit, and rotate credentials exposed by affected runs. "
                "Restrict access to affected build logs while investigating.",
            }
            (staging / "advisory.json").write_text(
                json.dumps(advisory, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
            )
        metadata = {
            "name": name,
            "mode": scenario.mode,
            "world": "demo-infra",
            "description": scenario.description,
        }
        (staging / "scenario.yaml").write_text(
            yaml.safe_dump(metadata, sort_keys=True), encoding="utf-8", newline="\n"
        )
        target = fixture_root / name
        target.mkdir(exist_ok=True)
        _publish(staging, target)
        published = True
    except _RecoveryError:
        preserve_staging = True
        raise
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise IngestError(f"Could not generate {name}: {exc}") from exc
    finally:
        if staging is not None and not preserve_staging:
            try:
                shutil.rmtree(staging)
            except OSError as exc:
                if published:
                    raise IngestError(f"Could not remove staging directory {staging}: {exc}") from exc
                log.warning("Could not remove staging directory %s after generation failed: %s", staging, exc)
    log.info("Generated %s", target)


def main() -> int:
    """Return the exit status after generating the requested fixture inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=[*sorted(SCENARIOS), "all", "code-pr"])
    args = parser.parse_args()
    names = sorted(SCENARIOS) if args.scenario == "all" else [args.scenario]
    try:
        bash = resolve_bash() if args.scenario != "code-pr" else None
        for name in names:
            generate(name, ROOT / "demo-infra", ROOT / "fixtures", bash=bash)
    except IngestError as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
