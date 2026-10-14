# FM6: Containment PR

**Lane:** Finding mode | **Stage:** Beats 3 and 4: Contain it, Nobody breaks | **Size:** M | **Needs first:** FM3, E4, E5, E9, A9 | **Branch:** `fm6-containment`

## The feature

Candidate K pins the cut role's `sub` to the workflows that need it, is verified on a graph copy, rendered to Terraform, and opened as a PR with a rotate issue.

## Why it matters

Beat 3 ends with the agent acting: one PR contains the compromise, mirroring how `terraform-apply` is already pinned.

## Read first

- [04-engine.md: 16. Finding mode (engine/finding.py)](../spec/04-engine.md#16-finding-mode-enginefindingpy)
- [07-github-and-deploy.md: Finding and scan outputs (tasks FM6, C3)](../spec/07-github-and-deploy.md#finding-and-scan-outputs-tasks-fm6-c3)

## Files

| File | Action | Purpose |
| --- | --- | --- |
| `theseus/engine/finding.py` | change | `containment(rows, cut, requirements)` building K ops |
| `theseus/api/github.py`, `theseus/api/routes.py` | change | Open the containment PR (branch `theseus/contain-<id>`, label `demo`, only `demo-infra/terraform/ci.tf` changed) and the rotate issue |
| `tests/golden/test_compromised_action.py` | change | K passes; R4, R5 and R17 still hold |
| `tests/unit/test_containment_pr.py` | create | respx-mocked PR and issue creation |

## Steps

1. Golden test first, then the GitHub calls.

## Done when

- [ ] A containment PR opens in this repo with only `ci.tf` changed
- [ ] `pytest -q` and `ruff check .` pass, and `AI_USE.md` has this task's line

## Out of scope

- The gate check and clip (G3, humans)

## Prompt for your agent

> You are working on task `FM6` in the Theseus repo. Read `AGENTS.md`, then `docs/tasks/FM6.md`,
> then every spec section it lists under "Read first". Work only in the files the brief lists. Write the
> tests under "Done when" first, then the code, until `pytest -q` and `ruff check .` pass. If anything in
> the spec is unclear, stop and ask instead of guessing. Finish by drafting the PR description, including
> any check you could not run, and the `AI_USE.md` line.
