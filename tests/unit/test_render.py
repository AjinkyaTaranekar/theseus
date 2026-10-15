"""The PR comment (docs/spec/05-contracts.md, "The PR comment"), rendered from results like the engine's.

Snapshots live in tests/unit/snapshots/render/. After a deliberate change to the comment, regenerate them and
read the diff:

    UPDATE_SNAPSHOTS=1 pytest -q tests/unit/test_render.py
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from theseus.agent.render import (
    MARKER,
    MAX_CHARS,
    change_line,
    checkov_line,
    code,
    cut_sentence,
    escape,
    mermaid,
    pick_diagrams,
    render_comment,
)
from theseus.api.stub import result_from_expected
from theseus.contracts.result import (
    AnalysisResult,
    Candidate,
    Coverage,
    CutEdge,
    Evidence,
    Intent,
    MinCut,
    PathRecord,
    PathStep,
    ResourceChange,
    Timings,
    ToolCall,
)

REPO = "owner/theseus"
SHA = "0123456789abcdef0123456789abcdef01234567"
BLOB = f"https://github.com/{REPO}/blob/{SHA}/demo-infra/"
SNAPSHOTS = Path(__file__).with_name("snapshots") / "render"
FIXTURES = sorted(Path("fixtures").glob("*/expected.json"))

# Spec 05's intern example, word for word.
INTERN_EXPECTED: dict[str, Any] = {
    "scenario": "intern",
    "mode": "pr",
    "intent": {"grants": [["user:priya-intern", "read", "s3://demo-app-logs/"]], "suspicious": False},
    "opened": [
        {
            "actor": "user:priya-intern",
            "target": "db:customer-db",
            "route": [
                "user:priya-intern",
                "group:support-engineers",
                "role:prod-support",
                "secret:prod-db-credentials",
                "db:customer-db",
            ],
            "cites": [
                "terraform/people.tf:20",
                "terraform/people.tf:30",
                "terraform/roles.tf:31",
                "terraform/data.tf:12",
            ],
        }
    ],
    "closed": [],
    "requirements": {"R1": "satisfied", "R2": "satisfied", "R3": "satisfied", "I1": "satisfied"},
    "min_cut": {"cuttable": False, "value_at_least": 1000000},
    "candidates": {"A": "fail", "B": "pass", "C": "unknown", "D": "fail"},
    "recommended": "B",
    "rotate": [],
    "unused_grants": [],
    "use_beyond_intent": [],
    "staging_to_prod": [],
}

PRIYA = ["user:priya-intern", "group:support-engineers", "role:prod-support"]
EVIDENCE = {
    "E1": Evidence(
        address="aws_iam_user_group_membership.priya_support", file="terraform/people.tf", line=20
    ),
    "E2": Evidence(
        address="aws_iam_group_policy.support_assume",
        part="AssumeProdSupport",
        file="terraform/people.tf",
        line=30,
    ),
    "E3": Evidence(
        address="aws_iam_role_policy.prod_support_read",
        part="ReadDbSecret",
        file="terraform/roles.tf",
        line=31,
    ),
    "E4": Evidence(address="aws_secretsmanager_secret.prod_db", file="terraform/data.tf", line=12),
    "E5": Evidence(
        address="aws_iam_role_policy.prod_support_read",
        part="ReadInvoices",
        file="terraform/roles.tf",
        line=24,
    ),
    "E6": Evidence(address="inferred", file="unknown", note="the secret's db_instance tag"),
}


def path(n: int, target: str, sensitivity: str | None, *tail: tuple[str, str, str]) -> PathRecord:
    """Priya's route to the role, then the given (type, node, evidence) steps."""
    steps = [
        PathStep(src=PRIYA[0], type="MEMBER_OF", dst=PRIYA[1], evidence="E1"),
        PathStep(src=PRIYA[1], type="CAN_ASSUME", dst=PRIYA[2], evidence="E2"),
    ]
    node = PRIYA[2]
    for edge_type, dst, ev in tail:
        steps.append(PathStep(src=node, type=edge_type, dst=dst, evidence=ev))  # type: ignore[arg-type]
        node = dst
    return PathRecord(
        id=f"P{n}",
        actor=PRIYA[0],
        target=target,
        grants=["read"],
        steps=steps,
        sensitivity=sensitivity,  # type: ignore[arg-type]
    )


def candidate(cid: str, verdict: str, **extra: Any) -> Candidate:
    source = "llm" if cid == "B" else "rule"
    return Candidate(
        id=cid,
        source=source,  # type: ignore[arg-type]
        proposed_by="zai-org/GLM-5.3" if source == "llm" else "theseus",
        title=extra.pop("title", f"Fix {cid}"),
        verdict=verdict,  # type: ignore[arg-type]
        reason=extra.pop("reason", "checked on a graph copy"),
        **extra,
    )


