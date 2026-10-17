# 05. Contracts

Task F2 turns this file into `theseus/contracts/`. Once F2 freezes them, contracts only grow.

## The skeleton: every file, its purpose, and the task that creates it

```
theseus/                              (repo root)
├── AGENTS.md, CLAUDE.md              rules for agents                                     (written before the event)
├── AI_USE.md                         one line per task: which agent wrote what            F1
├── README.md                         setup, graph model, queries, results, limits, AI use S5
├── pyproject.toml                    package, dependencies, ruff and pytest config        F1
├── .env.example                      every environment variable, no values                F1
├── .github/
│   ├── workflows/ci.yml              lint and offline tests on every PR                   F1
│   ├── workflows/theseus.yml         the Theseus Action, on PRs that touch demo-infra/    F7
│   ├── pull_request_template.md      What, Why, How tested, AI used                       F1
│   └── CODEOWNERS                    folder to lane owner                                 F1
├── theseus/
│   ├── __init__.py, __main__.py      package; `python -m theseus`                         F1
│   ├── cli.py                        analyze, finding, scan, serve commands               F1, then E3
│   ├── config.py                     Settings from environment variables                  F1
│   ├── errors.py                     TheseusError and its subclasses                      F1
│   ├── contracts/                    vendor-neutral; a change needs both humans
│   │   ├── schema.py                 labels, edge types, ID grammar, categories, BIG, USED F2
│   │   ├── result.py                 shared Pydantic models, AnalysisResult, project()    F2
│   │   ├── engine.py                 Protocols for the engine functions and graph store   F2
│   │   └── adapters.py               IaC, cloud, CI and code adapter protocols            F2
│   ├── importer/                     core: compose the adapters into a World and rows
│   │   ├── world.py                  load a world folder or a fetched commit              E1
│   │   └── build.py                  adapters' rows, requirements, labels, coverage       E1
│   ├── adapters/                     the only code that names a vendor or a format (08)
│   │   ├── terraform/
│   │   │   ├── adapter.py            TerraformAdapter, the IacAdapter                     E1, E9
│   │   │   ├── plan.py               plan JSON to resources and unknown fields            E1
│   │   │   ├── source_index.py       file and line for addresses and Sids                 E1
│   │   │   └── render.py             patch ops as .tf text edits                          E9
│   │   ├── aws/
│   │   │   ├── adapter.py            AwsAdapter, the CloudAdapter                         E1, E2, E5, E6, FM1
│   │   │   ├── catalog.yaml          data and workload types as data (README.md)          F2, E2
│   │   │   ├── catalog.py            load and check the catalog                           E2
│   │   │   ├── kinds.py              resource kinds and categories, modeled types         F2, E2
│   │   │   ├── ops.py                the patch-op catalog, typed, and its JSON schema     F2
│   │   │   ├── resources.py          nodes, MEMBER_OF, RUNS_AS, UNLOCKS, HAS_ENV          E1
│   │   │   ├── iam.py                evaluate, trust_kind, glob matching                  E2
│   │   │   ├── policies.py           a principal's statements: inline, attached, managed  E2
│   │   │   ├── managed.py            the few AWS-managed policies we expand               E2
│   │   │   ├── access.py             CAN and CAN_ASSUME edges, bucket policies            E2
│   │   │   ├── oidc.py               OIDC trust matching and TRUSTS edges                 FM1
│   │   │   ├── patch.py              apply ops to resources                               E5
│   │   │   └── changes.py            a Change to ops                                      E6
│   │   ├── github/
│   │   │   ├── adapter.py            GithubAdapter, the CiAdapter                         E1, FM1
│   │   │   └── workflows.py          workflow YAML: per-job subs, id-token, uses          FM1
│   │   └── python/
│   │       ├── adapter.py            PythonAdapter, the CodeAdapter                       E1, C2
│   │       └── code.py               Python AST: CALLS, REQUESTS, HAS_ENV through boto3   C2
│   ├── graph/
│   │   ├── client.py                 FalkorDB connection from Settings                    F3
│   │   ├── store.py                  GraphStore protocol: FalkorStore, and MemoryStore for offline tests only  E3
│   │   ├── load.py                   load rows, GRAPH.COPY, delete, apply a delta         E3
│   │   ├── queries.py                the canonical Cypher from 03-graph.md                E3
│   │   └── algos.py                  maxFlow and betweenness calls, Python fallback       E4, FM4
│   ├── engine/
│   │   ├── analyze.py                paths, coverage, dangerous paths, requirements, diff E3
│   │   ├── pipeline.py               run_pr, run_finding, run_scan: build AnalysisResult  E3, then A5
│   │   ├── mincut.py                 capacities, max flow, cut from residual              E4, C3
│   │   ├── simulate.py               copy, apply delta, re-analyze, verdict               E5
│   │   ├── candidates.py             rule candidates A, C, D, S and ranking               E6
│   │   ├── intent_effect.py          says versus grants, headline                         A3
│   │   ├── finding.py                blast radius, rotate list, containment K             FM3, FM6
│   │   ├── staging.py                staging-to-prod findings                             FM4
│   │   └── usage.py                  unused grants, use beyond intent, candidate U        C3, C4
│   ├── agent/
│   │   ├── llm.py                    LiteLLM calls with record and replay                 A1
│   │   ├── intent.py                 PR text to expected access                           A1
│   │   ├── jev.py                    Jev client with record, replay and fast-LLM fallback A2
│   │   ├── sensitivity.py            classify Resource nodes                              A2
│   │   ├── fixer.py                  the LLM's fix loop over the tool registry            A7
│   │   ├── evidence.py               reject explanations citing unknown evidence IDs      A7
│   │   ├── trace.py                  record every tool call                               A6
│   │   ├── render.py                 AnalysisResult to the PR comment                     A4
│   │   └── templates/comment.md      the comment layout (Jinja2)                          A4
│   ├── mcp/
│   │   ├── tools.py                  tool registry: names, schemas, handlers              A6
│   │   └── server.py                 MCP server over the registry                         A6
│   ├── api/
│   │   ├── app.py                    FastAPI app, health                                  F3
│   │   ├── stub.py                   a valid AnalysisResult built from expected.json      F3
│   │   ├── routes.py                 analyze, finding, scan, apply, graphs, try           F3, then A5
│   │   ├── github.py                 App auth, comments, check runs, commits, PRs         F7, A9
│   │   └── webhooks.py               pull_request, issue_comment, push                    A9
│   └── web/                          Try-it page: index.html, app.js, style.css           S4
├── demo-infra/                       the synthetic world, layout in 02-demo-world.md      F4, C1
│   ├── terraform/*.tf, theseus.yaml, workflows/demo-org/<repo>/*.yml                  F4
│   └── services/<folder>/*.py, terraform/network.tf, platform.tf                       C1
├── fixtures/<scenario>/              generated by make_fixture.py; expected.json by humans F4, F5
├── recordings/llm/, recordings/jev/      recorded model replies for offline tests         A1, A2, A7
├── tests/unit/, golden/, contract/, replay/, integration/, e2e/                            every task
├── .mcp.json                         lets Claude Code connect to the MCP server           A6
├── bench/                            cases/, run.py, checkov.py, scale.py, report.md      S2
├── deploy/                           Dockerfile, docker-compose.yml, Caddyfile, deploy.sh F3
└── tools/                            make_board.py, tasks.csv, dep_graph.py (before the event); plan.sh, make_fixture.py (F4)
```

