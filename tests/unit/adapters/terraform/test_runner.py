"""Planning a Terraform root from Python as tools/plan.sh does (adapters/terraform/runner.py), with Terraform
itself stood in for: the commands, the isolated environment, the cache and the failures."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from theseus.adapters.terraform import runner
from theseus.errors import IngestError

PLAN = {"format_version": "1.2", "planned_values": {"root_module": {}}}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    tf = tmp_path / "terraform"
    tf.mkdir()
    (tf / "main.tf").write_text('resource "aws_iam_group" "g" { name = "g" }\n', encoding="utf-8")
    (tf / "notes.txt").write_text("not configuration\n", encoding="utf-8")
    return tf


class FakeTerraform:
    """Records each command and its environment; `show` prints the plan."""

    def __init__(self, fail: str | None = None) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.fail = fail

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((args, kwargs["env"]))
        verb = args[2]
        if verb == self.fail:
            return subprocess.CompletedProcess(args, 1, "", "line 1\nError: No valid credential sources\n")
        out = json.dumps(PLAN) if verb == "show" else ""
        return subprocess.CompletedProcess(args, 0, out, "")


def test_it_plans_a_copy_with_the_three_commands_plan_sh_runs(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeTerraform()
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setenv("AWS_PROFILE", "someone")
    assert runner.plan_json(root, tmp_path / "cache") == PLAN
    verbs = [args[2] for args, _ in fake.calls]
    assert verbs == ["init", "plan", "show"]
    args, env = fake.calls[1]
    assert args[1].startswith("-chdir=") and "-refresh=false" in args and "-out=tfplan" in args
    work = Path(args[1].removeprefix("-chdir="))
    assert work != root and sorted(p.name for p in work.iterdir() if p.suffix == ".tf") == ["main.tf"]
    assert "AWS_PROFILE" not in env and env["AWS_EC2_METADATA_DISABLED"] == "true"
    assert env["TF_DATA_DIR"] == str(tmp_path / "cache" / "terraform")  # providers install once


def test_the_same_configuration_is_planned_once(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeTerraform()
    monkeypatch.setattr(subprocess, "run", fake)
    runner.plan_json(root, tmp_path / "cache")
    assert runner.plan_json(root, tmp_path / "cache") == PLAN
    assert len(fake.calls) == 3
    (root / "main.tf").write_text('resource "aws_iam_group" "h" { name = "h" }\n', encoding="utf-8")
    runner.plan_json(root, tmp_path / "cache")
    assert len(fake.calls) == 6  # a changed file is a new plan


def test_a_failed_command_says_which_and_why(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", FakeTerraform(fail="plan"))
    with pytest.raises(IngestError, match=r"(?s)terraform plan failed:\n.*No valid credential sources"):
        runner.plan_json(root, tmp_path / "cache")
    assert not list((tmp_path / "cache").glob("*.plan.json"))


def test_no_terraform_or_no_configuration_is_an_ingest_error(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(args: list[str], **kwargs: Any) -> None:
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(IngestError, match="not installed"):
        runner.plan_json(root, tmp_path / "cache")
    with pytest.raises(IngestError, match="no Terraform configuration"):
        runner.plan_json(tmp_path / "empty", tmp_path / "cache")
