# AI use

Coding agents write much of this code (hackathon rule 11). Each task adds one line: which agent wrote what,
and what the humans changed. Commits name the agent in a `Co-Authored-By:` trailer.

| Task | Agent | What it wrote | What we changed |
| --- | --- | --- | --- |
| P3 | Codex | Drafted `docs/reviews/P3.md` from the existing specification and checked its reasoning with a local throwaway paper model. No product code or `expected.json` was added. | Both of us reviewed the notes and signed off. |
| F1 | Claude Code (Claude Opus 5.5) | Package skeleton, settings, CLI stub, tests, CI, PR template, code owners, `.env.example` | Chose LiteLLM with GLM 5.3 on Crusoe instead of the Anthropic SDK, and FalkorDB Cloud instead of Docker |
| F2 | Claude Code (Claude Opus 5.5) | Vendor-neutral contracts (schema, models, `project()`, `compare()`, engine and adapter protocols), the adapter packages with the AWS kinds and op catalog, the architecture test, and the spec and brief updates | Asked for the core to stay vendor-neutral so other clouds, IaC formats and CI systems can be added as adapters; field names pending both humans' read-through |
| F3 | Claude Code (Claude Opus 5.5) | FalkorDB Cloud client, the stub API (`/health`, `/analyze`, `/finding`, `/scan`), `theseus serve`, the Docker image, compose file, Caddyfile and deploy script, and CI jobs for FalkorDB and the image | Chose to park the VM deploy until the VM details arrive; the smoke test ran against our FalkorDB Cloud instance |
| A1 | Claude Code (Claude Opus 5.5) | The LLM wrapper (record, replay, live, retries, recording keys), PR text preparation, the untrusted-text screen, intent extraction with `stated` and the untrusted-content prompt, the intent tests, 28 draft cases in `intents.yaml`, and the 31 GLM 5.3 recordings | The 3 spec-sourced cases come from spec 02; the 28 drafts need both humans to confirm their answers. The humans asked for real-world PR text (templates, empty bodies, hidden comments), for no length cut and for the guardrails, and asked how the screen handles other languages and typos |
| A2 | Claude Code (Claude Opus 5.5) | The Jev client (record, replay, live, retries, fallback), sensitivity labels and overrides, the urgency and steering questions, the tests, and the Jev recordings | The humans asked for the steering check after the screen missed other languages and typos. One human approved the raw-zone `sensitive_overrides` entry and the `fallback` sensitivity source; the other still has to |

The P3 entry discloses assistance with review notes. Both teammates agreed on the expected paths and capacities, so P3 is complete.
