# AI use

Coding agents write much of this code (hackathon rule 11). Each task adds one line: which agent wrote what,
and what the humans changed. Commits name the agent in a `Co-Authored-By:` trailer.

| Task | Agent | What it wrote | What we changed |
| --- | --- | --- | --- |
| F1 | Claude Code (Claude Opus 5.5) | Package skeleton, settings, CLI stub, tests, CI, PR template, code owners, `.env.example` | Chose LiteLLM with GLM 5.3 on Crusoe instead of the Anthropic SDK, and FalkorDB Cloud instead of Docker |
