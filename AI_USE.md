# AI use

Coding agents write much of this code (hackathon rule 11). Each task adds one line: which agent wrote what,
and what the humans changed. Commits name the agent in a `Co-Authored-By:` trailer.

| Task | Agent | What it wrote | What we changed |
| --- | --- | --- | --- |
| P3 | Codex | Drafted `docs/reviews/P3.md` from the existing specification and checked its reasoning with a local throwaway paper model. No product code or `expected.json` was added. | Human review pending; no human sign-off is claimed. |
| F1 | Claude Code (Claude Opus 5.5) | Package skeleton, settings, CLI stub, tests, CI, PR template, code owners, `.env.example` | Chose LiteLLM with GLM 5.3 on Crusoe instead of the Anthropic SDK, and FalkorDB Cloud instead of Docker |

This entry discloses assistance with review notes. P3 remains pending until both teammates agree on the expected paths and capacities. Preserve this entry when F1 adds the project skeleton and extends this log.
