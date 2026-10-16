# Task briefs

Every agent task on the GitHub board has a brief here. A brief tells a person or an agent the feature, why it
matters, which spec sections to read, which files to create or change and what each one is for, the steps,
when it is done, and what is out of scope. Human tasks (prep checks, `expected.json`, the gates, the video,
the submission) are in [human-tasks.md](human-tasks.md).

Which task waits on which, colored by phase, with the critical path marked: [dependencies.md](dependencies.md).
Regenerate it with `python tools/dep_graph.py` whenever `tools/tasks.csv` changes.

## Setting up the board

1. Clone the repo and turn on the commit check: `git config core.hooksPath .githooks`.
2. Give `gh` the project scope once: `gh auth refresh -s project`.
3. Preview: `python tools/make_board.py --repo OWNER/theseus --dry-run`.
4. Create the labels (including `demo`), milestones, issues and the project: `python tools/make_board.py --repo OWNER/theseus`.
5. Start F1 together; it adds the package skeleton. Then F2 and F4 in parallel.
6. When a task changes, change `tools/tasks.csv`, the brief and `docs/plan-of-action.md` together, then re-run `python tools/dep_graph.py`.

## How to use a brief

1. Claim the issue on the board and open `docs/tasks/<ID>.md`.
2. Give your agent the prompt at the bottom of the brief. It reads `AGENTS.md`, the brief, and the listed spec sections.
3. Review the PR against the brief's "Done when" list, then merge.

## What each brief contains

| Section | What it settles |
| --- | --- |
| The feature | What exists when the task is done, in one paragraph |
| Why it matters | The story beat or judge question it serves |
| Read first | The exact spec sections; nothing else is needed |
| Files | Every file to create or change, and the purpose of each |
| Steps | The order to work in, tests first |
| Done when | The checks that decide the task is finished |
| Out of scope | What belongs to another task |
| Prompt for your agent | The words to paste |

## Foundation

**Goal:** The contracts are frozen, `demo-infra/` plans cleanly, the fixtures exist, and a demo PR gets a stub comment from the live URL.

| Task | Feature | Files it creates | It achieves | Needs first |
| --- | --- | --- | --- | --- |
| [F1](F1.md) | Repo, board and CI | `pyproject.toml`, `theseus/__init__.py`, `theseus/__main__.py`, `theseus/cli.py` | CI is green on the first PR | P5 |
| [F2](F2.md) | Freeze the contracts | `theseus/contracts/schema.py`, `theseus/contracts/result.py`, `theseus/contracts/engine.py` | Both humans reviewed and approved | F1 |
| [F3](F3.md) | Run it: Compose, API stub and VM deploy | `deploy/docker-compose.yml`, `deploy/Dockerfile`, `deploy/Caddyfile` | `docker compose -f deploy/docker-compose.yml --profile dev up -d` starts FalkorDB | F2 |
| [F4](F4.md) | Demo world and fixture generator | `demo-infra/README.md`, `demo-infra/terraform/providers.tf`, `demo-infra/terraform/people.tf`, `roles.tf`, `policies.tf`, `ci.tf`, `data.tf`, `services.tf`, `containers.tf` | `terraform plan` gives JSON for `demo-infra/terraform` with no AWS account | F1 |
| [F7](F7.md) | GitHub Action and App skeleton | `.github/workflows/theseus.yml`, `theseus/api/github.py`, `tests/unit/test_github.py` | The trial PR gets a stub comment from the live URL | F2, F3 |

## Beat 1: See it

**Goal:** Gate 1: the intern PR shows three opened paths and says versus grants, live.

| Task | Feature | Files it creates | It achieves | Needs first |
| --- | --- | --- | --- | --- |
| [E1](E1.md) | Importer: plan, structure, workloads and coverage | `theseus/importer/world.py`, `theseus/adapters/terraform/plan.py`, `theseus/adapters/terraform/source_index.py` | Intern base has 4 users, 3 groups, 11 roles, 6 workloads, 19 resources and 17 requirements; head adds exactly one `MEMBER_OF` edge | F2, F4 |
| [E2](E2.md) | IAM: statements, matching, CAN and CAN_ASSUME | `theseus/adapters/aws/iam.py`, `theseus/adapters/aws/policies.py`, `theseus/adapters/aws/managed.py` | All unit tests pass | F2 |
| [E3](E3.md) | Graph load, path diff and required access | `theseus/graph/store.py`, `theseus/graph/load.py`, `theseus/graph/queries.py` | `analyze` on the intern fixture matches `expected.json` for opened, closed and R1 to R17 | E1, E2, F3, F5 |
| [A1](A1.md) | LLM intent extraction | `theseus/agent/llm.py`, `theseus/agent/intent.py`, `tests/replay/test_intent.py` | Replay tests pass on 10 PR texts | F2 |
| [A2](A2.md) | Jev: sensitivity labels and advisory urgency | `theseus/agent/jev.py`, `theseus/agent/sensitivity.py`, `tests/replay/test_sensitivity.py` | Every demo resource is rated and cached | F2 |
| [A3](A3.md) | Says versus grants | `theseus/engine/intent_effect.py`, `tests/unit/test_intent_effect.py` | The intern headline names `customer-db` | E3, A1 |
| [A4](A4.md) | PR comment: paths, fix table, trace and coverage | `theseus/agent/templates/comment.md`, `theseus/agent/render.py`, `tests/unit/test_render.py` | Renders from every `expected.json` | F2 |
| [A5](A5.md) | Real analyze behind the Action | `tests/e2e/test_analyze_route.py` | On a real `demo/intern-1` PR the comment shows the headline and three opened paths | E3, A3, A4, F7 |
| [FM1](FM1.md) | CI in the graph: workflows and OIDC trust | `theseus/adapters/github/workflows.py`, `theseus/adapters/aws/oidc.py`, `tests/unit/adapters/github/test_workflows.py` | `preview.yml` has `id_token` true and `subs` `[repo:demo-org/docs-site:pull_request]` | F4, E2 |
| [C1](C1.md) | Demo backend: service code and platform resources | `demo-infra/services/orders_api/app.py`, `store.py`, `events.py`, `billing.py`, `demo-infra/services/orders_worker/worker.py`, `fulfil.py`, `demo-infra/services/billing_job/handler.py`, `invoices.py`, `payments.py` | Every resource name in the code comes from an environment variable | F4 |

