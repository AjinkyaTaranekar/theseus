# FM4: Finding extras: choke points, staging to prod, urgency

**Lane:** Finding mode | **Stage:** Beat 2: Fix it | **Size:** M | **Needs first:** FM3, E4, A2 | **Branch:** `fm4-finding-extras`

## The feature

Three facts every result can carry, none of which blocks containment: choke points from `algo.betweenness` with a Python fallback; every path from a staging actor to sensitive prod data; and Jev's urgency for a finding.

## Why it matters

It shows FalkorDB's algorithms doing visible work (one role sits on every route), catches the docs-site preview reaching prod, and shows System 1 making a fast typed call. Kept apart from FM6 so the containment PR does not wait for it.

## Read first

- [03-graph.md: Canonical queries (theseus/graph/queries.py)](../spec/03-graph.md#canonical-queries-theseusgraphqueriespy)
- [04-engine.md: 16. Finding mode (engine/finding.py)](../spec/04-engine.md#16-finding-mode-enginefindingpy)
- [04-engine.md: 8. Sensitivity and environments](../spec/04-engine.md#8-sensitivity-and-environments)
- [06-agent.md: Jev (agent/jev.py, agent/sensitivity.py, task A2)](../spec/06-agent.md#jev-agentjevpy-agentsensitivitypy-task-a2)

## Files

| File | Action | Purpose |
| --- | --- | --- |
| `theseus/graph/algos.py` | change | `betweenness(store, graph)`: `FalkorStore` uses `Q_BETWEENNESS`; `MemoryStore` uses Brandes |
| `theseus/engine/staging.py` | create | `staging_to_prod(analysis, rows)` |
| `theseus/engine/pipeline.py` | change | `choke_points` and `staging_to_prod` in every mode; `finding.urgency = {p, source}` in `run_finding` |
| `tests/golden/test_compromised_action.py` | change | `role:prod-support` ranks first among roles; the preview path is flagged staging to prod; urgency replayed |
| `tests/golden/test_intern.py` | change | No staging-to-prod flag |

## Steps

1. Golden tests first.
2. Parity test for betweenness against FalkorDB, marked.
3. Write down in the PR exactly what `algo.betweenness` returned.

## Done when

- [ ] `prod-support` ranks first among roles
- [ ] The docs-site preview path is flagged; the intern flags none
- [ ] The urgency shows with its probability
- [ ] `pytest -q` and `ruff check .` pass, and `AI_USE.md` has this task's line

## Prompt for your agent

> You are working on task `FM4` in the Theseus repo. Read `AGENTS.md`, then `docs/tasks/FM4.md`,
> then every spec section it lists under "Read first". Work only in the files the brief lists. Write the
> tests under "Done when" first, then the code, until `pytest -q` and `ruff check .` pass. If anything in
> the spec is unclear, stop and ask instead of guessing. Finish by drafting the PR description, including
> any check you could not run, and the `AI_USE.md` line.
