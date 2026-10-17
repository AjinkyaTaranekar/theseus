from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from theseus import cli
from theseus.cli import main
from theseus.config import get_settings
from theseus.errors import GraphError, TheseusError
from theseus.graph.store import MemoryStore

COMMANDS = ("analyze", "finding", "scan", "posture", "serve")


def test_help_lists_every_command() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "theseus", "--help"], capture_output=True, text=True, check=True
    )
    for command in COMMANDS:
        assert command in out.stdout


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


def test_analyze_refuses_to_run_without_falkordb(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unreachable(settings: object) -> None:
        raise GraphError("cannot reach FalkorDB at example:1")

    monkeypatch.setattr(cli, "get_client", unreachable)
    assert main(["analyze", "fixtures/intern"]) == 1
    assert "cannot reach FalkorDB" in capsys.readouterr().err


def test_analyze_reads_a_pr_fixture_through_the_real_adapters() -> None:
    from pathlib import Path

    from tests.golden.conftest import RecordedJev
    from theseus.config import get_settings
    from theseus.graph.store import MemoryStore

    store = MemoryStore()
    result = cli.analyze_fixture(Path("fixtures/intern"), store, RecordedJev(), get_settings())
    assert result.scenario == "intern" and result.graphs == {
        "base": "fx__intern__base",
        "head": "fx__intern__head",
    }
    assert store.list_graphs() == [
        "fx__intern__base",
        "fx__intern__fix-a",
        "fx__intern__fix-c",
        "fx__intern__fix-d",
        "fx__intern__head",
    ]
    assert {c.id for c in result.candidates} == {"A", "C", "D"}
    assert sorted(p.target for p in result.opened) == [
        "db:customer-db",
        "s3://demo-company-files/invoices/",
        "secret:prod-db-credentials",
    ]


def test_analyze_refuses_a_fixture_that_is_not_a_pr() -> None:
    from pathlib import Path

    from theseus.config import get_settings
    from theseus.errors import TheseusError
    from theseus.graph.store import MemoryStore

    with pytest.raises(TheseusError, match="'scan' fixture"):
        cli.analyze_fixture(Path("fixtures/unused-grant"), MemoryStore(), None, get_settings())


def test_finding_refuses_to_run_without_falkordb(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unreachable(settings: object) -> None:
        raise GraphError("cannot reach FalkorDB at example:1")

    monkeypatch.setattr(cli, "get_client", unreachable)
    assert main(["finding", "fixtures/compromised-action"]) == 1
    assert "cannot reach FalkorDB" in capsys.readouterr().err


def test_finding_reads_a_finding_fixture_through_the_real_adapters() -> None:
    from tests.golden.conftest import RecordedJev

    result = cli.finding_fixture(
        Path("fixtures/compromised-action"), MemoryStore(), RecordedJev(), get_settings()
    )
    assert result.mode == "finding"
    assert result.rotate == ["secret:prod-db-credentials"]


def test_finding_refuses_a_fixture_that_is_not_a_finding() -> None:
    with pytest.raises(TheseusError, match="finding reads finding fixtures"):
        cli.finding_fixture(Path("fixtures/intern"), MemoryStore(), None, get_settings())


def test_scan_refuses_to_run_without_falkordb(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unreachable(settings: object) -> None:
        raise GraphError("cannot reach FalkorDB at example:1")

    monkeypatch.setattr(cli, "get_client", unreachable)
    assert main(["scan", "fixtures/unused-grant"]) == 1
    assert "cannot reach FalkorDB" in capsys.readouterr().err


def test_scan_reads_a_scan_fixture_through_the_real_adapters() -> None:
    from pathlib import Path

    from tests.golden.conftest import RecordedJev
    from theseus.config import get_settings
    from theseus.graph.store import MemoryStore

    store = MemoryStore()
    result = cli.scan_fixture(Path("fixtures/unused-grant"), store, RecordedJev(), get_settings())
    assert result.mode == "scan" and result.graphs == {"main": "fx__unused-grant__main"}
    assert [(g.workload, g.resource, g.access) for g in result.unused_grants] == [
        ("workload:support-portal", "secret:prod-db-credentials", "read")
    ]
    assert [(c.id, c.verdict) for c in result.candidates] == [("U", "pass")]


def test_scan_refuses_a_fixture_that_is_not_a_scan() -> None:
    from pathlib import Path

    from theseus.config import get_settings
    from theseus.errors import TheseusError
    from theseus.graph.store import MemoryStore

    with pytest.raises(TheseusError, match="'pr' fixture"):
        cli.scan_fixture(Path("fixtures/intern"), MemoryStore(), None, get_settings())


def test_posture_refuses_to_run_without_falkordb(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unreachable(settings: object) -> None:
        raise GraphError("cannot reach FalkorDB at example:1")

    monkeypatch.setattr(cli, "get_client", unreachable)
    assert main(["posture", "fixtures/unused-grant/base", "fixtures/unused-grant/base.plan.json"]) == 1
    assert "cannot reach FalkorDB" in capsys.readouterr().err


def test_posture_reads_a_world_and_raises_the_advisory_s_finding() -> None:
    from tests.golden.conftest import RecordedJev

    advisories = cli.load_advisories(Path("advisories"))
    report = cli.posture_world(
        Path("fixtures/unused-grant/base"),
        Path("fixtures/unused-grant/base.plan.json"),
        MemoryStore(),
        RecordedJev(),
        get_settings(),
        advisories,
    )
    assert [(f.finding or {})["id"] for f in report.findings] == ["GHSA-demo-0001"]
    assert report.posture.reach and report.posture.cost.monthly_usd > 0


def test_a_bad_advisory_file_is_skipped_and_the_rest_are_read(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text('{"id": "GHSA-1", "action": "o/a", "affected_versions": ["v1"]}')
    (tmp_path / "b.json").write_text("not json")
    (tmp_path / "c.json").write_text('{"id": "GHSA-3"}')
    assert [a["id"] for a in cli.load_advisories(tmp_path)] == ["GHSA-1"]
    assert cli.load_advisories(tmp_path / "missing") == []