def intern() -> AnalysisResult:
    """The intern scenario as the engine will report it: three opened paths, four fixes, one unknown."""
    db = path(
        1,
        "db:customer-db",
        "regulated",
        ("CAN", "secret:prod-db-credentials", "E3"),
        ("UNLOCKS", "db:customer-db", "E6"),
    )
    secret = path(2, "secret:prod-db-credentials", "regulated", ("CAN", "secret:prod-db-credentials", "E3"))
    invoices = path(
        3,
        "s3://demo-company-files/invoices/",
        "confidential",
        ("CAN", "s3://demo-company-files/invoices/", "E5"),
    )
    return AnalysisResult(
        scenario="intern",
        mode="pr",
        repo=REPO,
        pr_number=42,
        intent=Intent(purpose="Let Priya read the app logs.", grants=[]),
        changes=[
            ResourceChange(
                address="aws_iam_user_group_membership.priya_support",
                type="aws_iam_user_group_membership",
                action="create",
            )
        ],
        headline="Your PR says Priya reads the app logs. Your change grants db:customer-db.",
        opened=[db, secret, invoices],
        unchanged=[path(4, "s3://demo-app-logs/", "internal")],
        unknowns=["aws_kms_key.main: key policy conditions are not modeled"],
        min_cut=MinCut(sources=[PRIYA[0]], sinks=["db:customer-db"], value=1_000_000, cuttable=False, cut=[]),
        candidates=[
            candidate("A", "fail", requirements_broken=["I1"], title="Revert the membership"),
            candidate("B", "pass", recommended=True, title="A new support-logs-read role for Priya"),
            candidate(
                "C",
                "unknown",
                unknown=["Deny with a principal condition"],
                title="Deny Priya on prod-support",
            ),
            candidate(
                "D",
                "fail",
                paths_left=["P3"],
                requirements_broken=["R2", "R3"],
                title="Remove AssumeProdSupport",
            ),
        ],
        evidence=EVIDENCE,
        tool_trace=[
            ToolCall(
                tool="explain_path", input={"path": "P1"}, summary="P1: 5 hops to db:customer-db", ms=12
            ),
            ToolCall(tool="min_cut", input={}, summary="value 1000000, not cuttable", ms=48),
            ToolCall(tool="simulate_fix", input={"id": "B"}, summary="B passes", ms=310),
        ],
        timings=Timings(engine_ms=1240, llm_ms=8010, jev_ms=330, total_ms=9580),
        coverage=Coverage(
            resources=46,
            modeled=31,
            skipped_types={
                "aws_cloudwatch_metric_alarm": 6,
                "aws_sns_topic": 5,
                "aws_kms_alias": 2,
                "aws_ssm_parameter": 2,
            },
        ),
        models={"llm": "zai-org/GLM-5.3", "jev": "jev-1.13.0"},
    )


def render(result: AnalysisResult, checkov: dict[str, Any] | None = None) -> str:
    return render_comment(result, REPO, SHA, checkov=checkov)


def details(comment: str) -> str:
    return comment.split("<details>", 1)[1].split("</details>", 1)[0]


def matches_snapshot(name: str, text: str) -> None:
    snapshot = SNAPSHOTS / f"{name}.md"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(text, encoding="utf-8", newline="\n")
        return
    assert snapshot.is_file(), f"no snapshot {snapshot}; create it with UPDATE_SNAPSHOTS=1"
    assert text == snapshot.read_text(encoding="utf-8"), f"{name} changed; regenerate with UPDATE_SNAPSHOTS=1"


# Structure ------------------------------------------------------------------------------------------------


def test_the_marker_comes_first_and_the_sections_follow_in_spec_order() -> None:
    comment = render(intern(), {"passed": 52, "failed": 0, "skipped": 0, "checkov_version": "3.2.255"})
    assert comment.startswith(MARKER + "\n")
    order = [
        "Adds `aws_iam_user_group_membership.priya_support`",
        "Your PR says Priya reads the app logs",
        "| Actor | Target | Hops |",
        "```mermaid",
        "Checkov 3.2.255",
        "No single permission can be removed without breaking required access.",
        "| ID | Fix | Dangerous paths | Required access | Code calls | Verdict |",
        "Reply `/theseus apply B` to commit a fix.",
        "aws\\_kms\\_key",
        "<details>",
    ]
    positions = [comment.index(part) for part in order]
    assert positions == sorted(positions)
    assert comment.count(MARKER) == 1 and comment.count("<details>") == 1


