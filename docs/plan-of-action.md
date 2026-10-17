# Plan of action

**We ship four story beats, each ending in an action the agent takes, and we build them as tasks either of us can pick up and finish end to end.** The story decides the scope, and the task board decides who does what. The drawing shows which tasks run side by side and which wait for a gate.

## What we ship and why it matters

**We ship an agent that reviews each Terraform pull request as a graph, shows which sensitive data the change makes reachable, and acts on it.** It explains the path, proves the smallest safe fix and commits it once a person approves. Given a security finding, such as a compromised GitHub Action, it opens a containment PR and lists exactly which secrets to rotate.

| Who | Today | With Theseus |
| --- | --- | --- |
| Developer | Waits for a security review, or merges without one | One comment per PR, about 20 seconds in the PoC, with the fix already tested |
| Security reviewer | Traces group, role, bucket, secret and database by hand | Reads a cited path and approves a proven fix |
| CTO or platform lead | Learns about over-grants after an incident or an audit | Sees each change's effect before merge, with evidence an auditor can read |
| Incident responder | Rotates every secret after a supply-chain compromise | Rotates only the secrets the compromised workflow could reach |

### What a CTO judge will ask

Assume every judge runs a large engineering org and has lived through this problem. Each answer needs something they can see in the demo, and both of us should be able to give any of them (task P7).

| Question | Our answer | What we show |
| --- | --- | --- |
| What does it prevent? | Access that creeps in through changes no rule flags: group membership, role trust, CI OIDC trust | Beat 1: Checkov passes, Theseus shows the path to customer-db |
| Checkov or AWS checks already catch this. | Not this PR: it changes no policy. Checkov passes, and AWS's policy checks have nothing to check | Checkov run in the same GitHub Action, its result beside ours |
| Cartography, SubImage and Wiz exist. Why you? | They map what exists. Theseus reviews what a change will do before merge, compares it with what the PR says and what the code calls, and proves the smallest fix | Fixes tested on graph copies; the three sources of truth |
| Why a graph, and why FalkorDB? | The risk is a path four or five hops long, and rule engines read one resource at a time. FalkorDB keeps one graph per state with `GRAPH.COPY` and runs MaxFlow inside the database. Stop the container and every check fails | The Mermaid path, the graph list, the Cypher in the README, timings |
| Why is this an agent and not a CI script? | The agent picks its tools, reads the minimum cut, designs fixes rules can't, and retries when one fails. Only the final gate is fixed rules, on purpose | The MCP tool trace, and a retry that runs in the demo |
| Can I trust an AI's verdict? What if it invents a permission? | The models suggest. The engine decides what is reachable, every claim cites an evidence ID, a checker rejects unknown IDs, and every fix is re-checked on a graph copy | Evidence links and the fix table with verdicts |
| What stops it committing something harmful? | The model has no write tools. A commit needs a reviewer's command and a fix that passed the gate, and the GitHub App reaches only the demo repos | The wiring, shown in the README |
| Can PR text or an advisory inject instructions? | Outside text reaches the model only as data, is scanned, and never counts as evidence. Even a PR that openly asks for sensitive data cannot approve it: only `theseus.yaml` can | The injection cases in the replay tests; a PR asking for `customer-db` stays flagged |
| What about KMS, SCPs, permission boundaries and conditions? | We model allows, explicit denies, wildcards, assume-role and KMS decrypt. Everything else returns UNKNOWN instead of a guess | Fix C returns UNKNOWN in Beat 2 |
| Does a path prove an attacker can get in? | No. It is a modeled path under labeled assumptions | Edges marked configured, inferred or assumed |
| Will it slow developers or flood them? | One comment per PR, and only for paths to sensitive data. About 20 seconds per PR in the PoC | The timing in the comment, and false alarms counted in the benchmark |
| How accurate is it? | Measured on about 20 PRs against Checkov, misses included. We wrote the PRs ourselves and say so | The benchmark table |
| Does it scale? | One graph per state in FalkorDB; candidate fixes run on graph copies | Timings on a large generated graph |
| What access does it need? | The repo and the plan JSON the CI already produces. It holds no cloud credentials | The architecture slide and the README |
| Why two models, and why Jev? | Jev makes fast typed judgments with probabilities, such as whether a resource is sensitive: 30 of 30 resource names right in the PoC, about a third of a second per call. The LLM (GLM 5.3 through LiteLLM) proposes and explains. Neither decides facts | Jev's numbers in the README |
| Who writes the required access? | A short `theseus.yaml` today. The code-aware graph can draft it from what the code calls, and a person prunes it | The yaml in the demo repo |
| Does passing the required-access check mean nothing breaks? | No: the declared needs still hold within the supported model. Beat 4 adds the code's own calls as evidence | Beat 4 |
| Who would buy this? | Platform teams who own the fix. It complements SubImage or Wiz; its edge is fixes that keep the app working | One honest slide, no market-size numbers |

## What Track 01 asks for

