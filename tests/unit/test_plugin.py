"""The Claude Code plugin in plugins/theseus and its marketplace: manifests that parse, commands that describe
themselves, a skill with a name, an MCP server in repo mode, and a hook that passes ordinary commands without
running Theseus."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from theseus import cli

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "theseus"
HOOK = PLUGIN / "hooks" / "before_ship.py"


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    head = text.split("---\n", 2)[1]
    return dict(line.split(": ", 1) for line in head.strip().splitlines())


def test_the_marketplace_lists_the_plugin_and_the_manifest_names_it() -> None:
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    (entry,) = market["plugins"]
    assert entry["name"] == "theseus" and (ROOT / entry["source"]).resolve() == PLUGIN
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "theseus" and manifest["description"]


def test_the_server_runs_on_the_working_tree() -> None:
    server = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["theseus"]
    # Plugin configs expand ${VAR} but not ${VAR:-default}; the server finds the repo from its working folder.
    assert server["command"] == "${THESEUS_PYTHON}"
    assert server["args"] == ["-m", "theseus.mcp.server", "--repo", "."]


@pytest.mark.parametrize("name", ["check", "investigate", "help"])
def test_each_command_describes_itself(name: str) -> None:
    assert frontmatter(PLUGIN / "commands" / f"{name}.md")["description"]


def test_the_skill_has_a_name_and_says_when_to_use_it() -> None:
    meta = frontmatter(PLUGIN / "skills" / "theseus" / "SKILL.md")
    assert meta["name"] == "theseus" and "check_change" not in meta["description"]
    assert "Use when" in meta["description"]


def test_the_hook_runs_before_bash_and_matches_what_the_check_acts_on() -> None:
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    (entry,) = hooks["PreToolUse"]
    assert entry["matcher"] == "Bash" and "before_ship.py" in entry["hooks"][0]["command"]
    source = HOOK.read_text(encoding="utf-8")
    assert f're.compile(r"{cli.SHIPS.pattern}")' in source


@pytest.mark.parametrize(
    "event",
    [
        {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        {"tool_name": "Read", "tool_input": {"file_path": "x"}},
        "not json",
    ],
)
def test_the_hook_passes_other_commands_at_once(event: object) -> None:
    stdin = event if isinstance(event, str) else json.dumps(event)
    done = subprocess.run(
        [sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, check=False, timeout=30
    )
    assert (done.returncode, done.stdout) == (0, "")