def test_a_pr_with_nothing_opened_shows_no_paths_cut_or_fixes() -> None:
    result = intern().model_copy(
        update={
            "opened": [],
            "candidates": [],
            "min_cut": None,
            "headline": "This change matches its stated purpose.",
        }
    )
    comment = render(result)
    assert "Opens 0 dangerous paths, closes 0." in comment
    for absent in ("```mermaid", "| ID | Fix |", "/theseus apply", "No single permission"):
        assert absent not in comment


# What the change does -------------------------------------------------------------------------------------


def change(action: str, *names: str) -> list[ResourceChange]:
    return [ResourceChange(address=n, type=n.split(".")[0], action=action) for n in names]  # type: ignore[arg-type]


def test_the_change_line_names_what_is_added_updated_and_deleted() -> None:
    result = intern().model_copy(
        update={
            "changes": change("create", "aws_iam_role.a", "aws_iam_role.b")
            + change("update", "aws_iam_role_policy.c")
            + change(
                "delete",
                "aws_s3_bucket.d",
                "aws_s3_bucket.e",
                "aws_s3_bucket.f",
                "aws_s3_bucket.g",
                "aws_s3_bucket.h",
            ),
            "closed": [path(9, "s3://demo-app-logs/", "internal")],
        }
    )
    assert change_line(result) == (
        "Adds `aws_iam_role.a` and `aws_iam_role.b`; updates `aws_iam_role_policy.c`;"
        " deletes `aws_s3_bucket.d`,"
        " `aws_s3_bucket.e`, `aws_s3_bucket.f` and 2 more. Opens 3 dangerous paths, closes 1."
    )


def test_with_no_change_list_the_line_gives_only_the_counts() -> None:
    result = intern().model_copy(update={"changes": [], "opened": intern().opened[:1]})
    assert change_line(result) == "Opens 1 dangerous path, closes 0."


# Headline -------------------------------------------------------------------------------------------------


def test_a_suspicious_intent_gets_a_warning_after_the_headline() -> None:
    result = intern().model_copy(update={"intent": Intent(purpose="p", suspicious=True)})
    comment = render(result)
    warning = comment.index("tries to steer the review")
    assert comment.index("Your PR says") < warning < comment.index("| Actor |")
    assert "Warning" not in render(intern())


def test_the_unstated_headline_passes_through() -> None:
    headline = "This PR doesn't say what it's for. Your change grants db:customer-db."
    result = intern().model_copy(update={"headline": headline, "intent": Intent(purpose="", stated=False)})
    assert "This PR doesn't say what it's for. Your change grants db:customer-db." in render(result)


# Paths and diagrams -------------------------------------------------------------------------------------


def test_at_most_three_diagrams_the_most_sensitive_first() -> None:
    result = intern()
    extra = path(5, "secret:payments-api-key", "regulated", ("CAN", "secret:payments-api-key", "E3"))
    picked = pick_diagrams([*result.opened, extra])
    assert [p.id for p in picked] == ["P1", "P2", "P5"]  # the database before the secret that unlocks it
    comment = render(result.model_copy(update={"opened": [*result.opened, extra]}))
    assert comment.count("```mermaid") == 3


def test_mermaid_node_ids_are_plain_and_labels_cannot_break_the_block() -> None:
    hostile = path(7, 'db:"x"```', "regulated", ("CAN", 'db:"x"```', "E3"))
    block = mermaid(hostile)
    assert block.startswith("```mermaid\nflowchart LR\n") and block.endswith("\n```")
    body = block.removeprefix("```mermaid\n").removesuffix("\n```")
    assert "```" not in body and '"x"' not in body
    for line in body.splitlines()[1:]:
        assert re.match(
            r"^\s*(n\d+\[\".*\"\]|n\d+ -->\|[A-Z_]+\| n\d+|classDef \w+ .*|class n\d+ \w+)$", line
        ), line


def test_every_step_links_to_its_line_at_the_head_commit() -> None:
    comment = render(intern())
    links = re.findall(r"\]\((https://[^)]+)\)", comment)
    assert links and all(link.startswith(BLOB) for link in links)
    assert f"{BLOB}terraform/people.tf#L20" in links


def test_a_step_with_unknown_evidence_says_so_and_has_no_link() -> None:
    comment = render(intern())
    assert "unknown: the secret's db\\_instance tag" in comment
    assert "unknown](" not in comment


# Checkov and the cut ------------------------------------------------------------------------------------


