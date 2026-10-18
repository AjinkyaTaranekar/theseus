---
description: What the Theseus plugin does, its commands, and how to set it up
---

Show the user this, briefly and in your own words. Call no tools unless they ask.

**What it does.** Theseus reviews infrastructure changes as a graph in FalkorDB. Before a commit or a pull
request, it plans the working tree against `main`, finds every path the change opens to sensitive data, says
where the change lands (who reaches it, what depends on it, what it costs), and proves the smallest fix on a
copy of the graph. Facts come from its engine; the models only propose; a person approves.

**Commands.**
- `/theseus:check [what it's for]`: check the working tree's change now.
- `/theseus:investigate <question>`: ask the graph, e.g. "what if casey-contractor is compromised?"
- `/theseus:help`: this text.

**Automatic.** Before `git commit`, `git push` or `gh pr create`, a hook runs the same check. A change that
would open a path to sensitive data is stopped once, with the reason and the fix. Running it again asks you.

**Setup.**
- A Python environment with Theseus installed (`pip install -e .` in the repo), and `THESEUS_PYTHON` set to its
  interpreter before starting Claude Code, e.g. `.venv/bin/python` (Windows: `.venv\Scripts\python.exe`).
- FalkorDB: the `FALKORDB_*` settings in the repo's `.env`.
- Terraform on your PATH. Plans need no cloud account; the first one downloads the providers once.

**Limits.** A defined AWS IAM subset and Python code. What it cannot model comes back UNKNOWN, and a path is
a modeled route, not proof that an attacker can get in.