## Beat 2: Fix it

**Goal:** Gate 2: minimum cut, four tested fixes, `/theseus apply B` commits, and the check turns green.

| Task | Feature | Files it creates | It achieves | Needs first |
| --- | --- | --- | --- | --- |
| [E4](E4.md) | Minimum cut with MaxFlow | `theseus/engine/mincut.py`, `theseus/graph/algos.py`, `tests/unit/test_mincut.py` | Intern max flow is 1,000,000; the Action's is 1, with the right cut edge | E3 |
| [E5](E5.md) | Simulator on GRAPH.COPY | `theseus/adapters/aws/patch.py`, `theseus/engine/simulate.py`, `tests/unit/test_patch.py` | Each candidate gets a verdict | E3 |
| [E6](E6.md) | Rule-based fixes and ranking | `theseus/engine/candidates.py`, `tests/golden/test_public_bucket.py`, `tests/unit/test_ranking.py` | For the intern: A fails, C is UNKNOWN, D fails | E5 |
| [E9](E9.md) | Terraform patch renderer | `theseus/adapters/terraform/render.py`, `tests/unit/adapters/terraform/render/` | Every op renders and the result parses | F2, F4 |
| [A6](A6.md) | MCP server and tool trace | `theseus/mcp/tools.py`, `theseus/agent/trace.py`, `theseus/mcp/server.py` | Claude Code lists and calls every tool on the fixtures | F2 |
| [A7](A7.md) | LLM fix agent | `theseus/agent/fixer.py`, `theseus/agent/evidence.py`, `tests/replay/test_fixer.py` | Fix B verified | E5, A6 |
| [A9](A9.md) | /theseus apply command | `theseus/api/webhooks.py`, `tests/unit/test_webhooks.py` | On a `demo/` PR, `/theseus apply <ID>` commits the rendered fix and the Action re-runs | F7, E9 |
| [C2](C2.md) | Python code reader | `theseus/adapters/python/code.py`, `tests/unit/adapters/python/test_code.py` | Every call in the backend becomes an edge, a counted skip or an unknown | F2, C1 |
| [FM3](FM3.md) | Finding mode: blast radius and rotate list | `theseus/engine/finding.py`, `tests/golden/test_compromised_action.py` | The five-hop trace to `customer-db` | FM1, E3 |
| [FM4](FM4.md) | Finding extras: choke points, staging to prod, urgency | `theseus/engine/staging.py` | `prod-support` ranks first among roles | FM3, E4, A2 |

## Beats 3 and 4: Contain it, Nobody breaks

**Goal:** Gate 3: a compromised Action is contained with one PR and a rotate list; a grant no code calls is found and removed safely; the typo PR is flagged.

| Task | Feature | Files it creates | It achieves | Needs first |
| --- | --- | --- | --- | --- |
| [FM6](FM6.md) | Containment PR | `tests/unit/test_containment_pr.py` | A containment PR opens in this repo with only `ci.tf` changed | FM3, E4, E5, E9, A9 |
| [C3](C3.md) | Unused grants, with usage capacities | `theseus/engine/usage.py`, `tests/golden/test_unused_grant.py` | The cut lands on the unused grant | C2, E4, E5 |
| [C4](C4.md) | Use beyond intent | `tests/golden/test_code_pr.py` | Flagged on the code-PR fixture | C2, A3 |

## Ship

**Goal:** Benchmark and timings, Try-it, README, video, submission.

| Task | Feature | Files it creates | It achieves | Needs first |
| --- | --- | --- | --- | --- |
| [S2](S2.md) | Proof: benchmark against Checkov, and large-graph timings | `bench/cases/<id>/`, `bench/run.py`, `bench/checkov.py` | A table of catches and misses | E4, E5 |
| [S4](S4.md) | Try-it page | `theseus/web/index.html`, `app.js`, `style.css`, `tests/unit/test_try.py` | Works on the live URL | A5 |
| [S5](S5.md) | README | `README.md` | A fresh clone runs with one command | G2, G3 |

## Merged task IDs

Small tasks that edit the same files were folded into one agent session each: fewer PRs to review, no two
branches fighting over one file, and one golden test per beat. These IDs are retired.

| Retired | Now part of | Why |
| --- | --- | --- |
| P2 | P1 | Terraform plan with mock credentials is part of the throwaway checks |
| F6 | F3 | Compose, the API stub and the VM deploy share one file and one person |
| FM2 | FM1 | OIDC matching needs the workflow importer's `subs`; one session does both |
| FM5 | FM3 | The rotate list is one query over the blast radius |
| E7 | FM4 | Staging-to-prod, choke points and urgency are extras on the same result, off the critical path |
| FM7 | A2, FM4 | The urgency question rides the Jev client (A2); FM4 puts it in the result |
| E8 | C3 | Usage capacities and unused grants share one golden test |
| A8 | A4 | The stub result already has candidates, so the fix table renders from the start |
| A10 | A6, A4 | The recorder wraps the tool registry (A6); the comment shows it (A4) |
| S1 | G1, G2, G3 | A backup clip is recorded at each gate |
| S3 | S2 | Benchmark and timings share `bench/` and run together on the VM |
