# CLAUDE.md

@AGENTS.md

## Claude Code only

- `AGENTS.md` is shared with Codex. Put any rule that applies to both there, not here.
- For an L-sized task, start in plan mode: list the files you will touch and the tests you will write, and wait
  for approval before editing.
- `.claude/settings.json` runs `tools/agent_guard.py` before every file edit and blocks writes to `expected.json`
  files and `.env`. If it blocks you, report the difference in the PR; do not work around it with a shell command.
- Before writing `theseus/agent/llm.py`, read the current LiteLLM docs for tool calling and exception types.
  Do not rely on memory for call shapes.
- Run `/memory` once at the start of a session to confirm this file and `AGENTS.md` loaded. Inside `demo-infra/`,
  its own `CLAUDE.md` adds the rules for the demo world.