def test_the_checkov_line_reads_its_summary_or_says_it_did_not_run() -> None:
    assert checkov_line({"passed": 52, "failed": 0, "skipped": 1, "checkov_version": "3.2.255"}) == (
        "Checkov 3.2.255 on this commit: 52 passed, 0 failed, 1 skipped."
    )
    assert checkov_line(None) == "Checkov did not run on this commit."


def test_the_cut_sentence_has_three_forms() -> None:
    assert cut_sentence(intern(), REPO, SHA, "demo-infra") == (
        "No single permission can be removed without breaking required access."
    )
    one = MinCut(
        sources=["workflow:demo-org/docs-site/preview.yml"],
        sinks=["db:customer-db"],
        value=1,
        cuttable=True,
        cut=[
            CutEdge(
                eid="e9",
                src="workflow:demo-org/docs-site/preview.yml",
                type="TRUSTS",
                dst="role:github-deploy",
                evidence="E1",
            )
        ],
    )
    sentence = cut_sentence(intern().model_copy(update={"min_cut": one}), REPO, SHA, "demo-infra")
    assert sentence.startswith(
        "One change closes every path: `workflow:demo-org/docs-site/preview.yml TRUSTS role:github-deploy`"
    )
    assert f"({BLOB}terraform/people.tf#L20)" in sentence
    two = one.model_copy(
        update={"value": 2, "cut": [*one.cut, one.cut[0].model_copy(update={"eid": "e10", "dst": "role:x"})]}
    )
    assert cut_sentence(intern().model_copy(update={"min_cut": two}), REPO, SHA, "demo-infra").startswith(
        "2 changes close every path:"
    )


# Fixes ----------------------------------------------------------------------------------------------------


def fix_rows(comment: str) -> list[str]:
    return [line for line in comment.splitlines() if re.match(r"^\| (\*\*)?[A-Z]\d*(\*\*)? \|", line)]


def test_the_fix_table_shows_every_candidate_with_the_recommended_row_bold() -> None:
    rows = fix_rows(render(intern()))
    assert [re.match(r"^\| (?:\*\*)?(\w+)", r).group(1) for r in rows] == ["A", "B", "C", "D"]  # type: ignore[union-attr]
    assert rows[1] == (
        "| **B** | **A new support-logs-read role for Priya (zai-org/GLM-5.3)** | **all closed** | **kept**"
        " | **kept** | **pass** |"
    )
    assert rows[0] == "| A | Revert the membership (rule) | all closed | breaks I1 | kept | fail |"
    assert rows[3] == "| D | Remove AssumeProdSupport (rule) | 1 left | breaks R2, R3 | kept | fail |"


def test_a_vetoed_pass_needs_a_closer_look_and_nothing_passing_is_said_plainly() -> None:
    vetoed = [
        c.model_copy(update={"recommended": False, "needs_closer_look": c.id == "B"})
        for c in intern().candidates
    ]
    comment = render(intern().model_copy(update={"candidates": vetoed}))
    assert "pass, needs a closer look" in comment
    assert not any("**" in r for r in fix_rows(comment))
    failing = [c.model_copy(update={"verdict": "fail", "recommended": False}) for c in intern().candidates]
    comment = render(intern().model_copy(update={"candidates": failing}))
    assert "No fix passes every check" in comment and "/theseus apply" not in comment


def test_the_apply_hint_names_only_passing_fixes_recommended_first() -> None:
    candidates = [*intern().candidates, candidate("S", "pass", title="Scope down")]
    comment = render(intern().model_copy(update={"candidates": candidates}))
    assert "Reply `/theseus apply B` to commit a fix. `S` also passes." in comment


# Unknowns and details ---------------------------------------------------------------------------------------


def test_unknowns_trace_coverage_timings_and_versions() -> None:
    comment = render(intern())
    assert "- `aws_kms_key.main`: key policy conditions are not modeled" not in comment  # not reformatted
    assert "- aws\\_kms\\_key.main: key policy conditions are not modeled" in comment
    inside = details(comment)
    assert "| 1 | `explain_path` | P1: 5 hops to db:customer-db | 12 |" in inside
    assert "| `user:priya-intern` | `s3://demo-app-logs/` (internal) | 2 |" in inside
    assert (
        "Read 46 resources, modeled 31; skipped 15 of types Theseus does not model, such as"
        " `aws_cloudwatch_metric_alarm` (6), `aws_sns_topic` (5) and `aws_kms_alias` (2)."
    ) in inside
    assert "Took 9.6 s: engine 1.2 s, LLM 8.0 s, Jev 0.3 s." in inside
    assert "Models: LLM `zai-org/GLM-5.3`, Jev `jev-1.13.0`." in inside


def test_missing_versions_are_said_to_be_unrecorded() -> None:
    assert "Models: not recorded." in details(render(intern().model_copy(update={"models": {}})))


