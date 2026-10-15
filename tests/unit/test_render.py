"""The PR comment (docs/spec/05-contracts.md, "The PR comment"), rendered from results like the engine's.

The comment is a card in plain words on top, then folded sections. Snapshots live in
tests/unit/snapshots/render/. After a deliberate change to the comment, regenerate them and read the diff:

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
    at_risk,
    change_line,
    checkov_line,
    code,
    cut_sentence,
    escape,
    mermaid,
    pick_diagrams,
    render_comment,
    story,
    verdict,
    what_happened,
    what_pr_says,
    what_to_do,
)
from theseus.api.stub import result_from_expected
from theseus.contracts.result import (
    AnalysisResult,
    BeyondIntent,
    Candidate,
    Coverage,
    CutEdge,
    Evidence,
    Grant,
    Intent,
    MinCut,
    NodeInfo,
    PathRecord,
    PathStep,
    ResourceChange,
    Timings,
    ToolCall,
)

REPO = "owner/theseus"
SHA = "0123456789abcdef0123456789abcdef01234567"
BLOB = f"https://github.com/{REPO}/blob/{SHA}/demo-infra/"
CHECKOV = {"passed": 52, "failed": 0, "skipped": 0, "checkov_version": "3.2.255"}
SNAPSHOTS = Path(__file__).with_name("snapshots") / "render"
FIXTURES = sorted(Path("fixtures").glob("*/expected.json"))
BR = "\\\n"  # a backslash, then a newline

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
    "E2": Evidence(address="aws_iam_group_policy.support_assume", file="terraform/people.tf", line=30),
    "E3": Evidence(address="aws_iam_role_policy.prod_support_read", file="terraform/roles.tf", line=31),
    "E4": Evidence(address="aws_secretsmanager_secret.prod_db", file="terraform/data.tf", line=12),
    "E5": Evidence(address="aws_iam_role_policy.prod_support_read", file="terraform/roles.tf", line=24),
    "E6": Evidence(address="inferred", file="unknown", note="the secret's db_instance tag"),
}
NODES = {
    "db:customer-db": NodeInfo(category="Database", sensitivity="regulated"),
    "secret:prod-db-credentials": NodeInfo(category="Secret", sensitivity="regulated"),
    "secret:payments-api-key": NodeInfo(category="Secret", sensitivity="regulated"),
    "s3://demo-company-files/invoices/": NodeInfo(category="ObjectStorage", sensitivity="confidential"),
    "s3://demo-app-logs/": NodeInfo(category="ObjectStorage", sensitivity="internal"),
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


DB = ("CAN", "secret:prod-db-credentials", "E3"), ("UNLOCKS", "db:customer-db", "E6")


def intern() -> AnalysisResult:
    """The intern scenario as the engine will report it: three opened paths, four fixes, one unknown."""
    db = path(1, "db:customer-db", "regulated", *DB)
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
        intent=Intent(
            purpose="Let Priya read the app logs.",
            grants=[Grant(principal=PRIYA[0], access="read", resource="s3://demo-app-logs/")],
        ),
        changes=[
            ResourceChange(
                address="aws_iam_user_group_membership.priya_support",
                type="aws_iam_user_group_membership",
                action="create",
            )
        ],
        headline=(
            "Your PR says it lets Priya read the app logs."
            " Your change also lets priya-intern reach customer-db."
        ),
        opened=[db, secret, invoices],
        unchanged=[path(4, "s3://demo-app-logs/", "internal")],
        unknowns=["aws_kms_key.main: key policy conditions are not modeled"],
        min_cut=MinCut(sources=[PRIYA[0]], sinks=["db:customer-db"], value=1_000_000, cuttable=False, cut=[]),
        candidates=[
            candidate("A", "fail", requirements_broken=["I1"], title="Revert the membership"),
            candidate("B", "pass", recommended=True, title="A new support-logs-read role for Priya"),
            candidate(
                "C", "unknown", unknown=["a Deny with a condition"], title="Deny Priya on prod-support"
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
        nodes=NODES,
    )


def code_pr() -> AnalysisResult:
    """A code change that starts reading the customer database, with no IAM change and no fix to test."""
    return AnalysisResult(
        scenario="code-pr",
        mode="pr",
        intent=Intent(purpose="Fix a typo on the support page.", grants=[]),
        headline="Your PR says: fix a typo. Your code now reads customer-db.",
        use_beyond_intent=[
            BeyondIntent(
                workload="workload:billing-api",
                resource="db:customer-db",
                access="read",
                file="services/billing_api/app.py",
                line=12,
            )
        ],
        nodes=NODES,
    )


def needs_a_look() -> AnalysisResult:
    return AnalysisResult(
        mode="pr",
        intent=Intent(purpose="Rotate the KMS key."),
        headline="This change matches its stated purpose.",
        unknowns=["aws_kms_key.main: key policy conditions are not modeled"],
    )


def render(result: AnalysisResult, checkov: dict[str, Any] | None = CHECKOV) -> str:
    return render_comment(result, REPO, SHA, checkov=checkov)


def card(comment: str) -> str:
    """Everything a reader sees before opening anything."""
    return comment.split("<details>", 1)[0]


def folded(comment: str, title: str) -> str:
    """The body of the folded section whose summary starts with `title`."""
    start = comment.index(f"<summary><b>{title}")
    return comment[start : comment.index("</details>", start)]


def matches_snapshot(name: str, text: str) -> None:
    snapshot = SNAPSHOTS / f"{name}.md"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(text, encoding="utf-8", newline="\n")
        return
    assert snapshot.is_file(), f"no snapshot {snapshot}; create it with UPDATE_SNAPSHOTS=1"
    assert text == snapshot.read_text(encoding="utf-8"), f"{name} changed; regenerate with UPDATE_SNAPSHOTS=1"


# The layout -------------------------------------------------------------------------------------------------


def test_the_card_comes_first_and_the_sections_follow_in_spec_order() -> None:
    comment = render(intern())
    assert comment.startswith(MARKER + "\n## 🔴 Merge blocked\n")
    order = [
        "**Your PR says it lets Priya read the app logs.",
        "#### What happened",
        "#### What's at risk",
        "#### What the PR said it needs",
        "#### What to do",
        "Checkov 3.2.255 passed this commit",
        "<summary><b>The path, step by step</b> (3 ways in",
        "<summary><b>All 4 fixes Theseus tested</b>",
        "<summary><b>What Theseus could not check</b> (1)",
        "<summary><b>Technical details</b>",
    ]
    positions = [comment.index(part) for part in order]
    assert positions == sorted(positions)
    assert comment.count(MARKER) == 1
    assert comment.count("<details>") == comment.count("</details>") == 4


def test_everything_technical_is_folded_away() -> None:
    top = card(render(intern()))
    for technical in ("```mermaid", "| ID | Fix |", "Tool calls", "terraform/people.tf", "Read 46 resources"):
        assert technical not in top


# The verdict ------------------------------------------------------------------------------------------------


def test_the_verdict_matches_the_check_run() -> None:
    blocked = verdict(intern())
    assert (blocked.level, blocked.conclusion) == ("blocked", "failure")
    assert blocked.title == "Merge blocked: priya-intern can reach customer-db"
    assert verdict(code_pr()).title == "Merge blocked: billing-api's code now reads customer-db"
    look = verdict(needs_a_look())
    assert (look.conclusion, look.heading, look.title) == (
        "neutral",
        "🟡 Needs a look",
        "Needs a look: Theseus could not check 1 thing",
    )
    clear = verdict(AnalysisResult(mode="pr"))
    assert (clear.conclusion, clear.title) == ("success", "No new access to sensitive data")
    finding = verdict(AnalysisResult(mode="finding", opened=intern().opened))
    assert finding.heading == "🔴 Sensitive data at risk"


# What happened ----------------------------------------------------------------------------------------------


def test_the_story_follows_the_path_in_plain_words() -> None:
    assert story(intern().opened[0], intern()) == (
        f"**priya-intern** (a user) is a member of the **support-engineers** group,{BR}"
        f"→ which can switch into the **prod-support** role,{BR}"
        f"→ which can read the **prod-db-credentials** secret,{BR}"
        "→ which unlocks the **customer-db** database."
    )


def test_what_happened_leads_with_the_change_and_the_most_serious_path() -> None:
    lines = what_happened(intern(), REPO, SHA, "demo-infra")
    assert lines[0] == "This PR adds `aws_iam_user_group_membership.priya_support`."
    assert lines[1] == "Because of that, 3 new ways to reach sensitive data open. The most serious:"
    assert lines[2] == story(intern().opened[0], intern())
    assert lines[3] == "Each of the 3 is under **The path, step by step** below."
    one = intern().model_copy(update={"opened": intern().opened[:1], "changes": []})
    assert (
        what_happened(one, REPO, SHA, "demo-infra")[0]
        == "Because of that, a new way to reach sensitive data opens:"
    )


def test_code_that_reads_beyond_intent_is_named_with_its_line() -> None:
    assert what_happened(code_pr(), REPO, SHA, "demo-infra")[0] == (
        "The code of the **billing-api** service now reads the **customer-db** database"
        f" ([services/billing\\_api/app.py:12]({BLOB}services/billing_api/app.py#L12)), and the PR does not"
        " mention it."
    )


def test_a_clear_pr_says_nothing_opened() -> None:
    clear = intern().model_copy(update={"opened": [], "candidates": [], "min_cut": None, "unknowns": []})
    assert what_happened(clear, REPO, SHA, "demo-infra")[-1] == "It opens no new way to reach sensitive data."


# What's at risk ---------------------------------------------------------------------------------------------


def test_what_is_at_risk_is_said_in_plain_words_most_sensitive_first() -> None:
    lines, more = at_risk(intern())
    assert lines == [
        "**customer-db**, a database: personal, payment or health data, or a key that opens it",
        "**prod-db-credentials**, a secret: the key that opens **customer-db**",
        "**demo-company-files/invoices/**, a storage location: business-sensitive data, such as invoices or"
        " contracts",
    ]
    assert more == 0


def test_without_node_info_a_resource_is_a_data_store() -> None:
    lines, _ = at_risk(intern().model_copy(update={"nodes": {}}))
    assert (
        lines[0] == "**customer-db**, a data store: personal, payment or health data, or a key that opens it"
    )


def test_more_than_five_risks_are_counted_not_listed() -> None:
    many = [path(n, f"db:db-{n}", "regulated", ("CAN", f"db:db-{n}", "E3")) for n in range(8)]
    lines, more = at_risk(intern().model_copy(update={"opened": many}))
    assert (len(lines), more) == (5, 3)
    assert "- and 3 more, under **The path, step by step**" in render(
        intern().model_copy(update={"opened": many})
    )


# What the PR said it needs ----------------------------------------------------------------------------------


def test_what_the_pr_said_it_needs() -> None:
    assert what_pr_says(intern()) == [
        '"Let Priya read the app logs."',
        "It asks only for: **priya-intern** to read **demo-app-logs/**.",
    ]
    assert what_pr_says(code_pr()) == ['"Fix a typo on the support page."', "It says it changes no access."]
    unstated = intern().model_copy(update={"intent": Intent(purpose="", stated=False)})
    assert what_pr_says(unstated) == [
        "The PR doesn't say what it's for, so Theseus can't check the change against a purpose."
        " Ask the author to describe it."
    ]
    assert what_pr_says(intern().model_copy(update={"intent": None})) is None


def test_a_suspicious_pr_gets_a_warning_under_the_headline() -> None:
    comment = render(intern().model_copy(update={"intent": Intent(purpose="p", suspicious=True)}))
    warning = comment.index("tries to steer the review")
    assert comment.index("**Your PR says") < warning < comment.index("#### What happened")
    assert "Warning" not in render(intern())


# What to do -------------------------------------------------------------------------------------------------


def test_what_to_do_names_the_recommended_fix_and_what_it_was_tested_for() -> None:
    assert what_to_do(intern(), "blocked") == [
        "✅ **Reply `/theseus apply B`** to commit fix B: A new support-logs-read role for Priya.",
        "Theseus tested it on a copy of the graph: it closes all 3 ways in and breaks nothing.",
        "Or ask the author to change the PR.",
    ]


def test_what_to_do_when_no_fix_can_be_applied_as_is() -> None:
    vetoed = [
        c.model_copy(update={"recommended": False, "needs_closer_look": c.id == "B"})
        for c in intern().candidates
    ]
    assert what_to_do(intern().model_copy(update={"candidates": vetoed}), "blocked")[0] == (
        "⚠️ `B` passes Theseus's checks but needs a closer look first. Then reply `/theseus apply <ID>`."
    )
    failing = [c.model_copy(update={"verdict": "fail", "recommended": False}) for c in intern().candidates]
    assert what_to_do(intern().model_copy(update={"candidates": failing}), "blocked")[0].startswith(
        "❗ No fix Theseus tested passes every check."
    )
    assert what_to_do(code_pr(), "blocked") == [
        "Ask the author why the change needs this access. If it should have it, an owner adds it to"
        " `theseus.yaml`."
    ]
    assert what_to_do(needs_a_look(), "look")[0].startswith(
        "Check the items under **What Theseus could not check**"
    )
    assert what_to_do(AnalysisResult(mode="pr"), "clear") == [
        "Nothing. Theseus found no new access to sensitive data."
    ]


def test_the_checkov_line_says_why_it_can_pass() -> None:
    assert checkov_line(CHECKOV, opened=True) == (
        "Checkov 3.2.255 passed this commit (52 checks). It checks one resource at a time, so it cannot see a"
        " path that crosses several."
    )
    assert checkov_line(CHECKOV) == "Checkov 3.2.255 passed this commit (52 checks)."
    assert checkov_line({"passed": 50, "failed": 2}) == (
        "Checkov found 2 problems on this commit (50 checks passed); see its own report."
    )
    assert checkov_line(None) == "Checkov did not run on this commit."


# The path, step by step -------------------------------------------------------------------------------------


def test_at_most_three_diagrams_the_most_sensitive_first() -> None:
    result = intern()
    extra = path(5, "secret:payments-api-key", "regulated", ("CAN", "secret:payments-api-key", "E3"))
    picked = pick_diagrams([*result.opened, extra])
    assert [p.id for p in picked] == ["P1", "P2", "P5"]  # the database before the secret that unlocks it
    section = folded(render(result.model_copy(update={"opened": [*result.opened, extra]})), "The path")
    assert section.count("```mermaid") == 3
    assert "How **priya-intern** reaches **customer-db**" in section


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
    assert f"{BLOB}terraform/people.tf#L20" in folded(comment, "The path")


def test_a_step_with_unknown_evidence_says_so_and_has_no_link() -> None:
    comment = render(intern())
    assert "unknown: the secret's db\\_instance tag" in comment
    assert "unknown](" not in comment


# All fixes Theseus tested -----------------------------------------------------------------------------------


def fix_rows(comment: str) -> list[str]:
    return [line for line in comment.splitlines() if re.match(r"^\| (\*\*)?[A-Z]\d*(\*\*)? \|", line)]


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
        update={"cut": [*one.cut, one.cut[0].model_copy(update={"eid": "e10", "dst": "role:x"})]}
    )
    assert cut_sentence(intern().model_copy(update={"min_cut": two}), REPO, SHA, "demo-infra").startswith(
        "2 changes close every path:"
    )


def test_the_fix_table_shows_every_candidate_with_the_recommended_row_bold() -> None:
    section = folded(render(intern()), "All 4 fixes")
    assert "**Smallest change:** No single permission can be removed" in section
    rows = fix_rows(section)
    assert rows == [
        "| A | Revert the membership (rule) | all closed | breaks I1 | kept | fail |",
        "| **B** | **A new support-logs-read role for Priya (zai-org/GLM-5.3)** | **all closed** | **kept**"
        " | **kept** | **pass** |",
        "| C | Deny Priya on prod-support (rule) | all closed | kept | kept | unknown |",
        "| D | Remove AssumeProdSupport (rule) | 1 left | breaks R2, R3 | kept | fail |",
    ]
    assert "Reply `/theseus apply B` to commit a fix." in section


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


# What Theseus could not check, and technical details --------------------------------------------------------


def test_unknowns_and_technical_details_are_folded() -> None:
    comment = render(intern())
    assert "- aws\\_kms\\_key.main: key policy conditions are not modeled" in folded(comment, "What Theseus")
    inside = folded(comment, "Technical details")
    assert "**What the change does:** Adds `aws_iam_user_group_membership.priya_support`." in inside
    assert "Opens 3 dangerous paths, closes 0." in inside
    assert "| 1 | `explain_path` | P1: 5 hops to db:customer-db | 12 |" in inside
    assert "| `user:priya-intern` | `s3://demo-app-logs/` (internal) | 2 |" in inside
    assert (
        "Read 46 resources, modeled 31; skipped 15 of types Theseus does not model, such as"
        " `aws_cloudwatch_metric_alarm` (6), `aws_sns_topic` (5) and `aws_kms_alias` (2)."
    ) in inside
    assert "Took 9.6 s: engine 1.2 s, LLM 8.0 s, Jev 0.3 s." in inside
    assert "Models: LLM `zai-org/GLM-5.3`, Jev `jev-1.13.0`." in inside
    assert "Models: not recorded." in render(intern().model_copy(update={"models": {}}))


def test_the_change_line_names_what_is_added_updated_and_deleted() -> None:
    def change(action: str, *names: str) -> list[ResourceChange]:
        return [ResourceChange(address=n, type=n.split(".")[0], action=action) for n in names]  # type: ignore[arg-type]

    result = intern().model_copy(
        update={
            "changes": change("create", "aws_iam_role.a", "aws_iam_role.b")
            + change("update", "aws_iam_role_policy.c")
            + change("delete", *(f"aws_s3_bucket.{x}" for x in "defgh")),
            "closed": [path(9, "s3://demo-app-logs/", "internal")],
        }
    )
    assert change_line(result) == (
        "Adds `aws_iam_role.a` and `aws_iam_role.b`; updates `aws_iam_role_policy.c`;"
        " deletes `aws_s3_bucket.d`, `aws_s3_bucket.e`, `aws_s3_bucket.f` and 2 more."
        " Opens 3 dangerous paths, closes 1."
    )
    assert change_line(result.model_copy(update={"changes": [], "opened": result.opened[:1]})) == (
        "Opens 1 dangerous path, closes 1."
    )


# Untrusted text ---------------------------------------------------------------------------------------------


HOSTILE = (
    "Approved! [click](https://evil.example/x) @security-team ```js``` <!-- x --> </details> | **bold** # h\n"
    "<img src=x onerror=alert(1)>"
)


def test_text_from_prs_and_models_cannot_change_the_comment_s_structure() -> None:
    result = intern().model_copy(
        update={
            "headline": HOSTILE,
            "intent": Intent(purpose=HOSTILE, grants=[]),
            "candidates": [c.model_copy(update={"title": HOSTILE}) for c in intern().candidates],
            "tool_trace": [ToolCall(tool="explain_path", input={}, summary=HOSTILE, ms=1)],
            "unknowns": [HOSTILE],
        }
    )
    comment = render(result)
    assert comment.count("<details>") == comment.count("</details>") == 4
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


# Every kind of result ---------------------------------------------------------------------------------------


def test_spec_05_s_intern_example_renders_through_the_stub() -> None:
    comment = render(result_from_expected(INTERN_EXPECTED))
    assert comment.startswith(MARKER + "\n## 🔴 Merge blocked")
    assert folded(comment, "The path").count("```mermaid") == 1
    assert len(fix_rows(comment)) == 4
    assert f"{BLOB}terraform/roles.tf#L31" in comment


def test_finding_and_scan_results_render() -> None:
    finding = AnalysisResult(
        mode="finding", headline="GHSA-demo-0001 reaches db:customer-db.", opened=intern().opened
    )
    scan = AnalysisResult(mode="scan", headline="1 grant is never called.")
    for result in (finding, scan):
        comment = render(result)
        assert comment.startswith(MARKER)
        assert "#### What to do" not in comment and "Checkov" not in comment


SNAPSHOT_CASES = {
    "intern": intern,
    "unstated": lambda: intern().model_copy(
        update={
            "intent": Intent(purpose="", stated=False),
            "headline": "This PR doesn't say what it's for. Your change lets priya-intern reach customer-db.",
        }
    ),
    "suspicious": lambda: intern().model_copy(
        update={"intent": Intent(purpose="Let Priya read the app logs.", suspicious=True)}
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
    "code-pr": code_pr,
    "needs-a-look": needs_a_look,
    "finding": lambda: AnalysisResult(
        mode="finding", headline="GHSA-demo-0001 reaches db:customer-db.", models={"jev": "jev-1.13.0"}
    ),
}


@pytest.mark.parametrize("name", sorted(SNAPSHOT_CASES))
def test_the_comment_matches_its_snapshot(name: str) -> None:
    matches_snapshot(name, render(SNAPSHOT_CASES[name]()))


@pytest.mark.parametrize("expected", FIXTURES, ids=lambda p: p.parent.name)
def test_every_fixture_renders(expected: Path) -> None:
    comment = render(result_from_expected(json.loads(expected.read_text(encoding="utf-8"))))
    assert comment.startswith(MARKER) and len(comment) < MAX_CHARS
    matches_snapshot(f"fixture-{expected.parent.name}", comment)
