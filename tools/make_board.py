#!/usr/bin/env python3
"""Build the Theseus GitHub board from tasks.csv.

Creates lane, size and demo labels, one milestone per stage, one issue per task (linked
to the issues it needs first), and a GitHub Project with a Lane field. Re-running
is safe: existing labels, milestones, issues and the project are reused.

    python tools/make_board.py --repo OWNER/theseus --dry-run
    python tools/make_board.py --repo OWNER/theseus --create-repo
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Rule 8: the repo and its first commit come after the event starts.
EVENT_START = datetime(2026, 10, 14, 18, 31, tzinfo=timezone.utc)

REPO_DESCRIPTION = (
    "Theseus: a graph agent that reviews infrastructure changes before merge (FalkorDB Graph Hacks, Track 01)"
)

# stage -> (milestone title, description). Each milestone ends at its gate.
STAGES = {
    "Prep": ("Prep", "Notes and throwaway checks only (rule 8)."),
    "Foundation": ("Foundation", "Gate: a demo PR gets a stub comment from the live URL."),
    "Beat 1": ("Beat 1: See it", "Gate 1: the intern PR shows three opened paths and says versus grants."),
    "Beat 2": ("Beat 2: Fix it", "Gate 2: Demo 2 end to end, apply included."),
    "Beats 3 and 4": (
        "Beats 3 and 4: Contain it, Nobody breaks",
        "Gate 3: the containment PR and the unused-grant fix, with backup clips.",
    ),
    "Ship": ("Ship", "Benchmark, Try-it, README, video, submission."),
}

# lane -> (label, color)
LANES = {
    "Prep": ("lane:prep", "c5def5"),
    "Foundation": ("lane:foundation", "bfd4f2"),
    "Engine": ("lane:engine", "0e8a16"),
    "Agent and GitHub": ("lane:agent", "1d76db"),
    "Finding mode": ("lane:finding", "d93f0b"),
    "Code-aware": ("lane:code", "5319e7"),
    "Story and proof": ("lane:story", "fbca04"),
    "Gate": ("lane:gate", "b60205"),
}

DEMO_LABEL = ("demo", "ededed", "A demo PR or issue in demo-infra/; never mixed with product work")

SIZES = {"S": "small", "M": "medium", "L": "large"}

TASK_ID = re.compile(r"^[A-Z]{1,2}\d+$")
TITLE_ID = re.compile(r"^([A-Z]{1,2}\d+): ")


def split_needs(needs: str) -> list[str]:
    return [n.strip() for n in re.split(r"[,;]", needs) if n.strip()]


def load_tasks(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        tasks = list(csv.DictReader(f))
    problems = []
    seen: set[str] = set()
    for t in tasks:
        tid = t["id"]
        if not TASK_ID.match(tid):
            problems.append(f"{tid}: IDs look like E4 or FM3")
        if tid in seen:
            problems.append(f"{tid}: listed twice")
        if t["stage"] not in STAGES:
            problems.append(f"{tid}: unknown stage {t['stage']!r}")
        if t["lane"] not in LANES:
            problems.append(f"{tid}: unknown lane {t['lane']!r}")
        if t["size"] not in SIZES:
            problems.append(f"{tid}: size must be S, M or L")
        # Dependencies must be listed earlier, so every link resolves in one pass.
        for dep in split_needs(t["needs"]):
            if TASK_ID.match(dep) and dep not in seen:
                problems.append(f"{tid}: needs {dep}, which is not listed before it")
        seen.add(tid)
    if problems:
        sys.exit("tasks.csv has problems:\n  " + "\n  ".join(problems))
    return tasks


class GH:
    """Runs gh. In a dry run nothing is sent to GitHub; commands are printed instead."""

    def __init__(self, dry_run: bool):
        self.dry_run = dry_run

    def run(self, *args: str, stdin: str | None = None, may_fail: bool = False) -> str:
        if self.dry_run:
            print("  would run: gh " + " ".join(shlex.quote(a) for a in args))
            return ""
        proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            if may_fail:
                return ""
            sys.exit(f"gh {' '.join(args[:3])} failed:\n{proc.stderr.strip()}")
        return proc.stdout

    def json(self, *args: str, may_fail: bool = False):
        out = self.run(*args, may_fail=may_fail)
        return json.loads(out) if out.strip() else None


def check_ready(args) -> None:
    if args.dry_run:
        return
    if datetime.now(timezone.utc) < EVENT_START and not args.allow_early:
        sys.exit(
            "The event has not started, and rule 8 says the repo and its first commit "
            "come after it starts. Use --dry-run now, or --allow-early if you are sure."
        )
    status = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if status.returncode != 0:
        sys.exit("gh is not logged in. Run: gh auth login")
    if not args.skip_project and "'project'" not in status.stdout + status.stderr:
        sys.exit(
            "The gh token lacks the 'project' scope that the board needs. Run: gh auth refresh -s project"
        )


def ensure_repo(gh: GH, repo: str, create: bool, visibility: str) -> None:
    print(f"Repo {repo}")
    if gh.dry_run:
        if create:
            gh.run("repo", "create", repo, f"--{visibility}", "--description", REPO_DESCRIPTION)
        return
    found = (
        subprocess.run(
            ["gh", "repo", "view", repo, "--json", "name"], capture_output=True, text=True
        ).returncode
        == 0
    )
    if found:
        print("  exists")
        return
    if not create:
        sys.exit(f"Repo {repo} was not found. Create it, or pass --create-repo.")
    gh.run("repo", "create", repo, f"--{visibility}", "--description", REPO_DESCRIPTION)
    print("  created")


def ensure_labels(gh: GH, repo: str) -> None:
    print("Labels")
    for lane, (name, color) in LANES.items():
        gh.run(
            "label",
            "create",
            name,
            "--repo",
            repo,
            "--color",
            color,
            "--description",
            f"Lane: {lane}",
            "--force",
        )
    for size, meaning in SIZES.items():
        gh.run(
            "label",
            "create",
            f"size:{size}",
            "--repo",
            repo,
            "--color",
            "ededed",
            "--description",
            f"Size {size}: {meaning}",
            "--force",
        )
    name, color, description = DEMO_LABEL
    gh.run("label", "create", name, "--repo", repo, "--color", color, "--description", description, "--force")


def ensure_milestones(gh: GH, repo: str) -> None:
    print("Milestones")
    existing = gh.json("api", f"repos/{repo}/milestones?state=all&per_page=100") or []
    titles = {m["title"] for m in existing}
    for title, description in STAGES.values():
        if title in titles:
            print(f"  exists: {title}")
            continue
        gh.run(
            "api",
            f"repos/{repo}/milestones",
            "-X",
            "POST",
            "-f",
            f"title={title}",
            "-f",
            f"description={description}",
        )


def branch_name(t: dict) -> str:
    """The branch named in the task's brief; otherwise one made from the ID and title."""
    brief = HERE.parent / "docs" / "tasks" / f"{t['id']}.md"
    if brief.exists():
        m = re.search(r"\*\*Branch:\*\* `([^`]+)`", brief.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    slug = re.sub(r"[^a-z0-9]+", "-", t["title"].lower()).strip("-")
    return f"{t['id'].lower()}-{slug}"[:40].rstrip("-")


BRIEFS = HERE.parent / "docs" / "tasks"


def brief_link(t: dict, repo: str) -> str:
    name = f"{t['id']}.md" if (BRIEFS / f"{t['id']}.md").exists() else "human-tasks.md"
    return f"https://github.com/{repo}/blob/main/docs/tasks/{name}"


def issue_body(t: dict, issues: dict, repo: str) -> str:
    needs = []
    for dep in split_needs(t["needs"]):
        number = issues.get(dep, (None, ""))[0]
        needs.append(f"#{number} ({dep})" if number else dep)
    return "\n".join(
        [
            f"**Task:** {t['task']}",
            "",
            f"**Lane:** {t['lane']} | **Size:** {t['size']} ({SIZES[t['size']]}) | "
            f"**Stage:** {STAGES[t['stage']][0]}",
            "",
            f"**Needs first:** {', '.join(needs) if needs else 'nothing'}",
            "",
            f"**Done when:** {t['done_when']}",
            "",
            f"**Brief:** {brief_link(t, repo)} "
            "(files, purpose of each, steps, tests, and the prompt for your agent)",
            "",
            "---",
            f"Claim it: assign yourself and move it to In progress. Branch: `{branch_name(t)}`. "
            "Every `expected.json` is written by us, never by an agent.",
            "",
        ]
    )


def ensure_issues(gh: GH, repo: str, tasks: list[dict]) -> dict:
    """Returns task ID -> (issue number, issue URL)."""
    print("Issues")
    issues: dict[str, tuple] = {}
    existing = (
        gh.json(
            "issue", "list", "--repo", repo, "--state", "all", "--limit", "500", "--json", "number,title,url"
        )
        or []
    )
    for issue in existing:
        m = TITLE_ID.match(issue["title"])
        if m:
            issues[m.group(1)] = (issue["number"], issue["url"])
    for t in tasks:
        if t["id"] in issues:
            print(f"  exists: #{issues[t['id']][0]} {t['id']}")
            continue
        out = gh.run(
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            f"{t['id']}: {t['title']}",
            "--body-file",
            "-",
            "--label",
            f"{LANES[t['lane']][0]},size:{t['size']}",
            "--milestone",
            STAGES[t["stage"]][0],
            stdin=issue_body(t, issues, repo),
        )
        url = out.strip().splitlines()[-1] if out.strip() else ""
        m = re.search(r"/issues/(\d+)$", url)
        issues[t["id"]] = (int(m.group(1)) if m else None, url)
        if url:
            print(f"  created: {url}")
    return issues


def project_field(gh: GH, number: str, owner: str, name: str):
    data = (
        gh.json("project", "field-list", number, "--owner", owner, "--format", "json", "--limit", "50") or {}
    )
    return next((f for f in data.get("fields", []) if f.get("name") == name), None)


def ensure_project(gh: GH, owner: str, repo: str, title: str, tasks: list[dict], issues: dict) -> None:
    print(f"Project {title!r}")
    listed = gh.json("project", "list", "--owner", owner, "--format", "json", "--limit", "100") or {}
    project = next((p for p in listed.get("projects", []) if p.get("title") == title), None)
    if project is None:
        project = gh.json("project", "create", "--owner", owner, "--title", title, "--format", "json")
    number = str(project["number"]) if project else "<number>"
    project_id = project.get("id") if project else None
    gh.run("project", "link", number, "--owner", owner, "--repo", repo, may_fail=True)

    lane_field = None if gh.dry_run else project_field(gh, number, owner, "Lane")
    if lane_field is None:
        gh.run(
            "project",
            "field-create",
            number,
            "--owner",
            owner,
            "--name",
            "Lane",
            "--data-type",
            "SINGLE_SELECT",
            "--single-select-options",
            ",".join(LANES),
        )
        lane_field = None if gh.dry_run else project_field(gh, number, owner, "Lane")
    options = {o["name"]: o["id"] for o in (lane_field or {}).get("options", [])}

    for t in tasks:
        url = issues[t["id"]][1] or f"<issue url for {t['id']}>"
        item = gh.json("project", "item-add", number, "--owner", owner, "--url", url, "--format", "json")
        if item and project_id and lane_field and t["lane"] in options:
            gh.run(
                "project",
                "item-edit",
                "--id",
                item["id"],
                "--project-id",
                project_id,
                "--field-id",
                lane_field["id"],
                "--single-select-option-id",
                options[t["lane"]],
            )
    if project and project.get("url"):
        print(f"  board: {project['url']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", required=True, help="OWNER/NAME, for example yourname/theseus")
    parser.add_argument("--tasks", type=Path, default=HERE / "tasks.csv")
    parser.add_argument("--create-repo", action="store_true", help="create the repo if it does not exist")
    parser.add_argument(
        "--visibility",
        choices=["private", "public"],
        default="private",
        help="for a new repo (make it public before submitting)",
    )
    parser.add_argument("--project-title", default="Theseus hackathon")
    parser.add_argument("--skip-project", action="store_true", help="labels, milestones and issues only")
    parser.add_argument("--dry-run", action="store_true", help="print what would happen; send nothing")
    parser.add_argument("--allow-early", action="store_true", help="run before the event starts")
    args = parser.parse_args()

    if "/" not in args.repo:
        sys.exit("--repo must look like OWNER/NAME")
    tasks = load_tasks(args.tasks)
    print(
        f"{len(tasks)} tasks from {args.tasks.name}" + (" (dry run: nothing is sent)" if args.dry_run else "")
    )
    check_ready(args)

    gh = GH(args.dry_run)
    owner = args.repo.split("/")[0]
    ensure_repo(gh, args.repo, args.create_repo, args.visibility)
    ensure_labels(gh, args.repo)
    ensure_milestones(gh, args.repo)
    issues = ensure_issues(gh, args.repo, tasks)
    if not args.skip_project:
        ensure_project(gh, owner, args.repo, args.project_title, tasks, issues)
    print("Done.")


if __name__ == "__main__":
    main()