**The track page names five focus areas and no scoring rubric, so every beat must show at least two of them.** Its prize line is "for the best agent that uses a graph to make decisions and take action" ([hackathon page](https://www.wemakedevs.org/hackathons/falkordb)).

| Focus area (track page) | How Theseus shows it | Beats |
| --- | --- | --- |
| Multi-hop reasoning | Intern to group to role to bucket and secret to database; Action to workflow to OIDC role to database | 1, 3 |
| Graph queries and algorithms as agent tools | Path queries, MaxFlow, betweenness and BFS, each wrapped as an MCP tool | 2, 3, 4 |
| Tool selection through MCP | The LLM chooses among blast radius, minimum cut, simulate and code-use tools, and the tool trace is shown | 2, 3, 4 |
| Actions based on what the graph shows | A PR comment, a committed fix, a containment PR, a rotation list | All |
| Explainable results | Every step cites a file and line, and each fix says why it passed or failed | All |

## The story: four beats

**Each beat is one scene in the video, one fixture and one `expected.json`, and each ends with the agent doing something.** We write the video script first (task P4) and build the beats in order, so wherever time runs out, the video is finished up to that beat.

| Beat | What the judge sees | What the agent does | Phase |
| --- | --- | --- | --- |
| 1. See it | The intern PR: "Your PR says logs. Your change grants the customer database." Checkov passes | Posts the cited path on the PR | 1 |
| 2. Fix it | The minimum cut, and four fixes tested on graph copies | Commits fix B after `/theseus apply B` | 1 |
| 3. Contain it | A compromised Action reaches customer-db through a staging workflow | Opens a containment PR and lists the secrets to rotate | 2 |
| 4. Nobody breaks | The code never calls the grant that opens the path | Proposes removing it: the fix that breaks nobody | 3 |
| Close | One graph, three teams | Roadmap: survives the outage, dead stacks and their cost, live accounts | 4 and 5 |

Demo 1, the public bucket, becomes a preset on the Try-it page instead of a scene.

## Parallel or in order

**Stages run in order and each ends at a gate; the four lanes inside a stage run side by side.** The first stage is the only one we do together, because everything else plugs into the contracts it freezes.

![Four lanes, five stages, a gate after each stage](images/stages-and-lanes.png)

Read across a stage for what runs at the same time, and down for what waits on a gate.

- **Critical path:** F1, F4 demo world, E1 importer, E3 analyze, E5 simulator, E6 rule fixes, Gate 2, Gate 3, the README, then submission. F2 contracts and F5 expected.json run beside F4. Whoever is free helps there first.
- **Can run ahead:** the Finding and Code lanes block nothing until Beats 3 and 4, so they fill gaps beside the critical path.
- **Suggested owners:** A takes Engine and Code, B takes Agent and GitHub plus Finding. Either of us can claim any task on the board.

### Which task waits on which

**The top row needs nothing, F1 starts the build, and the longest chain to submission runs P5, F1, F4, E1, E3, E5, E6, G2, G3, S5, S7.** Each arrow points from a task to one that needs it merged first; arrows implied by a longer route are left out. The same graph comes from `tools/tasks.csv`.

![Task dependencies: 44 tasks colored by phase, critical path in dark](images/task-dependencies.png)

The picture is a snapshot. The up-to-date version is [tasks/dependencies.md](tasks/dependencies.md), regenerated from `tools/tasks.csv` by `python tools/dep_graph.py`.

The demo world (F4) and the engine core (E1, E3, E5, E6) sit on the critical path. F2 and F5 no longer do: F4 needs only the repo, E1 needs only the generated fixtures, and the apply command and the containment PR no longer wait for E6, because the renderer (E9) needs only the op contract. Measured to the containment PR, the longest chain is about a quarter shorter than in the first plan.

## Agent kit: what Claude and Codex read

**Every agent works from three things in the repo, so it never has to guess: `AGENTS.md`, its task's brief, and the spec sections that brief lists.** We wrote them before the event as notes (rule 8 allows notes and sketches), and they are the first commits of the private repo, [AjinkyaTaranekar/theseus](https://github.com/AjinkyaTaranekar/theseus). This plan and the [project overview](project-overview.md) live in `docs/` beside them, so every decision stays in the repo.

| File | What it gives the agent |
| --- | --- |
| `AGENTS.md` (`CLAUDE.md` imports it) | Commands first, then Always, Ask first and Never boundaries, code conventions with one example, tests, the definition of done, the commit and pull request rules, where to look, and the start prompt. Codex reads it directly and Claude Code through CLAUDE.md, where a hook blocks writes to expected.json and .env. demo-infra/AGENTS.md adds the demo world's own rules |
| `docs/spec/` (7 files) | What Theseus does; the demo world with every name and the five scenarios' expected outcomes; the graph schema and canonical Cypher; every engine rule; the full file skeleton and shared models; LLM and Jev prompts; GitHub and deployment |
| `docs/tasks/<ID>.md` (31 briefs) | The feature, why it matters, the spec sections to read, each file to create or change and its purpose, steps, done when, out of scope, and the prompt to paste |
| `docs/tasks/README.md` | Every task by stage, with the files it creates and what it achieves; how to set up the board; which IDs were merged and why |
| `docs/tasks/human-tasks.md` | The 13 tasks only people do: prep checks, expected.json, the three gates, the video and the submission |

**How a task runs:** claim the issue (its body links the brief), paste the brief's prompt into Claude Code or Codex, let the agent write the tests first and then the code, and the other person reviews against "Done when" before merging. The prompt:

> You are working on task `<ID>` in the Theseus repo. Read `AGENTS.md`, then `docs/tasks/<ID>.md`, then every spec section it lists under "Read first". Work only in the files the brief lists. Write the tests under "Done when" first, then the code, until `pytest -q` and `ruff check .` pass. If anything in the spec is unclear, stop and ask instead of guessing. Finish by drafting the PR description, including any check you could not run, and the `AI_USE.md` line.

**Decisions the kit settles, so agents never invent them:**

- Every name in the demo world (137 resources and eight services), from Terraform addresses to statement Sids, and each scenario's expected outcome. The world lives in demo-infra/ in this repo; demo PRs change only that folder, and the App may write only there.
- The IAM subset, and that everything outside it is UNKNOWN.
- Capacities: 1,000,000 for required routes and non-permission edges, 1,000 for grants the code uses, 1 otherwise.
- Candidate IDs: A revert, B the LLM, C conditional Deny, D cut the shared hop, S scope down, K containment, U unused grant.
- `expected.json` holds only the compared fields, and only people write it.
- An in-memory graph store exists for offline tests only; the product refuses to run without FalkorDB (rule 3).
- Every LLM call goes through one wrapper with record and replay; the fix agent never sees PR text.

### What each stage builds

**Each agent task creates these files; its brief lists every file, its purpose and its tests.** "Changes" names files another task created first.

**Foundation**

| Task | Creates | Changes |
| --- | --- | --- |
| F1 Repo, board and CI | `pyproject.toml`, `theseus/__init__.py`, `theseus/__main__.py`, `theseus/cli.py`, `theseus/errors.py`, `theseus/config.py`, `tests/conftest.py`, `tests/unit/test_config.py`, `.github/workflows/ci.yml`, `.github/pull_request_template.md`, `.github/CODEOWNERS`, `.env.example`, `LICENSE`, `AI_USE.md` | none |
| F2 Freeze the contracts | `theseus/contracts/schema.py`, `theseus/contracts/result.py`, `theseus/contracts/engine.py`, `tests/contract/test_models.py` | none |
| F3 Run it: Compose, API stub and VM deploy | `deploy/docker-compose.yml`, `deploy/Dockerfile`, `deploy/Caddyfile`, `deploy/deploy.sh`, `deploy/README.md`, `theseus/graph/client.py`, `theseus/api/app.py`, `theseus/api/routes.py`, `theseus/api/stub.py`, `tests/data/stub_expected.json`, `tests/integration/test_falkordb_smoke.py`, `tests/unit/test_api_stub.py` | none |
| F4 Demo world and fixture generator | `demo-infra/README.md`, `demo-infra/terraform/providers.tf`, `people.tf`, `roles.tf`, `policies.tf`, `ci.tf`, `data.tf`, `services.tf`, `containers.tf`, `demo-infra/theseus.yaml`, `demo-infra/workflows/demo-org/` (four workflows), `demo-infra/services/<six folders>/__init__.py`, `tools/plan.sh`, `tools/make_fixture.py`, `fixtures/intern/`, `public-bucket/`, `compromised-action/`, `unused-grant/`, `tests/unit/test_demo_world.py` | none |
| F7 GitHub Action and App skeleton | `.github/workflows/theseus.yml`, `theseus/api/github.py`, `tests/unit/test_github.py` | `theseus/api/routes.py` |

**Beat 1: See it**

| Task | Creates | Changes |
| --- | --- | --- |
| E1 Importer: plan, structure, workloads and coverage | `theseus/importer/world.py`, `build.py`, `theseus/adapters/terraform/plan.py`, `source_index.py`, `adapter.py`, `theseus/adapters/aws/resources.py`, `adapter.py`, `tests/unit/importer/`, `tests/unit/adapters/` | none |
| E2 IAM: statements, matching, CAN and CAN\_ASSUME | `theseus/adapters/aws/iam.py`, `policies.py`, `managed.py`, `access.py`, `tests/unit/adapters/aws/test_iam.py`, `test_policies.py`, `test_access.py` | `theseus/adapters/aws/adapter.py` |
| E3 Graph load, path diff and required access | `theseus/graph/store.py`, `load.py`, `queries.py`, `theseus/engine/analyze.py`, `pipeline.py`, `tests/golden/test_intern.py`, `test_main.py`, `tests/integration/test_store_parity.py` | `theseus/cli.py` |
| A1 LLM intent extraction | `theseus/agent/llm.py`, `intent.py`, `tests/replay/intents.yaml`, `recordings/llm/intent-*.json`, `tests/replay/test_intent.py` | none |
| A2 Jev: sensitivity labels and advisory urgency | `theseus/agent/jev.py`, `sensitivity.py`, `tests/replay/test_sensitivity.py`, `test_triage.py` | none |
| A3 Says versus grants | `theseus/engine/intent_effect.py`, `tests/unit/test_intent_effect.py` | `theseus/engine/pipeline.py`, `tests/golden/test_intern.py` |
| A4 PR comment: paths, fix table, trace and coverage | `theseus/agent/templates/comment.md`, `theseus/agent/render.py`, `tests/unit/test_render.py` | none |
| A5 Real analyze behind the Action | `tests/e2e/test_analyze_route.py` | `theseus/importer/world.py`, `theseus/api/routes.py` |
| FM1 CI in the graph: workflows and OIDC trust | `theseus/adapters/github/workflows.py`, `theseus/adapters/aws/oidc.py`, `tests/unit/adapters/github/test_workflows.py`, `tests/unit/adapters/aws/test_oidc.py` | `theseus/adapters/github/adapter.py`, `theseus/adapters/aws/adapter.py` |
| C1 Demo backend: service code and platform resources | `demo-infra/services/` (six services, 17 modules), `demo-infra/terraform/network.tf`, `platform.tf` | `tools/make_fixture.py`, `fixtures/*/` |

**Beat 2: Fix it**

| Task | Creates | Changes |
| --- | --- | --- |
| E4 Minimum cut with MaxFlow | `theseus/engine/mincut.py`, `theseus/graph/algos.py`, `tests/unit/test_mincut.py`, `tests/golden/test_mincut_fixtures.py` | `theseus/engine/pipeline.py`, `theseus/graph/store.py` |
| E5 Simulator on GRAPH.COPY | `theseus/adapters/aws/patch.py`, `theseus/engine/simulate.py`, `tests/unit/adapters/aws/test_patch.py`, `tests/golden/test_simulate_intern.py` | `theseus/graph/load.py` |
| E6 Rule-based fixes and ranking | `theseus/engine/candidates.py`, `theseus/adapters/aws/changes.py`, `tests/unit/adapters/aws/test_changes.py`, `tests/golden/test_public_bucket.py`, `tests/unit/test_ranking.py` | `theseus/engine/pipeline.py`, `tests/golden/test_intern.py` |
| E9 Terraform patch renderer | `theseus/adapters/terraform/render.py`, `tests/unit/adapters/terraform/render/` | `theseus/adapters/terraform/adapter.py` |
| A6 MCP server and tool trace | `theseus/mcp/tools.py`, `server.py`, `theseus/agent/trace.py`, `.mcp.json`, `tests/unit/test_mcp_tools.py`, `test_trace.py` | none |
| A7 LLM fix agent | `theseus/agent/fixer.py`, `evidence.py`, `recordings/llm/fix-*.json`, `tests/replay/test_fixer.py` | none |
| A9 /theseus apply command | `theseus/api/webhooks.py`, `tests/unit/test_webhooks.py` | `theseus/api/github.py`, `theseus/api/routes.py` |
| C2 Python code reader | `theseus/adapters/python/code.py`, `tests/unit/adapters/python/test_code.py` | `theseus/adapters/python/adapter.py` |
| FM3 Finding mode: blast radius and rotate list | `theseus/engine/finding.py`, `tests/golden/test_compromised_action.py` | `theseus/engine/pipeline.py`, `theseus/api/routes.py`, `theseus/cli.py` |
| FM4 Finding extras: choke points, staging to prod, urgency | `theseus/engine/staging.py` | `theseus/graph/algos.py`, `theseus/engine/pipeline.py`, `tests/golden/test_compromised_action.py`, `tests/golden/test_intern.py` |

**Beats 3 and 4: Contain it, Nobody breaks**

| Task | Creates | Changes |
| --- | --- | --- |
| FM6 Containment PR | `tests/unit/test_containment_pr.py` | `theseus/engine/finding.py`, `theseus/api/github.py`, `theseus/api/routes.py`, `tests/golden/test_compromised_action.py` |
| C3 Unused grants, with usage capacities | `theseus/engine/usage.py`, `tests/golden/test_unused_grant.py` | `theseus/engine/mincut.py`, `simulate.py`, `pipeline.py`, `theseus/api/routes.py`, `theseus/cli.py` |
| C4 Use beyond intent | `tests/golden/test_code_pr.py` | `theseus/engine/usage.py` (creates it if C3 has not), `theseus/engine/pipeline.py` |

**Ship**

| Task | Creates | Changes |
| --- | --- | --- |
| S2 Proof: benchmark against Checkov, and large-graph timings | `bench/cases/<id>/`, `bench/run.py`, `checkov.py`, `scale.py`, `report.md` | none |
| S4 Try-it page | `theseus/web/index.html`, `app.js`, `style.css`, `tests/unit/test_try.py` | `theseus/api/routes.py` |
| S5 README | `README.md` | none |

## The task board

**Every row is one GitHub issue: one branch and one PR, with the title starting with the ID.** "Needs first" lists what must be merged before you start. Sizes are relative effort with agents doing the typing: S small, M medium, L large. The ID letters name the lane: P prep, F foundation, E engine, A agent and GitHub, FM finding mode, C code-aware, G gate, S story and proof. There are 44 tasks: 31 have an agent brief, and 13 are done by people.

### Prep: notes and throwaway checks only (rule 8)

| ID | Task | Lane | Needs first | Done when | Size |
| --- | --- | --- | --- | --- | --- |
| P1 | Throwaway checks: FalkorDB and Terraform plan (people) | Prep | nothing | Every check returns a result, and the notes are written | M |
| P3 | Check the five scenarios on paper (people) | Prep | nothing | We both agree on every expected path | S |
| P4 | Finalize the video script (people) | Prep | P3 | Read aloud, and its length noted | S |
| P5 | Check access and keys (people) | Prep | nothing | Each one tested once | S |
| P6 | Register the team and agree IP ownership (people) | Prep | nothing | Registered, and the agreement signed by both of us | S |
| P7 | Rehearse the judge questions (people) | Prep | P3 | Each of us answers every question | S |

### Foundation

| ID | Task | Lane | Needs first | Done when | Size |
| --- | --- | --- | --- | --- | --- |
| F1 | Repo, board and CI | Foundation | P5 | CI is green on the first PR | S |
| F2 | Freeze the contracts | Foundation | F1 | Both humans reviewed and approved | M |
| F4 | Demo world and fixture generator | Foundation | F1 | `terraform plan` gives JSON for `demo-infra/terraform` with no AWS account | L |
| F3 | Run it: Compose, API stub and VM deploy | Foundation | F2 | FalkorDB starts in Compose, the stub API is live over HTTPS | M |
| F5 | Hand-write expected.json (people) | Foundation | F4, P3 | We both sign off every expected.json | M |
| F7 | GitHub Action and App skeleton | Foundation | F2, F3 | The trial PR gets a stub comment from the live URL | M |

### Beat 1: See it

| ID | Task | Lane | Needs first | Done when | Size |
| --- | --- | --- | --- | --- | --- |
| E1 | Importer: plan, structure, workloads and coverage | Engine | F2, F4 | Intern base has 4 users, 3 groups, 11 roles, 6 workloads, 19 resources and 17 requirements; head adds exactly one `MEMBER_OF` edge | L |
| E2 | IAM: statements, matching, CAN and CAN\_ASSUME | Engine | F2 | All unit tests pass, including attached and shared managed policies | L |
| E3 | Graph load, path diff and required access | Engine | E1, E2, F3, F5 | `analyze` on the intern fixture matches `expected.json` for opened, closed and R1 to R17 | M |
| A1 | LLM intent extraction | Agent and GitHub | F2 | Replay tests pass on 10 PR texts | M |
| A2 | Jev: sensitivity labels and advisory urgency | Agent and GitHub | F2 | Every demo resource is rated and cached | M |
| A3 | Says versus grants | Agent and GitHub | E3, A1 | The intern headline names `customer-db` | S |
| A4 | PR comment: paths, fix table, trace and coverage | Agent and GitHub | F2 | Renders from every `expected.json` | L |
| A5 | Real analyze behind the Action | Agent and GitHub | E3, A3, A4, F7 | On a real `demo/intern-1` PR the comment shows the headline and three opened paths | S |
| FM1 | CI in the graph: workflows and OIDC trust | Finding mode | F4, E2 | `preview.yml` has `id_token` true and `subs` `[repo:demo-org/docs-site:pull_request]` | M |
| C1 | Demo backend: service code and platform resources | Code-aware | F4 | Every resource name in the code comes from an environment variable | L |
| G1 | Gate 1: Beat 1 live (people) | Gate | A5 | The live comment shows three opened paths and says versus grants; the clip is saved | S |

### Beat 2: Fix it

| ID | Task | Lane | Needs first | Done when | Size |
| --- | --- | --- | --- | --- | --- |
| E4 | Minimum cut with MaxFlow | Engine | E3, A3 | Intern max flow is 1,000,000; the Action's is 1, with the right cut edge | M |
| E5 | Simulator on GRAPH.COPY | Engine | E3 | Each candidate gets a verdict | M |
| E6 | Rule-based fixes and ranking | Engine | E5 | For the intern: A fails, C is UNKNOWN, D fails | M |
| E9 | Terraform patch renderer | Engine | F2, F4 | Every op renders and the result parses | M |
| A6 | MCP server and tool trace | Agent and GitHub | F2 | Claude Code lists and calls every tool on the fixtures | M |
| A7 | LLM fix agent | Agent and GitHub | E5, A6 | Fix B verified | M |
| A9 | /theseus apply command | Agent and GitHub | F7, E9 | On a `demo/` PR, `/theseus apply <ID>` commits the rendered fix and the Action re-runs | M |
| C2 | Python code reader | Code-aware | F2, C1 | Every call in the backend becomes an edge, a counted skip or an unknown | L |
| FM3 | Finding mode: blast radius and rotate list | Finding mode | FM1, E3 | The five-hop trace to `customer-db` | M |
| FM4 | Finding extras: choke points, staging to prod, urgency | Finding mode | FM3, E4, A2 | `prod-support` ranks first among roles | M |
| G2 | Gate 2: Demo 2 end to end (people) | Gate | G1, E4, E6, A7, A9 | The check turns green after the apply; the clip is saved | S |

### Beats 3 and 4: Contain it, Nobody breaks

| ID | Task | Lane | Needs first | Done when | Size |
| --- | --- | --- | --- | --- | --- |
| FM6 | Containment PR | Finding mode | FM3, E4, E5, E9, A9 | A containment PR opens in this repo with only `ci.tf` changed | M |
| C3 | Unused grants, with usage capacities | Code-aware | C2, E4, E5 | The cut lands on the unused grant | M |
| C4 | Use beyond intent | Code-aware | C2, A3 | Flagged on the code-PR fixture | S |
| G3 | Gate 3: Contain it and nobody breaks (people) | Gate | G2, FM4, FM6, C3, C4 | All three run live; the clips are saved | S |

### Ship

| ID | Task | Lane | Needs first | Done when | Size |
| --- | --- | --- | --- | --- | --- |
| S2 | Proof: benchmark against Checkov, and large-graph timings | Story and proof | E4, E5 | A table of catches and misses | L |
| S4 | Try-it page | Story and proof | A5 | Works on the live URL | M |
| S5 | README | Story and proof | G2, G3 | A fresh clone runs with one command | M |
| S6 | Final video (people) | Story and proof | G3, P4 | Uploaded | M |
| S7 | Tag the release and submit (people) | Story and proof | S5, S6 | Submitted | S |
| S8 | Blog post (people) | Story and proof | S6 | Published after submission | M |

### Merged task IDs

Small tasks that edit the same files became one agent session each, as long as that kept side work off the critical path. These IDs are retired:

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

## How we work the board

**Agents write the code; we own the contracts, the expected results and the review.** That split is what keeps fast code correct, and it is what rules 11 to 13 ask of us.

1. **Claim:** assign yourself on the issue and move it to In progress. At most two tasks in progress per person, one per agent.
2. **Build:** one branch per task, named after its ID (`e4-min-cut`), kept short. Agents read AGENTS.md, the task's brief in docs/tasks/, and the spec sections it lists. Commits and PR titles read `<type>: <Summary>` (feat, fix, docs, test, refactor, chore) with no task ID, and the commit-msg hook checks every message.
3. **Done:** the "Done when" check passes in CI, and the other person has read the diff before merging. CI must pass to merge, so `main` is always deployable.
4. **Folders:** `CODEOWNERS` maps each folder to its lane owner. The other person reviews, but rarely edits.
5. **Contracts:** frozen once both of us approve F2, and after that they only grow. A change is a tiny PR that adds fields, agreed by both of us and merged before other work continues.
6. **Stubs both ways:** the Agent lane builds against `expected.json` through a stub engine; the Engine lane builds against pytest and fixtures, never against the live app.
7. **Expected results:** every `expected.json` is written by us, never by an agent. A owns the fixtures, and B asks A to change one. B owns Compose and the environment files.
8. **Demo PRs:** branch `demo/<scenario>-<take>`, label `demo`, changing only `demo-infra/`. Practise on one branch, then record the video on a fresh one.
9. **Deploy:** every merge to `main` deploys to the VM. If a deploy breaks, revert first and debug second.
10. **AI log:** `AI_USE.md` records which agent wrote what in each task, for the disclosure in rule 11.
11. **Rhythm:** a sync at the start of each working session to plan and agree contract changes, a joint run at each gate, then a walkthrough where each of us explains the other's merged code (rule 12).

## Contracts and repo layout

**Task F2 freezes these eight contracts, and every other task plugs into them.** The first name in the last column writes the contract; the second reviews it.

| Contract | File | What it pins down | Writes, reviews |
| --- | --- | --- | --- |
| Graph schema | `contracts/schema.py` | Node labels and IDs, edge types (including `USES`, `CALLS`, `REQUESTS`, `HAS_ENV`), edge kinds, the `env` tag, the evidence object, the capacities `BIG` and `USED` (spec: `03-graph.md`) | A, B |
| Shared models | `contracts/result.py` | Every model that crosses a module boundary, including `AnalysisResult`, plus `project()` and `compare()` for golden tests (spec: `05-contracts.md`) | A, B |
| Engine functions | `contracts/engine.py` | The graph-store protocol and the signatures of `load_world`, `build_rows`, `analyze`, `diff`, `min_cut`, `simulate`, `rank`, `run_pr`, `run_finding`, `run_scan` | A, B |
| Adapter protocols | `contracts/adapters.py` | The IaC, cloud, CI and code protocols; `IacResource`, `CiIdentity` and `Change`; the patch-op envelope. Vendor names live only in `adapters/` (spec: `08-core-and-adapters.md`) | A, B |
| Fixture format | `fixtures/<scenario>/` | `scenario.yaml`, `base/` and `head/` trees, both plans, `pr.md` or `advisory.json`, and `expected.json` (only compared fields, written by us) | A, B |
| MCP tools | `mcp/tools.py` | Ten tools in one registry, used by the MCP server and the fix agent | B, A |
| API | `api/routes.py` | `/health`, `/analyze`, `/finding`, `/scan`, `/apply`, `/webhooks/github`, `/graphs`, `/try` | B, A |
| PR comment | `agent/templates/comment.md` | Ten sections, filled only from `AnalysisResult` fields | B, A |

```
theseus/            repo root; every file and its owner task is in docs/spec/05-contracts.md
  AGENTS.md, CLAUDE.md, .claude/settings.json, AI_USE.md, README.md, pyproject.toml, .env.example
  theseus/
    contracts/   schema, result, engine, adapters: vendor-neutral                         F2
    importer/    world, build (E1): compose the adapters into a World and its rows
    adapters/    everything that names a vendor or a format (docs/spec/08-core-and-adapters.md)
      terraform/ plan, source_index, adapter (E1); render (E9)
      aws/       kinds, ops (F2); resources, adapter (E1); iam, policies, managed, access (E2);
                 oidc (FM1); patch (E5); changes (E6)
      github/    workflows, adapter (FM1)
      python/    code, adapter (C2)
    graph/       client (F3); store, load, queries (E3); algos (E4, FM4)
    engine/      analyze, pipeline (E3); mincut (E4, C3); simulate (E5); candidates (E6);
                 intent_effect (A3); finding (FM3, FM6); staging (FM4); usage (C3, C4)
    agent/       llm, intent (A1); jev, sensitivity (A2); trace (A6); fixer, evidence (A7); render, templates (A4)
    mcp/         tools, server (A6)
    api/         app, stub, routes (F3); github (F7, A9); webhooks (A9)
    web/         the Try-it page (S4)
  demo-infra/    the synthetic world: terraform/, services/, workflows/, theseus.yaml (F4, C1)
  fixtures/      five scenarios generated by make_fixture.py; expected.json by people (F4, F5)
  recordings/    recorded LLM and Jev replies (A1, A2, A7)
  tests/         unit, golden, contract, replay, integration, e2e
  bench/         benchmark and timings (S2)
  deploy/        Dockerfile, docker-compose.yml, Caddyfile, deploy.sh (F3)
  tools/         make_board.py, tasks.csv, dep_graph.py, agent_guard.py; plan.sh, make_fixture.py (F4)
  docs/          spec/ (7 files) and tasks/ (31 briefs)
```

A sample `expected.json` for the intern scenario. It holds only the fields we compare, and we write it by hand; it is the answer key the agents' code is graded against. The line numbers come from `demo-infra/` once F4 is merged.

```json
{
  "scenario": "intern",
  "mode": "pr",
  "intent": {"grants": [["user:priya-intern", "read", "s3://demo-app-logs/"]], "suspicious": false},
  "opened": [
    {"actor": "user:priya-intern", "target": "db:customer-db",
     "route": ["user:priya-intern", "group:support-engineers", "role:prod-support",
               "secret:prod-db-credentials", "db:customer-db"],
     "cites": ["terraform/people.tf:20", "terraform/people.tf:30", "terraform/roles.tf:31", "terraform/data.tf:12"]}
  ],
  "closed": [],
  "requirements": {"R1": "satisfied", "R2": "satisfied", "R3": "satisfied", "I1": "satisfied"},
  "min_cut": {"cuttable": false, "value_at_least": 1000000},
  "candidates": {"A": "fail", "B": "pass", "C": "unknown", "D": "fail"},
  "recommended": "B",
  "rotate": [], "unused_grants": [], "use_beyond_intent": [], "staging_to_prod": []
}
```

## Testing

**Fast code only counts when a test we wrote says it is right.** The layers below run automatically, and the acceptance tests under them are what "done" means for the four beats.

| Layer | What it checks | Runs | Owner |
| --- | --- | --- | --- |
| Unit | IAM matching: wildcards, Deny precedence, `NotAction` returning UNKNOWN, OIDC `sub` matching. The code extractor on each call pattern | Every commit | A |
| Golden fixtures | Engine output against `expected.json` for each scenario and each benchmark PR | Every commit | A |
| Contract | Results from the stub and from the real engine both validate against the schema | Every commit | Both |
| Agent replay | Recorded LLM replies replayed. The evidence checker rejects unknown IDs, and an injected instruction in PR text is flagged | Every commit | B |
| Live model | A few real LLM and Jev calls on the scenarios | At every gate | B |
| End to end | A real demo/ PR in this repo: comment, check, apply, re-run | At every gate | Both |
| Deploy smoke | Health endpoint up, FalkorDB reachable, Try-it renders | After every deploy | B |
| Benchmark | About 20 PRs: Theseus against Checkov, plus timings | Once E3 passes, and again before the video | A |
| Integration | FalkorDB and the in-memory test store give the same paths and cuts on every fixture | Every PR, with FalkorDB as a CI service | A |

### Acceptance tests

- [ ] Adding the intern to the group opens paths that the base graph does not have
- [ ] Removing her from the group closes them but breaks her declared need to read app-logs
- [ ] The minimum cut reports that no single permission can be cut without breaking required access
- [ ] The `intern-onboarding` role closes every path and keeps every requirement
- [ ] Making the bucket public exposes `invoices/*`, and public read on `public/*` only does not
- [ ] The compromised-Action alert traces Action, workflow, OIDC trust and role to the customer database
- [ ] The rotation list holds exactly the secrets the compromised workflow can reach
- [ ] The docs-site preview workflow is flagged as a staging-to-prod path
- [ ] A grant on a sensitive path with no `CALLS` edge behind it is listed, and the usage-weighted cut lands on it
- [ ] When a second route exists, Theseus never claims the risk is fully blocked
- [ ] A statement with an unsupported condition returns UNKNOWN
- [ ] A finding is shown as an assumed compromise, never a confirmed one
- [ ] Injected instructions in PR text or an advisory are flagged and never count as evidence
- [ ] Resetting restores the base graph, and a re-run gives the same result
- [ ] The explanation cannot add paths, permissions or evidence that the engine did not return

## Gates and fallbacks

**Each gate is a G task on the board with a fallback decided now, so nobody argues under pressure.** At a gate both of us run the beat end to end on a fresh `demo/` branch and save a backup clip.

| Gate or risk | Checked | If it fails |
| --- | --- | --- |
| Walking skeleton | End of Foundation | Keep building on fixtures. If the VM is blocked, run Docker locally behind a tunnel |
| G1: Beat 1 live | End of Beat 1 | Show the comment from fixtures; fixing the importer comes before anything else |
| G2: Demo 2 end to end | End of Beat 2 | Both of us stop everything else and finish it. Beat 3 shrinks to the trace, without the containment PR |
| G3: Beats 3 and 4 | End of Beats 3 and 4 | An unfinished beat runs on fixtures in the video, or moves to the roadmap slide |
| A demo-world resource type fails to plan under mock credentials | P1 or F4 | Move it to the skipped files or drop it; no scenario depends on network or platform resources |
| MaxFlow missing or unusable | P1 or E4 | Compute the cut in Python from graph copies, and say so in the README |
| Intent extraction unreliable | A1 | Add a purpose field to the PR template and keep the comparison |
| Code freeze | Before the video | After the freeze, only the README, the video and fixes for breakage |
| Submission | Well before the deadline | The time left is buffer |

## Rules we must meet

**Every rule on the [event page](https://www.wemakedevs.org/hackathons/falkordb) has an owner task, so none is left for the end.**

| Rule | What we do |
| --- | --- |
| 2 and 3: FalkorDB is primary, and the product must not work without it | The README says what breaks without FalkorDB, with a one-line test: stop the container and every check fails |
| 5: name every track entered | Track 01 only |
| 6: only public, synthetic or own data | Invented names only, never a teammate's or an employer's. The compromised Action is a fixture advisory, and we never run a real tampered Action. No real secrets in the demo org |
| 8: main coding and design start after the event begins | The PoC stays private and is never copied into the repo. The first commit landed after the event started. The repo, with this plan, stays private until we submit. The agent kit (specs and task briefs, no code) was written before the event as notes, and the README says so |
| 10: repo, README with setup and graph model, the Cypher and algorithms used, video, live deployment or local setup, track named | Tasks S5 to S7. The README's queries-and-algorithms section is written first, not left for the end |
| FAQ: a live deployment is preferred | The Try-it page runs the real engine and FalkorDB live and caches only the LLM's text, so it is genuinely live and still cheap |
| 11 to 13: disclose AI use, every member can explain the code, not entirely AI-generated | `AI_USE.md`, the evening walkthroughs, every `expected.json` reviewed and saved by us (an agent may draft the values), and real commits from both of us |
| 1, 4, 7, 9, 15 to 18 | IP ownership agreed in writing (P6), and Cartography, SubImage and AWS research credited in the README |

## Submission

**The video carries the story and the README carries the proof.** Record a backup clip at each gate (tasks G1 to G3), so a late failure never costs a beat.

### Video script, 3:00 target

**Video script for P4 / [#3](https://github.com/AjinkyaTaranekar/theseus/issues/3).**
The story follows the implemented four beats, then shows the organisation dashboard. Speak only the
voice-over column; the screen directions and evidence below are for the operator and editor.

Use one narrator for continuity and one operator for the captures. Narrator and operator names await the
team's choice. Capture the interactions first, then record the narration against the edited sequence.
The eight slots total 180 seconds, including pauses to read the graph. This is a timing budget, not a measured
read-aloud. P4 stays open until a person reads this version aloud and records the duration below.

| Time | On screen and edit | Voice-over |
| --- | --- | --- |
| 0:00–0:12 | Open the intern PR at its Terraform diff, then the Checkov result for that same head. Overlay: **One group membership. Three new paths.** | An intern needs production logs. Checkov passes this group-membership change. But it also opens a route to the customer database. |
| 0:12–0:34 | Theseus's comment: the consequence, what the PR says, then the graph. Follow Priya → support-engineers → prod-support → prod-db-credentials → customer-db. Open one evidence link; briefly show all three targets. | Theseus compares what the pull request says, what Terraform allows, and what the code calls. In FalkorDB, it traces Priya through the group and role, to a secret that unlocks customer-db. Every hop links to its source line. |
| 0:34–1:01 | Show the protected minimum cut, value **1,000,000**, and the four candidate verdicts: A fail, B pass, C UNKNOWN, D fail. Open B's proposed patch operations from the saved review data, then its tool trace. Overlay: **Models propose. The engine checks.** | Deleting access would also remove the logs she needs. The agent uses graph tools to propose a scoped role instead. Each fix is tested on its own graph copy. The engine checks dangerous paths, required access, and resolved code calls. An unsupported conditional Deny gets UNKNOWN. |
| 1:01–1:18 | Use the G2 capture: the reviewer inspects B, comments `/theseus apply B`, the App's commit appears, then the rerun's final **Theseus** check succeeds. Cut waiting time; keep the reviewed and resulting heads legible. | A reviewer inspects the fix and asks Theseus to apply it. The App commits to the reviewed branch, and the check runs again. The model cannot approve its own proposal. |
| 1:18–1:46 | Label **Synthetic advisory; assumed compromise**. From the finding page, follow preview.yml → github-deploy → prod-support → secret → customer-db. Show containment K, its `ci.tf` diff and the rotation issue. Keep the PR visibly awaiting review. | Now assume a workflow using this affected Action is compromised. Its staging trust reaches production data. Theseus verifies a narrower trust policy and opens a containment pull request for human review. It lists prod-db-credentials for rotation because that workflow could read it. |
| 1:46–2:10 | Show the unused grant in the dashboard or saved scan, its `LegacyDbSecret` evidence and U's passing verdict. Cut to the `code-pr` result: a typo PR, new secret and database calls, cited lines. Overlay: **Within the modeled requirements and resolved calls.** | The graph finds a database-secret grant with no resolved call from support-portal. Removing it preserves the modeled requirements and resolved calls. But when a typo-fix pull request starts reading that secret, Theseus flags the new use, even though IAM permissions did not change. |
| 2:10–2:35 | Organisation dashboard: posture of main, a linked review and finding, reach, a single point of failure and cost marked **estimate**. Cut to the state graphs, `GRAPH.COPY`, actual flow call and the recorded MCP trace. | The dashboard brings together main's access, reviews, findings, single points of failure, and estimated cost. FalkorDB stores each state and runs the path queries and maximum flow. Copies isolate proposed fixes. The tool trace shows what the agent actually asked and what the engine returned. |
| 2:35–3:00 | End card: **FalkorDB Graph Hacks · Track 01**; **Engine decides facts · Models propose · A person approves**; public Try-it and repository links, verified before export. Small text: **Synthetic infrastructure · AWS IAM subset · Python code · Network exposure not modeled**. | Theseus reviews changes before merge and helps contain risks already present. Today it supports a defined AWS IAM subset and Python code. Unsupported rules stay UNKNOWN. The demo uses synthetic infrastructure. Try the live graph engine with recorded model responses. The engine decides facts, models propose, and a person approves. |

#### Evidence behind the shots

Use the actual output at the recorded commit. Candidate B's name and operations can vary: show the scoped role
it produced, rather than relabeling it `intern-onboarding`. A `pass` result still needs human review.
The comment shows verdicts and a tool trace; it does not expose the numeric protected cut or a rendered
Terraform diff. For the cut value and B's patch operations, open the saved review's signed `/data` response
and inspect `result.min_cut` and `result.candidates`. Keep its `head_sha` visible so the details belong to the
same take. The actual Terraform diff is available on the App's resulting commit after apply; do not imply
that the current review page provides a pre-apply diff preview. U's cited policy and operations are in the
saved scan result; the dashboard's unused-grant table shows the grant and U verdict, not the full evidence.

| Shot | Evidence already available | What still needs capture or verification |
| --- | --- | --- |
| Intern and Checkov | [PR #85](https://github.com/AjinkyaTaranekar/theseus/pull/85), head `01ae50f1fb2152d61003b6bff769b1c755832b0b`: the App comment reports 365 Checkov checks passed, three opened paths, B pass, C unknown, A/D fail and an engine tool trace. [Intern golden tests](../tests/golden/test_intern.py) and [cut tests](../tests/golden/test_mincut_fixtures.py) pin the modeled outcomes. | G1: a fresh demo branch, the same-head Checkov artifact and comment, the source link and a saved clip. The existing PR is a reference take, not evidence that G1's recording is complete. |
| Apply and green check | [Apply PR #102](https://github.com/AjinkyaTaranekar/theseus/pull/102) and [follow-up #115](https://github.com/AjinkyaTaranekar/theseus/pull/115) are merged; [webhook tests](../tests/unit/test_webhooks.py) cover permission, head and verdict checks. | G2: a person approves B on a fresh demo PR, then captures the commit and final **Theseus** success on the new head. At audit time #85's **Theseus** conclusion is failure; its workflow job called `review` succeeding does not mean the security check passed. |
| Containment and rotation | [PR #111](https://github.com/AjinkyaTaranekar/theseus/pull/111) is open and changes only `demo-infra/terraform/ci.tf`; [issue #112](https://github.com/AjinkyaTaranekar/theseus/issues/112) lists `prod-db-credentials`. [Finding golden tests](../tests/golden/test_compromised_action.py) verify K, retained required access and the rotate list. | G3: capture the finding, K and the open reviewable PR. Creating the PR does not merge it or rotate a secret. This synthetic scenario needs no real AWS account or secret rotation. |
| Unused grant and code PR | [Unused-grant golden tests](../tests/golden/test_unused_grant.py) pin U pass with no broken calls; [code-PR tests](../tests/golden/test_code_pr.py) pin the new secret and database calls and blocked check. | G3: capture the deployed posture/scan and code-PR result, with evidence. Preserve the distinction between an unused grant in base and new use in the separate code-PR head. |
| Dashboard and graph tools | [Dashboard PR #109](https://github.com/AjinkyaTaranekar/theseus/pull/109), [redesign #114](https://github.com/AjinkyaTaranekar/theseus/pull/114), [dashboard tests](../tests/e2e/test_dashboard.py), [graph algorithms](../theseus/graph/algos.py), [store](../theseus/graph/store.py) and [MCP registry](../theseus/mcp/tools.py). | Open links from the current App comment/dashboard. The dashboard shows the commit actually scanned. Capture real calls and responses; do not invent a tool selection or retry for the story. |
| Try-it and limits | [Try-it PR #95](https://github.com/AjinkyaTaranekar/theseus/pull/95), [preset tests](../tests/unit/test_try.py) and [world limits](spec/02-demo-world.md#what-the-world-leaves-out). | Test the public URL from outside the operator's signed-in session. Try-it offers the three PR presets (`intern`, `public-bucket`, `code-pr`), with recorded models and live engine/FalkorDB; it does not offer finding or scan presets. |

The maximum-flow implementation has a logged Python Edmonds–Karp fallback; inspect the take's logs before
attributing its flow calculation to FalkorDB. If that fallback was used, replace the dashboard segment's
algorithm sentence with: **“FalkorDB stores each state and runs the path queries. This run computes maximum
flow with the Python fallback.”** Choke-point ranking uses exact Brandes in Python; articulation points use
Tarjan in Python. Do not describe either as a database algorithm in this video.

#### Recording handoff

1. **Prepare the take (G1–G3).** Use current deployed `main` and a new `demo/<scenario>-<take>` branch whose
   changes stay in `demo-infra/`. Keep the intern review and fix together at their actual heads. Record the
   commit SHA, deployment, graph names, check URLs and clip paths with the take. Opening a branch or posting
   `/theseus apply B` is a gate action for the team, not part of preparing this local script.
2. **Arrange the screens.** Use one browser size, hide unrelated tabs and notifications, and enlarge the
   relevant card, graph or diff. Follow one route per shot. Keep node names, verdicts and cited source lines
   readable; use cuts instead of dragging viewers across the entire graph.
3. **Record the evidence first.** G1 supplies the opening; G2 supplies the apply sequence; G3 supplies finding,
   U and code-use clips. Capture the dashboard and graph/tool details after those results exist. Save each
   original take before editing. Do not merge the intern demo into main to obtain a green-check shot.
4. **Edit the waits.** A plan or model call can take longer than its slot. Cut to the real completed result,
   label elapsed-time cuts, and keep the head and candidate identity consistent. Narration makes no latency
   promise: #85's comment reports 88.7 seconds, not the old plan's roughly 20-second PoC figure.
5. **Handle a failed take.** Use the saved G1/G2/G3 clip of that same operation and label it **Recorded run**.
   A saved finding page proves the saved result, not a new run. If no apply-success clip exists, replace that
   slot with B's verified patch operations and say **“This fix is verified on a graph copy and awaits a reviewer’s apply
   command.”** Do not show a fabricated green check. If unused-grant or code-use capture fails, use a clearly
   labeled fixture recording or move the claim out of the spoken script and re-time the edit.
6. **Keep the model boundary visible.** Label Try-it **Recorded model responses; live engine and FalkorDB**.
   A fixture command is a fallback only after its complete invocation has succeeded in that environment;
   CLI and `/scan` replay coverage is not interchangeable with Try-it's content-based replay helpers.
   `/scan` without a fixture currently returns 501, so it cannot demonstrate automatic repo scan-fix PRs.
   The `/posture` path opens containment PRs; a standalone finding result does not itself prove PR creation.
7. **Export (S6).** Check readable captions, clear speech and matching source/head IDs. Add the Try-it and
   repository URLs only after the team verifies judge access; private signed review links are not the public
   end-card link. Use only these synthetic fixtures. Leave benchmark and large-graph numbers out until S2's
   report exists; results on this demo are not a measured detection rate.

#### P4 read-aloud and sign-off

| Item | Status and owning task |
| --- | --- |
| Narrator / operator | Pending the team's choice; one narrator and one operator recommended |
| Spoken word count and estimated pace | 314 whitespace-separated words; about 2:31 at 125 words/minute, leaving about 0:29 for pauses in the 3:00 edit. Every segment fits its slot at that pace. Recount after wording changes. |
| Actual read-aloud duration | Pending a human read of this exact version; record `m:ss`, reader and version/commit |
| Edit duration (S6) | Target 3:00; verify after inserting the actual clips and pauses. This is a later video-production check, not a P4 merge requirement. |
| Other teammate review | Pending: explain the protected cut, B/K/U verification, UNKNOWN and the synthetic-compromise assumption |

Read it aloud once at a comfortable pace, pausing at each evidence link and verdict. Trim wording before
speeding up the narration. The final read and exported video, rather than a words-per-minute estimate, decide
whether the timing works. This documentation can be reviewed now. To merge it as the completed P4 task, record the narrator/operator
choice and actual read-aloud duration, obtain the other teammate's diff review, and pass the PR's required
CI checks. G1–G3 recordings, S2's benchmark and the final S6 video are separate tasks; they do not block the
P4 script merge. Until P4's human steps are recorded, keep its eventual PR in draft so `Closes #3` cannot
prematurely mark the task complete.

### Board audit and remaining handoffs for this video

**Snapshot: 17 October 2026.** Read all 54 issues (42 closed, 12 open), all 59 PR records, the task dependency
CSV, briefs, relevant specs, code and tests. The implementation baseline is `origin/main` at `9e98a0e`, whose
[CI](https://github.com/AjinkyaTaranekar/theseus/actions/runs/39026784111) and
[deploy](https://github.com/AjinkyaTaranekar/theseus/actions/runs/39027147161) succeeded. The completed
[Theseus main run](https://github.com/AjinkyaTaranekar/theseus/actions/runs/39026660205) scanned the earlier
`7b41127` head. These are historical run results, not a claim that the current public site was tested here.

The authenticated CLI lacks `read:project`, so project columns and cards could not be read. The audit uses
issue states, explicit dependencies, PR merge targets and Git history; it does not infer a board column from
an issue being open or closed. No issue, assignment, label or project status was changed. Rows below cover
every issue in this snapshot. Closed implementation issues still need their gate's recorded demonstration.

| Issues / work | Repository and dependency check | Consequence for P4 and the team |
| --- | --- | --- |
| [#1 P1](https://github.com/AjinkyaTaranekar/theseus/issues/1), [#2 P3](https://github.com/AjinkyaTaranekar/theseus/issues/2), [#4 P5](https://github.com/AjinkyaTaranekar/theseus/issues/4), [#5 P6](https://github.com/AjinkyaTaranekar/theseus/issues/5) — closed | Prep, scenario review, access and registration/IP tasks. P3 landed through #45; it is P4's only declared prerequisite. | P4 can proceed. Closed human tasks are recorded issue states, not checks repeated by this script audit. |
| [#7 F1](https://github.com/AjinkyaTaranekar/theseus/issues/7), [#8 F2](https://github.com/AjinkyaTaranekar/theseus/issues/8), [#9 F4](https://github.com/AjinkyaTaranekar/theseus/issues/9), [#10 F3](https://github.com/AjinkyaTaranekar/theseus/issues/10), [#11 F5](https://github.com/AjinkyaTaranekar/theseus/issues/11), [#12 F7](https://github.com/AjinkyaTaranekar/theseus/issues/12), [#63 demo hardening](https://github.com/AjinkyaTaranekar/theseus/issues/63) — closed | Package/CI, contracts, generated world, deployment, human answer keys and GitHub integration exist. F5 follows F4/P3; ingestion and analysis use these contracts and fixtures. | Use the existing world and evidence. No fixture regeneration, schema changes or moved source lines are needed for the video script. |
| [#13 E1](https://github.com/AjinkyaTaranekar/theseus/issues/13), [#14 E2](https://github.com/AjinkyaTaranekar/theseus/issues/14), [#15 E3](https://github.com/AjinkyaTaranekar/theseus/issues/15), [#16 A1](https://github.com/AjinkyaTaranekar/theseus/issues/16), [#17 A2](https://github.com/AjinkyaTaranekar/theseus/issues/17), [#18 A3](https://github.com/AjinkyaTaranekar/theseus/issues/18), [#19 A4](https://github.com/AjinkyaTaranekar/theseus/issues/19), [#20 A5](https://github.com/AjinkyaTaranekar/theseus/issues/20) — closed | Importer + IAM + FalkorDB analysis, recorded model wrappers, intent/effect, rendering and real analyze are in main. E3 consumes E1/E2/F3/F5; A5 combines E3/A3/A4/F7. | Supplies G1 and the first two shots; PR #85 is existing live evidence, while a new gate clip is still due. |
| [#21 FM1](https://github.com/AjinkyaTaranekar/theseus/issues/21), [#22 C1](https://github.com/AjinkyaTaranekar/theseus/issues/22), [#31 C2](https://github.com/AjinkyaTaranekar/theseus/issues/31) — closed | Workflow/OIDC ingestion and Python services/code reader are present; C2 consumes F2/C1, FM1 consumes F4/E2. | Supplies the Action/trust path and the code-use evidence. No new language reader or network-exposure edge is needed. |
| [#24 E4](https://github.com/AjinkyaTaranekar/theseus/issues/24), [#25 E5](https://github.com/AjinkyaTaranekar/theseus/issues/25), [#26 E6](https://github.com/AjinkyaTaranekar/theseus/issues/26), [#27 E9](https://github.com/AjinkyaTaranekar/theseus/issues/27), [#28 A6](https://github.com/AjinkyaTaranekar/theseus/issues/28), [#29 A7](https://github.com/AjinkyaTaranekar/theseus/issues/29), [#30 A9](https://github.com/AjinkyaTaranekar/theseus/issues/30) — closed | Cuts, graph-copy simulation, rule fixes, Terraform rendering, MCP, the model's fix and apply are integrated. A7 needs E5/A6; apply needs F7/E9. Actual cut code also uses approved intent (A3), although #24's issue body lists only E3. Both dependencies are now in main. | Supplies G2. Read B's proposed operations and verify the current head before the human apply action; rule or replay tests alone cannot supply the green-check clip. |
| [#32 FM3](https://github.com/AjinkyaTaranekar/theseus/issues/32), [#33 FM4](https://github.com/AjinkyaTaranekar/theseus/issues/33), [#35 FM6](https://github.com/AjinkyaTaranekar/theseus/issues/35) — closed | Finding depends on FM1/E3; extras use E4/A2; containment adds E5/E9/A9. Stacked PRs #113 → #109 → #108 reach main; #111/#112 are actual resulting artifacts. | Supplies G3's finding shot. Show an assumed compromise, a verified proposed trust edit, and an unmerged PR; do not claim the incident is already contained. |
| [#36 C3](https://github.com/AjinkyaTaranekar/theseus/issues/36), [#37 C4](https://github.com/AjinkyaTaranekar/theseus/issues/37) — closed | Usage weighting, U and use-beyond-intent exist with golden tests. #91 closed without a merge; C3's commit `f6caaed` is nevertheless an ancestor of main. C4 is integrated via #101/#108. | Supplies G3's two code shots. A closed PR is not the only way code reaches main; judge readiness comes from the actual implementation and captures. |
| [#40 S4](https://github.com/AjinkyaTaranekar/theseus/issues/40) — closed | Try-it's PR #95 is merged. `build_try` uses recorded model answers with the selected graph store; production uses FalkorDB. | Provides the public call to action and a PR-fixture fallback. It is not a replacement for finding/scan gate captures. |
| [#57 incomplete replies](https://github.com/AjinkyaTaranekar/theseus/issues/57), [#58 API retries](https://github.com/AjinkyaTaranekar/theseus/issues/58) — closed | Shared LLM validation and status-based retry fixes landed through #67/#68. | Existing reliability work; no new model/dependency change for P4. Avoid staging a retry that the displayed tool trace did not perform. |
| [#103 O1](https://github.com/AjinkyaTaranekar/theseus/issues/103), [#104 O2](https://github.com/AjinkyaTaranekar/theseus/issues/104), [#105 O3](https://github.com/AjinkyaTaranekar/theseus/issues/105), [#106 O4](https://github.com/AjinkyaTaranekar/theseus/issues/106), [#107 O5](https://github.com/AjinkyaTaranekar/theseus/issues/107) — closed | Posture, dependency loss/articulation, cost estimates, dashboard and onboarding are integrated via #109/#108 and the redesign. O1 consumes C3/FM3/FM4; O2/O3/O4 consume O1; O5 consumes O4. These additions are not in the original task CSV. | Give the implemented dashboard a short synthesis shot. Label cost as an estimate without usage data; showing a single point of failure does not demonstrate failover simulation. |
| [#3 P4](https://github.com/AjinkyaTaranekar/theseus/issues/3) — open | P3 is closed. This local script replaces the old eight one-line narration cues with a timed script, proof map and handoff. | Human work remaining: choose narrator/operator, read this version aloud, record duration and review wording. Then #42 can consume the script. |
| [#6 P7](https://github.com/AjinkyaTaranekar/theseus/issues/6) — open | P3 is closed; both teammates still need the judge-question rehearsal. | Rehearse capacities, residual cut, UNKNOWN, OIDC assumptions, model boundaries and limits using the current code; remove old performance/benchmark promises when answering. |
| [#23 G1](https://github.com/AjinkyaTaranekar/theseus/issues/23) — open | A5 is closed; the reference PR has a real review. Missing proof for closure: both teammates witness the fresh run and save its clip. | Capture same-head Checkov, three paths and linked evidence; record clip path and head. This unlocks G2. |
| [#34 G2](https://github.com/AjinkyaTaranekar/theseus/issues/34) — open | E4/E6/A7/A9 are closed; G1 is still open. | After G1, inspect B and capture human apply → commit → rerun → final Theseus success on that commit. Save the clip; never substitute the workflow job's success. This unlocks G3. |
| [#38 G3](https://github.com/AjinkyaTaranekar/theseus/issues/38) — open | FM4/FM6/C3/C4 are closed; G2 is still open. | After G2, capture finding/K/rotate plus U and code-use. Record which runs are live and which are fixtures, and save the clips. This unlocks final S5/S6 proof. |
| [#39 S2](https://github.com/AjinkyaTaranekar/theseus/issues/39) — open | E4/E5 are closed; `bench/` contains only `.gitkeep` at this baseline. The `s2-proof` worktree points at main; its name is not a benchmark report. | Can run alongside gate preparation. Follow its brief: humans own benchmark answer keys; produce catches/misses and VM medians in `bench/report.md`. Until then, omit accuracy and large-graph speed claims. S2 is not a declared prerequisite of P4 or S6. |
| [#41 S5](https://github.com/AjinkyaTaranekar/theseus/issues/41) — open | Existing local commit `6b96567` on `s5-readme` contains the submission README; it is not on main. G2/G3 are still open. | Preserve that work. Once the gates provide evidence, review setup, links, limits and measured results against the chosen release; add the real GIF/clip. Do not rewrite its README in P4. |
| [#42 S6](https://github.com/AjinkyaTaranekar/theseus/issues/42) — open | Needs G3 and P4, both open. | Edit the gate clips against this script, record the selected narrator, verify duration/captions/links, upload and record the URL. Script preparation can finish before the gate captures. |
| [#43 S7](https://github.com/AjinkyaTaranekar/theseus/issues/43) — open | Needs S5 and S6, both open. | After their review, the humans choose the submitted commit, verify public access, tag and submit naming Track 01. No publication or release action is part of this local script change. |
| [#44 S8](https://github.com/AjinkyaTaranekar/theseus/issues/44) — open | Needs S6. Its brief says publish after submission. | Draft from the verified script/results, then publish after S7 with the final demo/repo links. It does not block the demo. |
| [#69 future design](https://github.com/AjinkyaTaranekar/theseus/issues/69) — open | Service-to-service traversal, exposure and other-language proposals require human agreement on graph/schema changes; they are outside the four-beat implementation. | Keep these as future work. Do not add them as dependencies or suggest the current graph proves internet-to-service network reachability. |
| [#112 rotate list](https://github.com/AjinkyaTaranekar/theseus/issues/112) — open | This is an output of the synthetic advisory flow, linked from #111. | Show it as a proposed rotation checklist, not unfinished product implementation or proof that any real secret was rotated. |

**Working order:** finish P4's human read-aloud while preparing G1; then G1 → G2 → G3; then finish S5 and S6,
which can proceed together once their shared gates are evidenced; then S7; then S8 publication. P7 and S2 can
run beside the gate work. The runtime modules already exist: the immediate gaps are evidence, rehearsal,
benchmark work and release artifacts. Neither #69 nor the demo's rotation issue belongs on that critical path.

### README outline

1. One-line pitch, plus a 20-second GIF of the intern PR and Theseus's comment
2. Why it matters: the incidents table, short
3. How it works: one diagram
4. Graph model: nodes, edges (code edges included) and the evidence each edge keeps
5. Queries and algorithms: every Cypher query, plus the MaxFlow and betweenness calls (rule 10)
6. Setup: one Docker Compose command, environment variables, the demo org
7. Results: the benchmark against Checkov, timings, Jev's numbers
8. Limits: supported rules, when UNKNOWN appears, what static code reading misses
9. How we used AI: in building, and inside the product (rules 11 to 13)
10. Roadmap: Phases 4 and 5, each with a Cypher sketch
11. Credits: Cartography, SubImage, AWS research, the FalkorDB docs

### Repo hygiene

- The first commit lands after the event starts, and commits come from both of us, small and clearly described.
- Include a license, a `.env.example`, no secrets, and the tests running in CI.
- Tag the commit you submit, so judges see exactly what was judged.
- Write the blog post alongside the README, and publish it after submitting, for the side prize.
