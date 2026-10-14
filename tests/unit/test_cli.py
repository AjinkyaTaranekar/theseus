from __future__ import annotations

import subprocess
import sys

import pytest

from theseus.cli import main

COMMANDS = ("analyze", "finding", "scan", "serve")


def test_help_lists_the_four_commands() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "theseus", "--help"], capture_output=True, text=True, check=True
    )
    for command in COMMANDS:
        assert command in out.stdout


@pytest.mark.parametrize(
    "argv",
    [
        ["analyze", "fixtures/intern"],
        ["finding", "fixtures/compromised-action"],
        ["scan", "fixtures/unused-grant"],
        ["serve"],
    ],
)
def test_unbuilt_commands_exit_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 2
    assert "not implemented yet" in capsys.readouterr().err


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
