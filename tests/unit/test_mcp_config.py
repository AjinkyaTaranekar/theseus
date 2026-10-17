"""`.mcp.json` and the docs that tell a person how to start the MCP server on their own machine (issue #145).

Claude Code expands `${VAR:-default}` in a stdio server's `command`, so the file can name the Python of a
virtualenv through `THESEUS_PYTHON` without being edited. These tests keep the file, the README and AGENTS.md
saying the same thing, and keep the README's example prompts on tools the registry really has.
"""

from __future__ import annotations

import json
import re

from tests.golden.conftest import ROOT
from theseus.mcp.tools import build_registry

MCP_FILE = ROOT / ".mcp.json"
README = (ROOT / "README.md").read_text(encoding="utf-8")
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
SECTION = "Try the tools from Claude Code"


def server() -> dict[str, object]:
    return json.loads(MCP_FILE.read_text(encoding="utf-8"))["mcpServers"]["theseus"]


def try_section() -> str:
    """The README's text from the "Try the tools" heading to the next heading of the same level."""
    start = README.index(f"## {SECTION}")
    end = README.find("\n## ", start + 1)
    return README[start : end if end != -1 else len(README)]


def test_the_command_is_the_python_the_person_names_or_plain_python() -> None:
    assert server()["command"] == "${THESEUS_PYTHON:-python}"


def test_the_server_starts_the_module_on_a_fixture_that_exists() -> None:
    args = server()["args"]
    assert args[:2] == ["-m", "theseus.mcp.server"]
    assert (ROOT / args[2] / "head.plan.json").is_file()


def test_readme_and_agents_say_what_to_set_on_each_platform() -> None:
    for name, text in (("README.md", README), ("AGENTS.md", AGENTS)):
        assert "THESEUS_PYTHON=.venv/bin/python" in text, name
        assert "THESEUS_PYTHON=.venv\\Scripts\\python" in text, name


def test_readme_has_three_prompts_that_call_tools_the_registry_has() -> None:
    section = try_section()
    prompts = re.findall(r"^> (.+)$", section, flags=re.MULTILINE)
    assert len(prompts) >= 3
    named = set(re.findall(r"`(\w+)`", section)) & {t.name for t in build_registry().tools}
    assert {"diff_paths", "min_cut"} <= named
