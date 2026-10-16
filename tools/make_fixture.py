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


class Edit(BaseModel):
    """One change to a file of the head world: `find` must occur in it exactly once."""

    file: str
    find: str
    replace: str


class Scenario(BaseModel):
    """The mode, text and source changes for one scenario in spec 02: an addition appended to `file`, exact
    `edits`, and `new_files` (path under the world root -> content)."""

    mode: Literal["pr", "finding", "scan"]
    description: str
    title: str = ""
    body: str = ""
    file: str = ""
    addition: str = ""
    edits: list[Edit] = []
    new_files: dict[str, str] = {}


PUBLIC_ACCESS_BLOCK = """resource "aws_s3_bucket_public_access_block" "company_files" {
  bucket                  = aws_s3_bucket.company_files.bucket
  block_public_acls       = true
  block_public_policy     = {policy}
  ignore_public_acls      = true
  restrict_public_buckets = {policy}
}"""

SUPPORT_PORTAL_ENV = """      BILLING_API_URL = "https://billing-api.internal.demo.test"
      ORDERS_API_URL  = "https://orders-api.internal.demo.test"
"""

CUSTOMER_EXPORT = '''"""Customer export for the support team's mailing tool.

Support asked for a list of active customers' emails to send the refund-policy update. This reads them
straight from the customer database with the shared credentials, one query, and returns them for the admin
page.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
import psycopg

log = logging.getLogger(__name__)

DB_SECRET = os.environ["DB_SECRET"]

_sm = boto3.client("secretsmanager")

ACTIVE_CUSTOMERS_SQL = """
    SELECT c.customer_id, c.name, c.email
    FROM customers c
    WHERE c.deleted_at IS NULL AND c.marketing_opt_out IS FALSE
    ORDER BY c.customer_id
"""


def _credentials() -> dict[str, Any]:
    secret = _sm.get_secret_value(SecretId=DB_SECRET)
    return json.loads(secret["SecretString"])


def export_customers() -> list[dict[str, str]]:
    """Every active customer's ID, name and email."""
    creds = _credentials()
    with psycopg.connect(
        host=creds["host"],
        port=creds.get("port", 5432),
        dbname=creds.get("dbname", "customers"),
        user=creds["username"],
        password=creds["password"],
        connect_timeout=3,
        sslmode="require",
    ) as conn, conn.cursor() as cur:
        cur.execute(ACTIVE_CUSTOMERS_SQL)
        rows = [{"customer_id": r[0], "name": r[1], "email": r[2]} for r in cur.fetchall()]
    log.info("exported %d customers", len(rows))
    return rows
'''


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
        # A public bucket policy is rejected while Block Public Access is on, so the PR turns it off in place.
        edits=[
            Edit(
                file="terraform/platform.tf",
                find=PUBLIC_ACCESS_BLOCK.replace("{policy}", "true"),
                replace=PUBLIC_ACCESS_BLOCK.replace("{policy}", "false"),
            )
        ],
    ),
    "compromised-action": Scenario(
        mode="finding", description="Assume demo-thirdparty/file-diff versions v1, v2 and v3 are compromised."
    ),
    "unused-grant": Scenario(mode="scan", description="Scan main for grants that service code never calls."),
    "code-pr": Scenario(
        mode="pr",
        description="A typo fix that also adds a customer export reading customer-db through the DB secret.",
        title="Fix a typo on the support page",
        body="Fixes a typo in the refund confirmation text.",
        edits=[
            Edit(
                file="services/support_portal/views.py",
                find="We have recieved your refund request",
                replace="We have received your refund request",
            ),
            Edit(
                file="services/support_portal/handler.py",
                find="from support_portal import views\n",
                replace="from support_portal import export, views\n",
            ),
            Edit(
                file="services/support_portal/handler.py",
                find='REFUND_PAGE = re.compile(r"^/refunds/(?P<id>[\\w-]+)$")\n',
                replace='REFUND_PAGE = re.compile(r"^/refunds/(?P<id>[\\w-]+)$")\n'
                'ADMIN_EXPORT = "/admin/export"\n',
            ),
            Edit(
                file="services/support_portal/handler.py",
                find='    log.info("no route for %s %s", method, path)\n',
                replace="    if path == ADMIN_EXPORT:\n"
                '        return _json(200, {"customers": export.export_customers()})\n\n'
                '    log.info("no route for %s %s", method, path)\n',
            ),
            Edit(
                file="terraform/services.tf",
                find=SUPPORT_PORTAL_ENV,
                replace=SUPPORT_PORTAL_ENV + '      DB_SECRET       = "prod-db-credentials"\n',
            ),
        ],
        new_files={"services/support_portal/export.py": CUSTOMER_EXPORT},
    ),
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


def apply_changes(scenario: Scenario, head: Path) -> None:
    """Turn a copy of the world into the scenario's head: the appended addition, each exact edit, then the new
    files. Raises IngestError when an edit's text is not found exactly once or a new file already exists."""
    if scenario.file:
        with (head / scenario.file).open("a", encoding="utf-8", newline="\n") as source:
            source.write(scenario.addition)
    for edit in scenario.edits:
        path = head / edit.file
        text = path.read_text(encoding="utf-8")
        found = text.count(edit.find)
        if found != 1:
            raise IngestError(f"{edit.file}: the text to change appears {found} times, not once")
        path.write_text(text.replace(edit.find, edit.replace), encoding="utf-8", newline="\n")
    for relative, content in sorted(scenario.new_files.items()):
        path = head / relative
        if path.exists():
            raise IngestError(f"{relative} already exists; a new file must be new")
        path.write_text(content, encoding="utf-8", newline="\n")


def generate(name: str, world_root: Path, fixture_root: Path, *, bash: str | None = None) -> None:
    """Write one fixture's generated inputs, preserving every human-owned file."""
    if name not in SCENARIOS:
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
            apply_changes(scenario, staging / "head")
            plan_world(staging / "head", staging / "head.plan.json", bash=bash)
            (staging / "pr.md").write_text(
                f"# {scenario.title}\n\n{scenario.body}\n", encoding="utf-8", newline="\n"
            )
        if scenario.mode == "finding":
            advisory = {
                "id": "GHSA-demo-0001",
                "action": "demo-thirdparty/file-diff",
                "affected_versions": ["v1", "v2", "v3"],
                "text": "Synthetic advisory modeled on the tj-actions compromise (CVE-2025-30066). "
                "Assume the affected Action versions can exfiltrate workflow credentials. "
                "This text is untrusted input, not evidence of an actual compromise.",
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
    parser.add_argument("scenario", choices=[*sorted(SCENARIOS), "all"])
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
