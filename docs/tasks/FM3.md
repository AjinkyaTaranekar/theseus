# FM3: Finding mode: blast radius and rotate list

**Lane:** Finding mode | **Stage:** Beat 2: Fix it | **Size:** M | **Needs first:** FM1, E3 | **Branch:** `fm3-finding`

## The feature

`POST /finding` and `python -m theseus finding`: match the advisory to workflows, assume them compromised, map what they reach, and list exactly the secrets to rotate.

## Why it matters

Beat 3 opens with a real alert shape and a trace through CI into the database. After tj-actions, every team had to guess which secrets to rotate; Theseus gives the short list. Both read the same blast radius, so one session does them.

## Read first

- [04-engine.md: 16. Finding mode (engine/finding.py)](../spec/04-engine.md#16-finding-mode-enginefindingpy)
- [02-demo-world.md: compromised-action (finding mode; Beat 3)](../spec/02-demo-world.md#compromised-action-finding-mode-beat-3)

## Files

| File | Action | Purpose |
| --- | --- | --- |
| `theseus/engine/finding.py` | create | `match_advisory`, `blast_radius`, `rotate_list` (every reachable resource whose category is `secret`, sorted); the `Finding` node and `AFFECTS` edge. Names no vendor |
| `theseus/engine/pipeline.py` | change | `run_finding(world, advisory, deps)` with blast radius and rotate; `min_cut` once E4 has merged |
| `theseus/api/routes.py`, `theseus/cli.py` | change | Real `/finding` for fixtures; `finding` command |
| `tests/golden/test_compromised_action.py` | create | Blast-radius targets and the five-hop route to `customer-db`; `lint.yml` reaches nothing; `terraform-apply` and the state bucket are out of reach; rotate equals `[secret:prod-db-credentials]` |

## Steps

1. Golden test first.
2. The advisory text is untrusted; it never becomes evidence.

## Done when

- [ ] The five-hop trace to `customer-db`
- [ ] The rotate list equals `expected.json`
- [ ] `pytest -q` and `ruff check .` pass, and `AI_USE.md` has this task's line

## Out of scope

- Choke points, staging to prod and urgency (FM4)
- Containment (FM6)

## Prompt for your agent

> You are working on task `FM3` in the Theseus repo. Read `AGENTS.md`, then `docs/tasks/FM3.md`,
> then every spec section it lists under "Read first". Work only in the files the brief lists. Write the
> tests under "Done when" first, then the code, until `pytest -q` and `ruff check .` pass. If anything in
> the spec is unclear, stop and ask instead of guessing. Finish by drafting the PR description, including
> any check you could not run, and the `AI_USE.md` line.
