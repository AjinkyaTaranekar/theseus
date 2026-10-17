"""Pinned local Terraform scans; CLI options: https://www.checkov.io/2.Basics/CLI%20Command%20Reference.html."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pydantic import Field, ValidationError

from theseus.contracts.result import Contract
from theseus.errors import IngestError

log = logging.getLogger(__name__)
VERSION = "3.3.29"


class Finding(Contract):
    check_id: str
    resource: str


class CheckovReport(Contract):
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    findings: list[Finding] = Field(default_factory=list)
    raw_stdout: str = ""
    raw_stderr: str = ""


class ScanFailure(Contract):
    reason: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None


class CheckovError(IngestError):
    """A failed scan with its original tool output retained for inspection."""

    def __init__(self, failure: ScanFailure) -> None:
        super().__init__(failure.reason)
        self.failure = failure


class CheckovComparison(Contract):
    base: CheckovReport
    head: CheckovReport
    introduced: list[Finding]
    resolved: list[Finding]


def _count(summary: dict[str, Any], key: str) -> int:
    value = summary.get(key)
    if type(value) is not int or value < 0:
        raise IngestError(f"Checkov summary has invalid {key}")
    return value


def parse_report(raw: str, exit_code: int) -> CheckovReport:
    """Return validated Terraform findings, rejecting crashes and incomplete scans."""
    if exit_code not in (0, 1):
        raise IngestError(f"Checkov exited {exit_code}; scan did not complete")
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise IngestError("Checkov did not return JSON") from exc
    reports = parsed if isinstance(parsed, list) else [parsed]
    if not reports:
        raise IngestError("Checkov returned no report")
    result = CheckovReport(raw_stdout=raw)
    found: dict[tuple[str, str], Finding] = {}
    for report in reports:
        if not isinstance(report, dict) or report.get("check_type") != "terraform":
            raise IngestError("Checkov did not return a Terraform report")
        summary, checks = report.get("summary"), report.get("results")
        if not isinstance(summary, dict) or not isinstance(checks, dict):
            raise IngestError("Checkov report is missing summary/results")
        if _count(summary, "parsing_errors") or checks.get("parsing_errors"):
            raise IngestError("Checkov reported parsing errors")
        for kind, field in (
            ("passed", "passed_checks"),
            ("failed", "failed_checks"),
            ("skipped", "skipped_checks"),
        ):
            records = checks.get(field)
            if not isinstance(records, list) or len(records) != _count(summary, kind):
                raise IngestError(f"Checkov {kind} count disagrees with its findings")
            setattr(result, kind, getattr(result, kind) + len(records))
        for record in checks["failed_checks"]:
            if not isinstance(record, dict):
                raise IngestError("Checkov returned an invalid failed check")
            try:
                item = Finding(check_id=record["check_id"], resource=record["resource"])
            except (KeyError, ValidationError) as exc:
                raise IngestError("Checkov failed check needs check_id and resource") from exc
            if not item.check_id or not item.resource:
                raise IngestError("Checkov failed check has an empty identity")
            found[item.check_id, item.resource] = item
    if (exit_code == 1) != (result.failed > 0):
        raise IngestError("Checkov exit status disagrees with failed checks")
    result.findings = [found[key] for key in sorted(found)]
    return result


def compare_reports(base: CheckovReport, head: CheckovReport) -> CheckovComparison:
    """Return new and resolved check/resource identities, independent of line movement."""
    before = {(item.check_id, item.resource): item for item in base.findings}
    after = {(item.check_id, item.resource): item for item in head.findings}
    return CheckovComparison(
        base=base,
        head=head,
        introduced=[after[key] for key in sorted(after.keys() - before.keys())],
        resolved=[before[key] for key in sorted(before.keys() - after.keys())],
    )


def _environment() -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def check_version(executable: str = "checkov") -> str:
    """Return the required executable version or raise IngestError."""
    try:
        completed = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=30, env=_environment()
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IngestError(f"Checkov {VERSION} executable unavailable") from exc
    if completed.returncode != 0 or completed.stdout.strip() != VERSION:
        raise IngestError(f"Benchmark requires Checkov {VERSION}")
    return VERSION


def scan(root: Path, executable: str = "checkov", *, timeout: int = 180) -> CheckovReport:
    """Return a complete local scan, without external module downloads or platform uploads."""
    if timeout <= 0:
        raise IngestError("Checkov timeout must be positive")
    try:
        with TemporaryDirectory(prefix="theseus-checkov-") as directory:
            config = Path(directory) / "config.yaml"
            config.write_text("{}\n", encoding="utf-8")
            completed = subprocess.run(
                [
                    executable,
                    "--config-file",
                    str(config),
                    "--directory",
                    str(root.resolve()),
                    "--framework",
                    "terraform",
                    "--output",
                    "json",
                    "--compact",
                    "--download-external-modules",
                    "false",
                    "--skip-download",
                    "--skip-results-upload",
                ],
                cwd=directory,
                env=_environment(),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired as exc:
        raise IngestError(f"Checkov timed out after {timeout}s") from exc
    except OSError as exc:
        raise IngestError("Checkov executable could not run") from exc
    try:
        return parse_report(completed.stdout, completed.returncode).model_copy(
            update={"raw_stderr": completed.stderr}
        )
    except IngestError as exc:
        raise CheckovError(
            ScanFailure(
                reason=str(exc),
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
            )
        ) from exc
