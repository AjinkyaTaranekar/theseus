# FM1: CI in the graph: workflows and OIDC trust

**Lane:** Finding mode | **Stage:** Beat 1: See it | **Size:** M | **Needs first:** F4, E2 | **Branch:** `fm1-ci-graph`

## The feature

Read every workflow file under `workflows/<org>/<repo>/`: per-job OIDC `sub` values, whether a job can request an ID token, and each `uses:` line, into `Workflow` and `Action` nodes and `USES` edges; then match GitHub OIDC trust statements against those `sub` values to create `TRUSTS` edges.

## Why it matters

Beat 3 starts from a compromised Action and turns on one loose trust, `repo:demo-org/*`. Without this, CI is invisible to the graph. The two halves share the `subs` data, so one session does both.

## Read first

- [08-core-and-adapters.md](../spec/08-core-and-adapters.md): what is core, what is an adapter, and the protocol you implement
- [04-engine.md: 6. Edge derivation (importer/build.py and friends)](../spec/04-engine.md#6-edge-derivation-importerbuildpy-and-friends)
- [03-graph.md: Labels and properties](../spec/03-graph.md#labels-and-properties)
- [02-demo-world.md: Workflows in demo-infra/workflows/demo-org/](../spec/02-demo-world.md#workflows-in-demo-infraworkflowsdemo-org)

## Files

| File | Action | Purpose |
| --- | --- | --- |
| `theseus/adapters/github/workflows.py` | create | `parse_workflow(org, repo, file, text)`: Workflow and Action nodes, `USES` edges, and a `CiIdentity` (issuer `https://token.actions.githubusercontent.com`, subjects = the `subs`); `GithubAdapter.read` returns them as a `CiRead`; a job with `environment` presents only the environment `sub`. PyYAML reads the `on:` key as `True`; handle both |
| `theseus/adapters/aws/oidc.py` | create | `oidc_statements(trust)`, `oidc_allows(statement, sub, aud)` returning `yes`, `yes-any-repo`, `no` or `unknown` (uses `iam.glob_match`), and `TRUSTS` derivation from the `CiIdentity` list; `AwsAdapter.rows` adds the edges |
| `tests/unit/adapters/github/test_workflows.py` | create | The four demo workflows: exact `subs`, `id_token`, `uses` with line numbers |
| `tests/unit/adapters/aws/test_oidc.py` | create | `repo:demo-org/*` accepts the docs-site PR token; `terraform-apply`'s pinned environment `sub` refuses it and accepts deploy's apply job; an unknown condition key is unknown; `lint.yml` and `ci.yml` without `id-token` get no edge |

## Steps

1. Write tests from the 02 workflow table and the two trust policies.
2. Implement `workflows.py`, then `oidc.py`, then wire into `build.py`.
3. Run on every fixture.

## Done when

- [ ] `preview.yml` has `id_token` true and `subs` `[repo:demo-org/docs-site:pull_request]`
- [ ] `TRUSTS` edges exist exactly for deploy to `github-deploy`, deploy to `terraform-apply`, and preview to `github-deploy`
- [ ] `pytest -q` and `ruff check .` pass, and `AI_USE.md` has this task's line

## Out of scope

- The finding endpoint (FM3)

## Prompt for your agent

> You are working on task `FM1` in the Theseus repo. Read `AGENTS.md`, then `docs/tasks/FM1.md`,
> then every spec section it lists under "Read first". Work only in the files the brief lists. Write the
> tests under "Done when" first, then the code, until `pytest -q` and `ruff check .` pass. If anything in
> the spec is unclear, stop and ask instead of guessing. Finish by drafting the PR description, including
> any check you could not run, and the `AI_USE.md` line.