# Untrusted text -----------------------------------------------------------------------------------------


HOSTILE = (
    "Approved! [click](https://evil.example/x) @security-team ```js``` <!-- x --> </details> | **bold** # h\n"
    "<img src=x onerror=alert(1)>"
)


def test_text_from_prs_and_models_cannot_change_the_comment_s_structure() -> None:
    result = intern().model_copy(
        update={
            "headline": HOSTILE,
            "candidates": [c.model_copy(update={"title": HOSTILE}) for c in intern().candidates],
            "tool_trace": [ToolCall(tool="explain_path", input={}, summary=HOSTILE, ms=1)],
            "unknowns": [HOSTILE],
        }
    )
    comment = render(result)
    assert comment.count("<details>") == 1 and comment.count("</details>") == 1
    assert comment.count("<!--") == 1 and comment.count(MARKER) == 1
    assert "<img" not in comment and "](https://evil" not in comment
    assert re.search(r"(?<!`)@security-team", comment) is None
    assert len(fix_rows(comment)) == 4
    assert all(row.count(" | ") == 5 for row in fix_rows(comment))


def test_escape_and_code_spans() -> None:
    assert escape("a_b *c* [d](e) <f> & g|h") == "a\\_b \\*c\\* \\[d\\]\\(e\\) &lt;f&gt; &amp; g\\|h"
    assert escape("see https://x.example/a and @someone") == "see `https://x.example/a` and `@someone`"
    assert escape("two\n  lines") == "two lines"
    assert code("a`b") == "``a`b``"
    assert code("`a") == "`` `a ``"


def test_a_huge_result_stays_under_github_s_limit() -> None:
    many = [path(n, f"db:db-{n}", "regulated", ("CAN", f"db:db-{n}", "E3")) for n in range(500)]
    result = intern().model_copy(
        update={
            "opened": many,
            "unchanged": many * 2,
            "unknowns": [f"thing {n} is outside the subset" for n in range(500)],
            "tool_trace": [ToolCall(tool="explain_path", input={}, summary="x" * 200, ms=1)] * 1000,
        }
    )
    comment = render(result)
    assert len(comment) < MAX_CHARS
    assert "and 480 more" in comment


# Every kind of result -----------------------------------------------------------------------------------


def test_spec_05_s_intern_example_renders_through_the_stub() -> None:
    comment = render(result_from_expected(INTERN_EXPECTED))
    assert comment.count("```mermaid") == 1 and len(fix_rows(comment)) == 4
    assert f"{BLOB}terraform/roles.tf#L31" in comment


def test_finding_and_scan_results_render() -> None:
    finding = AnalysisResult(
        mode="finding",
        headline="GHSA-demo-0001 reaches db:customer-db.",
        rotate=["secret:prod-db-credentials"],
    )
    scan = AnalysisResult(mode="scan", headline="1 grant is never called.")
    for result in (finding, scan):
        comment = render(result)
        assert comment.startswith(MARKER) and "Opens" not in comment


SNAPSHOT_CASES = {
    "intern": lambda: intern(),
    "unstated": lambda: intern().model_copy(
        update={
            "intent": Intent(purpose="", stated=False),
            "headline": "This PR doesn't say what it's for. Your change grants db:customer-db.",
        }
    ),
    "suspicious": lambda: intern().model_copy(
        update={"intent": Intent(purpose="Publish previews.", suspicious=True)}
    ),
    "nothing-opened": lambda: intern().model_copy(
        update={
            "opened": [],
            "candidates": [],
            "min_cut": None,
            "unknowns": [],
            "headline": "This change matches its stated purpose.",
        }
    ),
    "finding": lambda: AnalysisResult(
        mode="finding", headline="GHSA-demo-0001 reaches db:customer-db.", models={"jev": "jev-1.13.0"}
    ),
}


@pytest.mark.parametrize("name", sorted(SNAPSHOT_CASES))
def test_the_comment_matches_its_snapshot(name: str) -> None:
    matches_snapshot(
        name,
        render(
            SNAPSHOT_CASES[name](), {"passed": 52, "failed": 0, "skipped": 0, "checkov_version": "3.2.255"}
        ),
    )


@pytest.mark.parametrize("expected", FIXTURES, ids=lambda p: p.parent.name)
def test_every_fixture_renders(expected: Path) -> None:
    comment = render(result_from_expected(json.loads(expected.read_text(encoding="utf-8"))))
    assert comment.startswith(MARKER) and len(comment) < MAX_CHARS
    matches_snapshot(f"fixture-{expected.parent.name}", comment)
