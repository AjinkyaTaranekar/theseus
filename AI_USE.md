# AI use

Coding agents write much of this code (hackathon rule 11). Each task adds one line: which agent wrote what,
and what the humans changed. Commits name the agent in a `Co-Authored-By:` trailer.

| Task | Agent | What it wrote | What we changed |
| --- | --- | --- | --- |
| P3 | Codex | Drafted `docs/reviews/P3.md` from the existing specification and checked its reasoning with a local throwaway paper model. No product code or `expected.json` was added. | Both of us reviewed the notes and signed off. |
| F1 | Claude Code (Claude Opus 5.5) | Package skeleton, settings, CLI stub, tests, CI, PR template, code owners, `.env.example` | Chose LiteLLM with GLM 5.3 on Crusoe instead of the Anthropic SDK, and FalkorDB Cloud instead of Docker |
| F2 | Claude Code (Claude Opus 5.5) | Vendor-neutral contracts (schema, models, `project()`, `compare()`, engine and adapter protocols), the adapter packages with the AWS kinds and op catalog, the architecture test, and the spec and brief updates | Asked for the core to stay vendor-neutral so other clouds, IaC formats and CI systems can be added as adapters; field names pending both humans' read-through |

The P3 entry discloses assistance with review notes. Both teammates agreed on the expected paths and capacities, so P3 is complete.