## Shared models (`contracts/result.py`)

All are Pydantic v2 models that reject unknown fields. Lists are sorted before a result is returned. Closed
sets are `Literal` types with the same values as the constants in `schema.py`, and a contract test keeps
them equal: `Access` (`read`, `write`, `assume`), `EdgeKind`, `EdgeType` (the 13 types in `03-graph.md`;
`FLOW` is internal and never in a row), `Category` (Cartography's ontology labels plus four of ours, `08-core-and-adapters.md`), `Sensitivity`,
`SensitivitySource`, `Env`, `Verdict`.
An eid is stable within one build only, so anything compared across builds names an edge by
(src, type, dst); eids appear only where the same run looks an edge up again (`CutEdge`, `UnusedGrant`,
`Change`).

| Model | Fields |
| --- | --- |
| `Evidence` | `address: str`, `part: str \| None` (the piece of the resource that decided it, such as an IAM statement Sid), `file: str`, `line: int \| None`, `note: str \| None` |
| `NodeRow` | `id: str`, `labels: list[str]`, `name: str`, `env: Env` (default `prod`), `category: Category \| None`, `provider: str \| None`, `sensitivity: Sensitivity \| None`, `sensitive: bool`, `sensitivity_source: SensitivitySource \| None`, `props: dict`. The category, provider and sensitivity fields are set on Resource nodes only. `props` holds the per-kind properties in `03-graph.md` (core may read them) and properties marked for one adapter (core never reads them) |
| `EdgeRow` | `eid: str`, `type: EdgeType`, `src: str`, `dst: str`, `kind: EdgeKind`, `grants: list[str]`, `evidence: list[Evidence]`, `props: dict` (the per-type properties in `03-graph.md`) |
| `GraphRows` | `nodes: list[NodeRow]`, `edges: list[EdgeRow]`, `unknowns: list[str]` |
| `Requirement` | `id: str`, `principal: str`, `access: Literal["read","write","assume"]`, `resource: str`, `source: Literal["config","intent"]` |
| `Grant` | `principal: str`, `access: Access`, `resource: str` |
| `Intent` | `purpose: str`, `grants: list[Grant]`, `suspicious: bool`, `stated: bool` (false when the PR does not say what it is for; then no grants) |
| `ResourceChange` | `address: str`, `type: str`, `action: Literal["create","update","delete"]`: one resource the change adds, changes or removes |
| `PathStep` | `src: str` (serialized as `from`), `type: EdgeType`, `dst: str` (serialized as `to`), `evidence: str` (an evidence ID), `grants: list[str]` (the access this hop's own edge grants; empty when not recorded). No eid: a step means the same in every build |
| `PathRecord` | `id: str`, `actor: str`, `target: str`, `grants: list[Access]`, `steps: list[PathStep]`, `unknown: bool`, `inferred: bool`, `sensitivity: Sensitivity \| None`; `route` (a property, not a field) is every node in order |
| `RequirementStatus` | `id: str`, `status: Literal["satisfied","missing","unknown"]` |
| `CutEdge` | `eid: str`, `src: str`, `type: EdgeType`, `dst: str`, `evidence: str` |
| `MinCut` | `sources: list[str]`, `sinks: list[str]`, `value: int`, `cuttable: bool`, `cut: list[CutEdge]` |
| `PatchOp` | `provider: str`, `op: str`, `args: dict`. The cloud adapter owns the catalog and validates `args`; AWS's is `04-engine.md` section 13 |
| `RankingFacts` | `unknown_steps: int >= 0`, `permissions_removed: int >= 0`, `adds_broad_wildcard: bool`; computed by simulation, absent on unverified results |
| `Candidate` | `id: str`, `source: Literal["rule","llm","human"]`, `proposed_by: str` (`theseus`, the model string, or a person's login), `title: str`, `ops: list[PatchOp]`, `verdict: Literal["pass","fail","unknown","invalid"]`, `reason: str`, `paths_left: list[str]`, `new_paths: list[str]`, `requirements_broken: list[str]`, `calls_broken: list[str]`, `unknown: list[str]`, `recommended: bool`, `needs_closer_look: bool`, `seconds: float`, `ranking_facts: RankingFacts \| None` |
| `UnusedGrant` | `workload: str`, `resource: str`, `access: Access`, `eid: str`, `evidence: str` |
| `BeyondIntent` | `workload: str`, `resource: str`, `access: Access`, `file: str`, `line: int`, `unlocks: list[str]` |
| `StagingToProd` | `actor: str`, `target: str`, `path_id: str` |
| `ChokePoint` | `id: str`, `score: float` |
| `ToolCall` | `tool: str`, `input: dict`, `summary: str`, `ms: int` |
| `Timings` | `engine_ms: int`, `llm_ms: int`, `jev_ms: int`, `total_ms: int` |
| `Coverage` | `resources: int`, `modeled: int`, `skipped_types: dict[str, int]`, `code_calls_skipped: int`, `nodes: int`, `edges: int` (the head graph's size in the store; 0 when not recorded) |
| `NodeInfo` | `category: Category \| None`, `sensitivity: Sensitivity \| None`: what the comment needs to name a node in plain words |
| `AnalysisResult` | `scenario: str \| None`, `mode: Literal["pr","finding","scan"]`, `repo: str \| None`, `pr_number: int \| None`, `graphs: dict[str,str]`, `intent: Intent \| None`, `changes: list[ResourceChange]`, `headline: str`, `opened`, `closed`, `unchanged: list[PathRecord]`, `requirements: list[RequirementStatus]`, `unknowns: list[str]`, `min_cut: MinCut \| None`, `candidates: list[Candidate]`, `rotate: list[str]`, `unused_grants: list[UnusedGrant]`, `use_beyond_intent: list[BeyondIntent]`, `staging_to_prod: list[StagingToProd]`, `choke_points: list[ChokePoint]`, `finding: dict \| None`, `evidence: dict[str, Evidence]`, `tool_trace: list[ToolCall]`, `timings: Timings`, `coverage: Coverage`, `models: dict[str,str]` (the models that answered, such as `{"llm": "zai-org/GLM-5.3", "jev": "jev-1.13.0"}`; shown in the comment, never projected), `nodes: dict[str, NodeInfo]` (every node on a listed path; shown, never projected), `impact: ChangeImpact \| None` (PR mode: where the change lands, whatever the data's class: `touched`, `edges`, `access`, `relies`, `dependents`, `most_affected`, the cost before and after, and a `headline`; shown, never projected) |

`project(result) -> dict` returns the comparable part of a result, in the `expected.json` shape below.

## Engine functions (`contracts/engine.py`)

| Function | Inputs | Output | Module |
| --- | --- | --- | --- |
| `load_world` | a world root (`demo-infra/`, a fixture side, or a fetched commit), its plan output, the adapters | `World` (root, IaC format, resources, unknown fields, skipped types, unknowns, IaC, CI and code files, config) | `importer/world.py` |
| `build_rows` | `World`, sensitivity labels, the adapters | `GraphRows` | `importer/build.py` |
| `load_graph`; `copy_graph`, `delete_graph` | store, `GraphState`; store, graph names | none | `graph/load.py` |
| `delta`, `apply_delta` | old rows, new rows; store, graph name, `GraphDelta` | `GraphDelta`; none | `graph/load.py` (E5) |
| `analyze` | store, `GraphState`, requirements, actors | `Analysis` (paths per actor, dangerous paths, requirement statuses) | `engine/analyze.py` |
| `diff` | base `Analysis`, head `Analysis` | `PathDiff`: opened, closed, unchanged | `engine/analyze.py` |
| `min_cut` | store, `GraphState`, `Analysis`, sources, requirements | `MinCut` | `engine/mincut.py` |
| `simulate` | store, head `GraphState`, a `CandidateDraft`, actors, requirements, the adapters | `Candidate` | `engine/simulate.py` |
| `rule_candidates`, `rank` | `GraphState`, analysis, opened paths, cut, optional keyword-only base and approved requirements; candidates and Jev's break scores by ID | `RuleFix` list; ranked `Candidate` list | `engine/candidates.py` |
| `blast_radius`, `rotate_list` | store, `GraphState`, matched workflows | paths; resource IDs of category `secret`, sorted | `engine/finding.py` |
| `containment` | `GraphState`, `Analysis`, cut, requirements | `RuleFix` K, or none when no trust is cut | `engine/finding.py` |
| `staging_to_prod` | `Analysis`, `GraphState` | `StagingToProd` list | `engine/staging.py` (task FM4) |
| `unused_grants`; `use_beyond_intent` | store, `GraphState`; base and head `GraphState`, requirements | lists | `engine/usage.py` |
| `choke_points` | store, `GraphState` | `ChokePoint` list | `graph/algos.py` |
| `run_pr`, `run_finding`, `run_scan` | worlds, PR text or advisory, `Deps` (store, adapters, LLM, Jev, settings) | `AnalysisResult` | `engine/pipeline.py` |

Applying ops and writing them back as text are adapter methods, not engine functions: `CloudAdapter.apply_ops`
and `IacAdapter.render`, below.

**The models these signatures use** (in `contracts/engine.py`):

| Model | Fields |
| --- | --- |
| `GraphState` | `name` (the graph in the store), `world: World`, `rows: GraphRows`. One state, kept together so the three never come from different states |
| `World` | `root`, `iac` (the IaC format), `resources: list[IacResource]`, `unknown_fields`, `skipped_types: dict[str, int]`, `unknowns`, `iac_files`, `ci_files`, `code_files` (relative path to text), `config` (`theseus.yaml`) |
| `Analysis` | `actors`, `paths: dict[actor, list[PathRecord]]`, `dangerous: list[PathRecord]`, `requirements: list[RequirementStatus]` |
| `PathDiff` | `opened`, `closed`, `unchanged`: lists of `PathRecord`, keyed by (actor, target) |
| `GraphDelta` | `add_nodes`, `remove_nodes` (IDs), `add_edges`, `remove_edges` (as (src, type, dst)) |
| `FlowRow`, `EdgeFlow`, `FlowResult` | One `FLOW` edge (`src`, `dst`, `eids`, `capacity`); its flow (`eids`, `flow`); max flow (`value`, `flows`) |
| `RuleFix` | `id`, `title`, `changes: list[Change]`: a rule's fix before the cloud adapter turns it into ops |
| `CandidateDraft` | `id`, `source: Literal["rule","llm","human"]`, `proposed_by`, `title`, `ops: list[PatchOp]`: a fix ready to simulate |
| `WorkflowUse`, `GrantRow`, `CallRow` | Rows of Q_WORKFLOWS_USING, Q_UNUSED_GRANTS and Q_CALLS |
| `Deps` | `store`, `adapters`, `llm` (A1's wrapper), `jev` (A2's client), `settings` |

**The graph store** (`GraphStore`, implemented by `FalkorStore` and `MemoryStore` in E3) has one method per
canonical query in `03-graph.md`, so both stores answer the same questions and the parity test compares them:

| Method | Query | Returns |
| --- | --- | --- |
| `list_graphs()` | `GRAPH.LIST` | graph names, sorted |
| `load(name, rows)`, `copy(src, dst)`, `delete(name)`, `apply_delta(name, delta)` | Loading, `GRAPH.COPY`, `GRAPH.DELETE` | none |
| `paths(name, actor)` | Q_PATHS | the eids of each route |
| `max_flow(name, sources, sinks, rows)` | Q_SET_FLOW, then Q_MAXFLOW | `FlowResult` |
| `betweenness(name)` | Q_REL_TYPES, then Q_BETWEENNESS | `ChokePoint` list |
| `workflows_using(name, action)`, `unused_grants(name)`, `calls(name)` | Q_WORKFLOWS_USING, Q_UNUSED_GRANTS, Q_CALLS | `WorkflowUse`, `GrantRow`, `CallRow` lists |

## Adapter protocols (`contracts/adapters.py`)

Rules in `08-core-and-adapters.md`. Core calls these through `Deps.adapters`; only `cli.py`, `api/app.py` and tests
build them.

| Protocol | v1 | Methods | Tasks |
| --- | --- | --- | --- |
| `IacAdapter` | `TerraformAdapter` | `read(root, plan) -> IacRead` (resources, unknown fields, files); `locate(files, address, part) -> Evidence`; `render(files, ops) -> files` | E1, E9 |
| `CloudAdapter` | `AwsAdapter` | `name`, `modeled_types`, `resource_kinds` (kind to category); `rows(resources, identities, locate) -> GraphRows`; `ops_for(change, rows, resources, *, base_resources=None) -> ops`; `apply_ops(resources, ops) -> resources`; `ops_schema()`; `patch_traits(ops) -> PatchTraits` (validated `adds_broad_wildcard: bool`); `monthly_cost(resources) -> list[CostLine]` (list-price estimates, O3) | E1, E2, E5, E6, FM1, O3 |
| `CiAdapter` | `GithubAdapter` | `read(files) -> CiRead` (Workflow and Action nodes, `USES` edges, each workflow's `CiIdentity`) | E1, FM1 |
| `CodeAdapter` | `PythonAdapter` | `read(files, rows, resources) -> CodeRead` (`CALLS`, `REQUESTS`, `HAS_ENV` edges, unknowns, calls skipped) | E1, C2 |

| Type | Fields |
| --- | --- |
| `IacResource` | `address`, `type`, `name`, `provider`, `values: dict` |
| `UnknownField` | `address`, `field`, `references: list[str]` |
| `CiIdentity` | `workflow` (node ID), `issuer`, `subjects: list[str]` |
| `Change` | `kind: Literal["remove_edge","narrow_grant","restrict_trust","deny_principal"]`, `eid`, `values: list[str]` |
| `Adapters` | `iac`, `cloud`, `ci`, `code` |

## MCP tools (`mcp/tools.py`)

One registry serves both the MCP server and the LLM's in-process fix loop. Every tool is read-only, except
`simulate_fix`, which only creates a candidate graph. Each tool's input is a JSON object:

| Tool | Input | Returns |
| --- | --- | --- |
| `diff_paths` | `base`, `head` (graph names) | opened, closed and unchanged keys with routes |
| `blast_radius` | `graph`, `sources` (node IDs) | reachable sensitive targets, with routes |
| `check_requirements` | `graph` | each requirement's status |
| `choke_points` | `graph`, `top` (int) | node IDs with betweenness scores |
| `explain_path` | `graph`, `actor`, `target` | the route with each step's evidence |
| `min_cut` | `graph`, `sources`, `sinks` (optional) | value, cuttable, cut edges |
| `shortest_route` | `graph`, `source`, `target` | the shortest valid route, or none |
| `simulate_fix` | `graph` (head), `candidate_id`, `ops` | a `Candidate` with its verdict |
| `unused_grants` | `graph` | `UnusedGrant` list |
| `secrets_reachable` | `graph`, `sources` | secret IDs |

Never exposed to a model: posting comments, committing, opening PRs. The API does those, only after a person's command.

## API (`api/routes.py`)

Calls from the GitHub Action carry `X-Theseus-Token`. Webhooks are verified with the App's webhook secret.

| Route | Body | Returns | Side effect |
| --- | --- | --- | --- |
| `GET /health` | | `{status, falkordb, version}` | |
| `POST /analyze` | `{repo, pr_number, base_sha, head_sha, pr_title, pr_body, base_plan, head_plan, checkov}` or `{fixture}` | `AnalysisResult` | With a repo: reads the world root (`THESEUS_WORLD_ROOT`) at both SHAs, posts or updates the PR comment and the check run |
| `POST /finding` | `{repo, advisory}` or `{fixture}` | `AnalysisResult` | With a repo: opens the containment PR and an issue listing secrets to rotate |
| `POST /scan` | `{repo}` or `{fixture}` | `AnalysisResult` | With a repo: opens an issue, and a PR for each passing U candidate |
| `POST /review-failed` | `{repo, head_sha, run_url}` | `204` | From `Theseus publish` when the Theseus workflow failed: fails the commit's `Theseus` check with a link to the run, unless a verdict is already there (`07-github-and-deploy.md`, "When Theseus reviews") |
| `POST /apply` | `{repo, pr_number, candidate_id, requested_by}` | `{commit_sha}` | Commits the candidate's `.tf` edits to the PR branch. Refuses any file outside the world root |
| `POST /webhooks/github` | GitHub payload | `204` | From a user with write access, `issue_comment` with `/theseus apply <ID>` calls apply and `/theseus review` re-runs the review; `check_run` `rerequested` re-runs the review; a `pull_request` that changes nothing under the world root gets a `success` check; `pull_request` closed deletes graphs; `push` to `main` runs a scan (`07-github-and-deploy.md`, "When Theseus reviews") |
| `GET /reviews/{owner}/{repo}/{number}?k=` | | the review page | A 404 unless `k` is the PR's signature (`07-github-and-deploy.md`, "The review page") |
| `GET /reviews/{owner}/{repo}/{number}/data?k=` | | `{repo, number, base_sha, head_sha, world_root, verdict, result, graphs: {head, base}}` | The PR's newest result and both graphs, read from the store now; each graph as `{name, nodes, edges}` |
| `POST /posture` | `{repo, sha, plan, trigger}` | `{repo, sha, graph, dangerous, unused_grants, single_points, monthly_usd, findings, contained, containment_failed, dashboard}` | From the `Theseus main` workflow (`push` to `main`, nightly, on demand): builds `main`'s graph, runs the scan and the posture (`contracts/posture.py`), runs finding mode for each advisory in `THESEUS_ADVISORIES` that affects a workflow on `main`, opens each finding's containment PR and rotate issue when K passes (FM6), and keeps it all for the dashboard. The dashboard's link comes back in `X-Theseus-Page` |
| `GET /dashboard/{owner}/{repo}?k=` | | the dashboard | A 404 unless `k` is the repo's dashboard signature (an HMAC of `dashboard:<repo>`, like the review page's) |
| `GET /dashboard/{owner}/{repo}/data?k=` | | `{repo, posture, main_graph, reviews, findings, onboarding}` | `main`'s newest posture, every PR review and every finding, read from the store now |
| `GET /graphs` | | graph names | For the "under the hood" shot |
| `GET /` and `POST /try/{preset}` | | the Try-it page; an `AnalysisResult` | Runs the live engine on a fixture, with the LLM replayed |

## The PR comment (`agent/templates/comment.md`)

Written for a reader with no context, at 3 a.m.: what they need to decide sits in a card at the top, in plain
words, and everything technical is folded below. Every sentence comes from a template over facts in the result,
in the plain words of `engine/words.py`; no model writes prose in the comment.

**The card** is five lines with no headings: it says what happened, why it is a risk and what to do, for a
reader who has never heard of Theseus, in short plain sentences. A PR is not merged yet, so the card says what it
*would* do; a finding or a scan reads `main` as it is. The check run's summary is the same card.

1. The marker `<!-- theseus:pr-comment -->`, so the comment is updated in place, never duplicated
2. The status, which is also the check run's (`render.verdict`; `07-github-and-deploy.md`, "Blocking a merge"):
   🔴 "Merge blocked" when a dangerous path opened or code reads data beyond intent; 🟡 "Needs a look" when only
   something Theseus could not check remains; 🟢 "No new access to sensitive data" otherwise. Outside PR mode the
   red status reads "Sensitive data at risk", and the headline follows it in bold
3. **The consequence**, in bold: "**This PR would let priya-intern read and change customer-db**, which holds
   personal, payment or health data." The most serious path in the `render._rank` order, its access from the
   path's grants; or "This PR would make billing-api's code read customer-db"; or what Theseus couldn't
   check; or "No new access to sensitive data." A warning follows when the intent is suspicious
4. **The PR says:** the PR's purpose in the model's plain words, or "nothing about what it's for" (PR mode)
5. **It asked for · It would get:** the access the PR asked for, then the opened targets, most sensitive first,
   at most three and a count; "Its code would read" for uses beyond intent. Together, lines 4 and 5 say section
   18's headline of `04-engine.md`, which stays in the result for the Action's log and the Try-it page
6. **How:** the most serious path in one line, each hop in plain words with its own access (`PathStep.grants`):
   "is in", "can become", "can read", "opens"; the hop this change adds or edits linked to its line, marked
   "new". Or the code line that reads beyond intent
7. **Fix:** one thing: the recommended fix and its command, with what Theseus tested it for; a passing fix that
   needs a closer look; that no fix passes; or, with no fix to test, to ask the author to grant only what the
   PR asked for, why it needs this access, or, when it asks for sensitive data on purpose, that an owner
   approves it in `theseus.yaml`

**The connections** (`render.connections`), under the card and above every fold: every opened path drawn as
one Mermaid `flowchart LR`. Each node is its name and what it is ("priya-intern", "user"); each arrow is the
hop's own access in plain words ("is in", "can read", "opens"); a hop shared by several paths is drawn once;
the hop this change adds or edits is a thick red arrow marked "new"; and sensitive targets are shaded. With more than 12 nodes, it draws the three most serious paths, then only the most serious one. A line
under it says what the colours mean. The check run's summary stops before it: the Checks tab draws no diagrams.

**Folded sections** (`<details>`), each shown only when it has something:

8. **Step by step:** what's at risk (each exposed target, most sensitive first, at most five: its
   name, what it is, and what its class means; a secret that unlocks another listed target is "the key that
   opens" it), a table of opened paths (actor, target with its class, hops), then, for each of the three most
   sensitive, a numbered list of its steps, each linked to `blob/<head_sha>/<world root>/<file>#L<line>` or
   saying why its evidence is unknown: GitHub does not run links inside Mermaid. With no opened path, what's at
   risk is its own section
9. **All fixes Theseus tested:** the minimum cut in one sentence ("No single permission can be removed without
   breaking required access" or "One change closes every path: `<edge>`"); the fix table: ID, fix (its title
   and who proposed it), dangerous paths ("all closed" or "2 left, 1 new"), required access ("kept" or "breaks
   R3"), code calls ("kept" or what breaks), verdict (with "needs a closer look" after Jev's veto), the
   recommended row in bold; "Reply `/theseus apply <ID>` to commit a fix.", naming only fixes that pass; and,
   if nothing passes, a sentence that says so
10. **What Theseus couldn't check:** the unknowns
11. **Details:** Checkov's result on the same commit and why it can pass while a path opens; where
    the graph was built ("Built in FalkorDB 4.22.0: 70 nodes and 146 edges for the head commit; the engine took
    3.1 s."); what
    the change does ("Adds `a`. Opens 3 dangerous paths, closes 0."), the tool trace, unchanged paths, coverage
    ("Read <n> resources, modeled <m>; skipped <k> of types Theseus does not model, such as <the three most
    common>"), timings, and the versions in `models`
12. **About Theseus:** two sentences for a reader who has never seen it

**Notes on the lines** (`render.annotations`): the check run also carries a note on each line this change adds
or edits on a dangerous path ("This line opens 3 new ways to reach sensitive data: customer-db (database), ..."),
and on each code line that reads beyond intent. GitHub shows them beside those lines in Files changed. Plain
text, at most 50.

Every value from a result is escaped before it reaches markdown: a PR author, a model, an advisory or a
Terraform file may have written it. Links and @-mentions in such text show as code, so they neither link nor
notify. Long lists stop at 20 opened paths, 30 unchanged paths, 40 tool calls and 20 unknowns, so the comment
stays under GitHub's 65,536 characters.

## Fixture folders and `expected.json`

```
fixtures/<scenario>/
  scenario.yaml        name, mode (pr | finding | scan), world, one-line description
  base/                the world root at base: terraform/, services/, theseus.yaml, workflows/<org>/<repo>/*.yml
  head/                the same at head (PR mode only)
  base.plan.json       from tools/plan.sh base/terraform
  head.plan.json       from tools/plan.sh head/terraform (PR mode only)
  pr.md                first line "# <title>", then the body (PR mode only)
  advisory.json        finding mode only
  expected.json        written by humans; never by an agent
```

`expected.json` holds only what we compare. A missing field is not compared.

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
  "rotate": [],
  "unused_grants": [],
  "use_beyond_intent": [],
  "staging_to_prod": []
}
```

**How `project()` shapes a result and `compare()` reads `expected.json`:**

- Every key in the example is projected, plus `headline`, `unchanged`, `unknowns`, `intent.purpose`,
  `intent.stated` and `changes`. A key missing from `expected.json` is not compared, and neither is a field
  missing inside a compared item.
- Paths are matched by (actor, target). `route` is compared in order. `cites` (one `file:line` per step, or
  `unknown`) and every other list are compared as sets.
- Tuples keep the file short: `intent.grants` and `unused_grants` and `use_beyond_intent` are
  `[principal or workload, access or resource, ...]` as in the example; `min_cut.cut` is
  `[src, TYPE, dst]`; `staging_to_prod` is `[actor, target]`; `changes` is `[action, address]`.
- `min_cut.value_at_least` is a lower bound on the projected `value`.

The line numbers in `cites` above are placeholders: humans fill in the real ones from `demo-infra/` once F4 is
merged. For a cuttable result, `min_cut` is `{"value": 1, "cuttable": true, "cut": [["<src>", "<TYPE>", "<dst>"]]}`.
