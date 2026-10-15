"""The analysis routes (docs/spec/05-contracts.md, "API").

Until E3 and A5 they answer `{fixture}` with a stub.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from theseus.api.stub import result_from_expected
from theseus.contracts.result import AnalysisResult

log = logging.getLogger(__name__)
router = APIRouter()

# Paths are relative to the working directory: the repo root locally, /app in the image.
FIXTURES = Path("fixtures")
SAMPLE = Path("tests/data/stub_expected.json")
FIXTURE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class AnalyzeRequest(BaseModel):
    """From the Action (repo and both plans) or from a test or the Try-it page (fixture)."""

    fixture: str | None = None
    repo: str | None = None
    pr_number: int | None = None
    base_sha: str | None = None
    head_sha: str | None = None
    pr_title: str | None = None
    pr_body: str | None = None
    base_plan: dict[str, Any] | None = None
    head_plan: dict[str, Any] | None = None
    checkov: dict[str, Any] | None = None


class FindingRequest(BaseModel):
    fixture: str | None = None
    repo: str | None = None
    advisory: dict[str, Any] | None = None


class ScanRequest(BaseModel):
    fixture: str | None = None
    repo: str | None = None


def load_expected(name: str) -> dict[str, Any]:
    """The expected.json for a fixture name, or the sample. Refuses any name that is not a plain slug."""
    if not FIXTURE_NAME.match(name):
        raise HTTPException(400, f"not a fixture name: {name!r}")
    path = SAMPLE if name == "sample" else FIXTURES / name / "expected.json"
    if not path.is_file():
        raise HTTPException(404, f"no expected.json for fixture {name!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def stub_for(fixture: str | None, mode: str) -> AnalysisResult:
    if fixture is None:
        raise HTTPException(501, "only {fixture} requests are answered until the engine lands (E3, A5)")
    expected = load_expected(fixture)
    if expected.get("mode") != mode:
        raise HTTPException(400, f"fixture {fixture!r} is a {expected.get('mode')} scenario, not {mode}")
    log.info("stub result for fixture %s", fixture)
    return result_from_expected(expected)


@router.post("/analyze", response_model=AnalysisResult)
def analyze(req: AnalyzeRequest) -> AnalysisResult:
    """PR mode."""
    return stub_for(req.fixture, "pr")


@router.post("/finding", response_model=AnalysisResult)
def finding(req: FindingRequest) -> AnalysisResult:
    """Finding mode."""
    return stub_for(req.fixture, "finding")


@router.post("/scan", response_model=AnalysisResult)
def scan(req: ScanRequest) -> AnalysisResult:
    """Scan mode."""
    return stub_for(req.fixture, "scan")
