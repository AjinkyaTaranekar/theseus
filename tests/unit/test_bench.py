"""Benchmark truth stays human-owned and tool failures never turn into catches."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from bench.checkov import CheckovReport, compare_reports, parse_report, scan
from bench.run import OwnedStore, evaluate, read_case, render_report
from bench.scale import build_world, measure
from theseus.cli import adapters_for
from theseus.contracts.result import AnalysisResult, GraphRows, PathRecord
from theseus.engine.analyze import analyze
from theseus.engine.mincut import capacities
from theseus.engine.simulate import simulate
from theseus.errors import GraphError, IngestError
from theseus.graph.load import load_graph
from theseus.graph.store import MemoryStore


def checkov_json(failed: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    failed = [] if failed is None else failed
    return {
        "check_type": "terraform",
        "results": {"failed_checks": failed, "passed_checks": [], "skipped_checks": []},
        "summary": {"passed": 0, "failed": len(failed), "skipped": 0, "parsing_errors": 0},
    }


def finding(check: str, address: str, line: int = 1) -> dict[str, Any]:
    return {"check_id": check, "resource": address, "file_path": "/main.tf", "file_line_range": [line, line]}


def test_checkov_accepts_one_or_multiple_reports_and_ignores_line_moves() -> None:
    before = parse_report(json.dumps(checkov_json([finding("CKV_AWS_1", "aws_x.a")])), 1)
    after = parse_report(json.dumps([checkov_json([finding("CKV_AWS_1", "aws_x.a", 20)])]), 1)
    assert before.failed == after.failed == 1
    assert compare_reports(before, after).introduced == []


@pytest.mark.parametrize("raw,code", [("", 0), ("not-json", 1), ("{}", 0), ("[]", 0), ("null", 0)])
def test_checkov_rejects_missing_or_malformed_output(raw: str, code: int) -> None:
    with pytest.raises(IngestError):
        parse_report(raw, code)


def test_checkov_error_exit_and_parse_errors_are_not_policy_failures() -> None:
    for raw, code in [(checkov_json(), 2), (checkov_json(), 1)]:
        with pytest.raises(IngestError):
            parse_report(json.dumps(raw), code)
    raw = checkov_json()
    raw["summary"]["parsing_errors"] = 1
    with pytest.raises(IngestError, match="pars"):
        parse_report(json.dumps(raw), 0)


def test_checkov_summary_must_agree_with_findings() -> None:
    raw = checkov_json([finding("CKV_AWS_1", "aws_x.a")])
    raw["summary"]["failed"] = 0
    with pytest.raises(IngestError):
        parse_report(json.dumps(raw), 0)


def test_checkov_scans_without_shell_or_external_module_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert args[0] == "checkov"
        assert "--quiet" not in args  # Checkov 3.3.29 omits passed/skipped JSON records with --quiet.
        assert "--download-external-modules" in args
        assert args[args.index("--download-external-modules") + 1] == "false"
        assert kwargs.get("shell", False) is False
        assert kwargs["timeout"] == 7
        return subprocess.CompletedProcess(args, 0, json.dumps(checkov_json()), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert scan(tmp_path, timeout=7).failed == 0


def test_checkov_timeout_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def run(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired("checkov", 1)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(IngestError, match="timed out"):
        scan(tmp_path)


def test_owned_store_refuses_to_replace_existing_graphs_and_cleans_its_copies() -> None:
    backing = MemoryStore()
    backing.load("s2__old", GraphRows())
    scoped = OwnedStore(backing, "s2__")
    with pytest.raises(GraphError, match="existing"):
        scoped.load("s2__old", GraphRows())
    scoped.load("s2__new", GraphRows())
    scoped.copy("s2__new", "s2__copy")
    with pytest.raises(GraphError):
        scoped.copy("s2__old", "s2__unauthorized")
    with pytest.raises(GraphError):
        scoped.load("demo-infra__main", GraphRows())
    with pytest.raises(GraphError):
        scoped.max_flow("s2__old", [], [], [])
    with pytest.raises(GraphError):
        scoped.put_doc("review", "must not write product documents")
    scoped.cleanup()
    assert backing.list_graphs() == ["s2__old"]


def test_owned_store_does_not_hide_cleanup_failure() -> None:
    class CannotDelete(MemoryStore):
        def delete(self, graph: str) -> None:
            raise GraphError("deletion unavailable")

    backing = CannotDelete()
    scoped = OwnedStore(backing, "s2__")
    scoped.load("s2__new", GraphRows())
    with pytest.raises(GraphError, match="cleanup"):
        scoped.cleanup()


def test_case_requires_nonempty_human_key_and_both_plans(tmp_path: Path) -> None:
    tmp_path = tmp_path / "case"
    tmp_path.mkdir()
    (tmp_path / "scenario.yaml").write_text("name: case\nmode: pr\nworld: demo-infra\n")
    with pytest.raises(IngestError, match="expected.json"):
        read_case(tmp_path)
    (tmp_path / "expected.json").write_text("{}")
    with pytest.raises(IngestError, match="empty"):
        read_case(tmp_path)
    (tmp_path / "expected.json").write_text('{"opened": []}')
    with pytest.raises(IngestError, match="base"):
        read_case(tmp_path)


def test_evaluation_compares_all_key_fields_and_preserves_uncertainty() -> None:
    result = AnalysisResult(
        mode="pr",
        headline="actual",
        opened=[
            PathRecord(id="p1", actor="user:a", target="secret:b", unknown=True, grants=["read"], steps=[])
        ],
        unknowns=["conditional policy"],
    )
    observation = evaluate(result, {"headline": "human headline", "opened": []})
    assert not observation.matches
    assert observation.certain_paths == 0 and observation.unknown_paths == 1
    assert any("headline" in difference for difference in observation.differences)
    assert observation.product_verdict == "blocked"


def test_report_does_not_claim_checkov_relevance_or_turn_missing_data_into_pass() -> None:
    observation = evaluate(AnalysisResult(mode="pr"), {"opened": [], "use_beyond_intent": []})
    report = render_report([("unsafe|name\nextra", observation, None, "Checkov unavailable")])
    assert "Checkov unavailable" in report and "unavailable" in report
    assert "human review" in report
    assert "unsafe|name\nextra" not in report


def test_scale_world_is_exact_deterministic_and_rebuildable(tmp_path: Path) -> None:
    state, draft, requirements = build_world(tmp_path, 20)
    other, _, _ = build_world(tmp_path, 20)
    assert state == other
    assert len(state.rows.edges) == 20
    assert all(edge.evidence for edge in state.rows.edges)
    assert not state.rows.unknowns
    store = MemoryStore()
    load_graph(store, state)
    actors = ["user:scale-reader"]
    analysis = analyze(store, state, requirements, actors)
    assert len(analysis.dangerous) == 16
    assert all(status.status == "satisfied" for status in analysis.requirements)
    caps = capacities(state.rows, analysis, requirements)
    sinks = sorted({path.target for path in analysis.dangerous})
    assert store.max_flow(state.name, actors, sinks, caps).value == 16
    before = store.view(state.name)
    candidate = simulate(store, state, draft, actors, requirements, adapters_for(tmp_path))
    assert candidate.verdict == "pass"
    assert store.view(state.name) == before


def test_measure_discards_warmup_validates_all_samples_and_uses_median() -> None:
    ticks = iter([0, 9, 20, 25, 30, 31, 40, 43, 50, 52, 60, 64])
    observed: list[int] = []
    counter = iter(range(6))
    got = measure(lambda: next(counter), observed.append, clock=lambda: next(ticks))
    assert observed == list(range(6))
    assert got.samples_ns == [5, 1, 3, 2, 4]
    assert got.median_ms == 3 / 1_000_000


def test_generation_has_twenty_independent_specs_and_preserves_human_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bench.run import case_specs, generate_case

    specs = case_specs()
    assert len(specs) == 20 and len({spec.id for spec in specs}) == 20
    source = Path(__file__).resolve().parents[2] / "demo-infra"
    target = tmp_path / specs[0].id
    target.mkdir()
    key = target / "expected.json"
    key.write_bytes(b"human-owned sentinel\n")
    planned: list[str] = []

    def plan(root: Path, output: Path, *, bash: str) -> None:
        planned.append(root.name)
        output.write_text("generated by fake plan tool")

    monkeypatch.setattr("bench.run.plan_world", plan)
    generate_case(specs[0], source, tmp_path, bash="bash")
    assert planned == ["base", "head"]
    assert key.read_bytes() == b"human-owned sentinel\n"
    assert "priya_support" in (target / "head/terraform/people.tf").read_text()
    assert "priya_support" not in (target / "base/terraform/people.tf").read_text()


def test_all_case_edits_apply_once_to_the_pinned_demo(tmp_path: Path) -> None:
    import ast
    import shutil

    import hcl2

    from bench.run import case_specs
    from tools.make_fixture import COPY_IGNORE, apply_changes

    source = Path(__file__).resolve().parents[2] / "demo-infra"
    for spec in case_specs():
        head = tmp_path / spec.id
        shutil.copytree(source, head, ignore=COPY_IGNORE)
        apply_changes(spec.scenario, head)
        for path in (head / "terraform").glob("*.tf"):
            hcl2.loads(path.read_text())
        for path in (head / "services").rglob("*.py"):
            ast.parse(path.read_text())


def test_checkov_new_findings_are_sorted_and_not_lost() -> None:
    before = CheckovReport()
    after = parse_report(json.dumps(checkov_json([finding("B", "r.b"), finding("A", "r.a")])), 1)
    assert [(f.check_id, f.resource) for f in compare_reports(before, after).introduced] == [
        ("A", "r.a"),
        ("B", "r.b"),
    ]


def test_report_keeps_all_rows_together_before_differences() -> None:
    wrong = evaluate(AnalysisResult(mode="pr", headline="actual"), {"headline": "wanted"})
    report = render_report([("b", wrong, None, ""), ("a", wrong, None, "")])
    assert report.index("| a |") < report.index("| b |") < report.index("Differences for a")


def test_generation_failure_leaves_previous_inputs_and_key_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bench.run import case_specs, generate_case

    spec = case_specs()[0]
    target = tmp_path / spec.id
    target.mkdir()
    (target / "pr.md").write_text("previous input")
    (target / "expected.json").write_text("human-owned key")

    def fail(*args: Any, **kwargs: Any) -> None:
        raise IngestError("plan failed")

    monkeypatch.setattr("bench.run.plan_world", fail)
    with pytest.raises(IngestError, match="plan failed"):
        generate_case(spec, Path(__file__).resolve().parents[2] / "demo-infra", tmp_path, bash="bash")
    assert (target / "pr.md").read_text() == "previous input"
    assert (target / "expected.json").read_text() == "human-owned key"
    assert sorted(p.name for p in tmp_path.iterdir()) == [spec.id]


def test_generation_preserves_recovery_files_after_a_failed_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bench.run import case_specs, generate_case
    from tools.make_fixture import _RecoveryError

    def plan(root: Path, output: Path, *, bash: str) -> None:
        output.write_text("fake plan tool output")

    def fail(staging: Path, target: Path) -> None:
        (staging / "recovery-marker").write_text("preserve me")
        raise _RecoveryError("rollback failed; preserve staging")

    monkeypatch.setattr("bench.run.plan_world", plan)
    monkeypatch.setattr("bench.run._publish", fail)
    with pytest.raises(_RecoveryError):
        generate_case(
            case_specs()[0], Path(__file__).resolve().parents[2] / "demo-infra", tmp_path, bash="bash"
        )
    assert len(list(tmp_path.glob(".01-intern-membership-*/recovery-marker"))) == 1


def test_scale_checks_all_operations_and_cleans_every_graph(tmp_path: Path) -> None:
    from bench.scale import run_scale

    store = MemoryStore()
    store.load("demo-infra__main", GraphRows())
    result = run_scale(store, tmp_path, 20)
    assert result.edges == 20 and result.routes == 17 and result.sinks == 16
    assert set(result.measurements) == {"paths", "copy", "max_flow_with_setup", "simulation"}
    assert all(len(timing.samples_ns) == 5 for timing in result.measurements.values())
    assert store.list_graphs() == ["demo-infra__main"]


def test_scale_does_not_turn_a_database_error_into_a_fallback_timing(tmp_path: Path) -> None:
    from bench.scale import run_scale

    class FailsMaxFlow(MemoryStore):
        def max_flow(self, *args: Any, **kwargs: Any) -> Any:
            raise GraphError("database algorithm failed")

    store = FailsMaxFlow()
    with pytest.raises(GraphError, match="database algorithm failed"):
        run_scale(store, tmp_path, 20)
    assert store.list_graphs() == []


def test_runner_exposes_missing_recordings_and_preserves_existing_graphs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bench.run import run_case
    from theseus.config import Settings

    monkeypatch.setattr("bench.run.scan", lambda root: CheckovReport())
    root = Path(__file__).resolve().parents[2]
    case = read_case(root / "fixtures/intern")
    store = MemoryStore()
    store.load("demo-infra__main", GraphRows())
    record = run_case(case, store, Settings(theseus_mode="live"), tmp_path / "missing-recordings")
    assert record.result is None and record.errors
    assert any("recording" in error for error in record.errors)
    assert store.list_graphs() == ["demo-infra__main"]


def test_optional_fixer_model_errors_remain_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.run import AuditedLlm
    from theseus.agent.llm import Llm
    from theseus.config import Settings
    from theseus.errors import ModelError

    def fail(*args: Any, **kwargs: Any) -> None:
        raise ModelError("no fix recording")

    llm = Llm(Settings(theseus_mode="replay"))
    monkeypatch.setattr(llm, "call", fail)
    audit = AuditedLlm(llm)
    with pytest.raises(ModelError):
        audit.call("fix", [])
    assert audit.errors == ["fix: no fix recording"]


def test_record_command_requires_explicit_model_call_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.run import main

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("recording without explicit opt-in must not connect")

    monkeypatch.setattr("bench.run.get_client", forbidden)
    assert main(["record"]) == 1


@pytest.mark.parametrize("record_models", [False, True])
def test_runner_only_enables_recording_when_explicitly_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_models: bool
) -> None:
    from bench.run import run_case
    from theseus.config import Settings

    def pipeline(base: Any, head: Any, title: str, body: str, deps: Any) -> AnalysisResult:
        assert deps.settings.theseus_mode == ("record" if record_models else "replay")
        assert deps.llm.llm.mode == deps.settings.theseus_mode
        return AnalysisResult(mode="pr")

    monkeypatch.setattr("bench.run.run_pr", pipeline)
    monkeypatch.setattr("bench.run.scan", lambda root: CheckovReport())
    case = read_case(Path(__file__).resolve().parents[2] / "fixtures/intern")
    record = run_case(
        case, MemoryStore(), Settings(theseus_mode="live"), tmp_path, record_models=record_models
    )
    assert record.provenance["model_mode"] == ("record" if record_models else "replay")
