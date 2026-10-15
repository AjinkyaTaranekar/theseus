# Theseus spec

The build follows these files. When code and spec disagree, the spec wins until both humans change it.
Task briefs in `docs/tasks/` point to the exact sections each task needs.

| File | What it settles | Read it when |
| --- | --- | --- |
| [01-product.md](01-product.md) | What Theseus does, the three modes, the four story beats, who decides what, the glossary | Always, once |
| [02-demo-world.md](02-demo-world.md) | The `demo-infra/` world: the company, the map of how everything relates, every Terraform resource, service module, workflow, `theseus.yaml`, what `main` looks like, and the five scenarios with their expected outcomes | Fixtures, importer, golden tests, demos |
| [03-graph.md](03-graph.md) | Node IDs, labels, properties, edge types, evidence, one graph per state, the canonical Cypher | Importer, graph layer, engine |
| [04-engine.md](04-engine.md) | Import rules, the IAM subset, edge derivation, paths, requirements, diff, capacities, the minimum cut, patch ops, simulation, verdicts, ranking, findings, usage | Engine and importer tasks |
| [05-contracts.md](05-contracts.md) | Module layout, the shared models, engine functions, MCP tools, API routes, the PR comment, `expected.json` | Every task |
| [06-agent.md](06-agent.md) | The LLM and Jev: schemas, prompts, record and replay, the evidence checker, untrusted text | Agent tasks |
| [07-github-and-deploy.md](07-github-and-deploy.md) | The GitHub Action and App, the apply command, Docker Compose, Caddy, environment variables | GitHub and deploy tasks |

## Decisions already made

- AWS only. Terraform plan JSON is the input; no live cloud account is ever read.
- One repo. The product and the synthetic world (`demo-infra/`) live together; demo PRs are PRs in this repo
  that change only `demo-infra/`, and the App may write only there. No GitHub org is needed.
- Python 3.12, FastAPI, Pydantic v2, FalkorDB.
- One FalkorDB graph per state; candidate fixes run on `GRAPH.COPY` copies.
- The engine decides facts; the LLM proposes and explains; Jev answers typed questions; a person approves.
- UNKNOWN is a real answer. Anything outside the supported IAM subset returns UNKNOWN, never a guess.
- Findings from the throwaway PoC are written into these files. Its code is never copied (rule 8).
