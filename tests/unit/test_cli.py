from __future__ import annotations

import subprocess
import sys

import pytest

from theseus import cli
from theseus.cli import main
from theseus.errors import GraphError

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
    ],
)
def test_unbuilt_commands_exit_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 2
    assert "not implemented yet" in capsys.readouterr().err


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_serve_refuses_to_start_without_falkordb(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unreachable(settings: object) -> None:
        raise GraphError("cannot reach FalkorDB at example:1")

    monkeypatch.setattr(cli, "get_client", unreachable)
    assert main(["serve"]) == 1
    assert "cannot reach FalkorDB" in capsys.readouterr().err


def test_serve_starts_the_api_when_falkordb_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    started: dict[str, object] = {}
    monkeypatch.setattr(cli, "get_client", lambda settings: object())
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: started.update(app=app, **kw))
    assert main(["serve"]) == 0
    assert started == {"app": "theseus.api.app:app", "host": "127.0.0.1", "port": 8000}
