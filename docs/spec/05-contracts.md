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
│   ├── contracts/
│   │   ├── schema.py                 labels, edge types, ID helpers, BIG, USED            F2
│   │   ├── result.py                 shared Pydantic models, AnalysisResult, project()    F2
│   │   └── engine.py                 Protocols for the engine functions                   F2
│   ├── importer/
│   │   ├── world.py                  load a world folder or a fetched commit              E1
│   │   ├── plan.py                   plan JSON to resources and unknown fields            E1
│   │   ├── source_index.py           file and line for addresses and Sids                 E1
│   │   ├── build.py                  resources to nodes and edges (structure)             E1
│   │   ├── iam.py                    evaluate, trust_kind, glob matching                  E2
│   │   ├── policies.py               a principal's statements: inline, attached, managed  E2
│   │   ├── aws_managed.py            the few AWS-managed policies we expand               E2
│   │   ├── access.py                 CAN and CAN_ASSUME edges, bucket policies            E2
│   │   ├── workflows.py              workflow YAML: per-job subs, id-token, uses          FM1
│   │   ├── oidc.py                   OIDC matching and TRUSTS edges                       FM1
│   │   └── code.py                   Python AST: CALLS, REQUESTS, HAS_ENV                 C2
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
│   │   ├── patch.py                  the patch-op catalog on resources                    E5
│   │   ├── simulate.py               copy, apply delta, re-analyze, verdict               E5
│   │   ├── candidates.py             rule candidates A, C, D, S and ranking               E6
│   │   ├── render_tf.py              patch ops as .tf text edits                          E9
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

All are Pydantic v2 models. Lists are sorted before a result is returned.

| Model | Fields |
| --- | --- |
| `Evidence` | `address: str`, `sid: str \| None`, `file: str`, `line: int \| None`, `note: str \| None` |
| `NodeRow` | `id: str`, `labels: list[str]`, `props: dict` |
| `EdgeRow` | `eid: str`, `type: str`, `src: str`, `dst: str`, `kind: str`, `grants: list[str]`, `evidence: list[Evidence]`, `props: dict` |
| `GraphRows` | `nodes: list[NodeRow]`, `edges: list[EdgeRow]`, `unknowns: list[str]` |
| `Requirement` | `id: str`, `principal: str`, `access: Literal["read","write","assume"]`, `resource: str`, `source: Literal["config","intent"]` |
| `Grant` | `principal: str`, `access: str`, `resource: str` |
| `Intent` | `purpose: str`, `grants: list[Grant]`, `suspicious: bool` |
| `PathStep` | `src: str` (serialized as `from`), `edge: str`, `dst: str` (serialized as `to`), `evidence: str` (an evidence ID) |
| `PathRecord` | `id: str`, `actor: str`, `target: str`, `grants: list[str]`, `steps: list[PathStep]`, `unknown: bool`, `inferred: bool`, `sensitivity: str \| None` |
| `RequirementStatus` | `id: str`, `status: Literal["satisfied","missing","unknown"]` |
| `CutEdge` | `eid: str`, `src: str`, `type: str`, `dst: str`, `evidence: str` |
| `MinCut` | `sources: list[str]`, `sinks: list[str]`, `value: int`, `cuttable: bool`, `cut: list[CutEdge]` |
| `PatchOp` | `op: str` plus the fields in `04-engine.md` section 13, all optional |
| `Candidate` | `id: str`, `source: Literal["rule","llm"]`, `title: str`, `ops: list[PatchOp]`, `verdict: Literal["pass","fail","unknown","invalid"]`, `reason: str`, `paths_left: list[str]`, `new_paths: list[str]`, `requirements_broken: list[str]`, `calls_broken: list[str]`, `unknown: list[str]`, `recommended: bool`, `needs_closer_look: bool`, `seconds: float` |
| `UnusedGrant` | `workload: str`, `resource: str`, `access: str`, `eid: str`, `evidence: str` |
| `BeyondIntent` | `workload: str`, `resource: str`, `access: str`, `file: str`, `line: int`, `unlocks: list[str]` |
| `StagingToProd` | `actor: str`, `target: str`, `path_id: str` |
| `ChokePoint` | `id: str`, `score: float` |
| `ToolCall` | `tool: str`, `input: dict`, `summary: str`, `ms: int` |
| `Timings` | `engine_ms: int`, `llm_ms: int`, `jev_ms: int`, `total_ms: int` |
| `Coverage` | `resources: int`, `modeled: int`, `skipped_types: dict[str, int]`, `code_calls_skipped: int` |
| `AnalysisResult` | `scenario: str \| None`, `mode: Literal["pr","finding","scan"]`, `repo: str \| None`, `pr_number: int \| None`, `graphs: dict[str,str]`, `intent: Intent \| None`, `headline: str`, `opened`, `closed`, `unchanged: list[PathRecord]`, `requirements: list[RequirementStatus]`, `unknowns: list[str]`, `min_cut: MinCut \| None`, `candidates: list[Candidate]`, `rotate: list[str]`, `unused_grants: list[UnusedGrant]`, `use_beyond_intent: list[BeyondIntent]`, `staging_to_prod: list[StagingToProd]`, `choke_points: list[ChokePoint]`, `finding: dict \| None`, `evidence: dict[str, Evidence]`, `tool_trace: list[ToolCall]`, `timings: Timings`, `coverage: Coverage` |

`project(result) -> dict` returns the comparable part of a result, in the `expected.json` shape below.

## Engine functions (`contracts/engine.py`)

| Function | Inputs | Output | Module |
| --- | --- | --- | --- |
| `load_world` | a world root (`demo-infra/`, a fixture side) or a fetched commit | `World` (resources, skipped types, unknowns, tf files, workflows, code files, config) | `importer/world.py` |
| `build_rows` | `World`, sensitivity labels | `GraphRows` | `importer/build.py` |
| `load_graph`, `copy_graph`, `delete_graph`, `apply_delta` | client, graph name, rows | none | `graph/load.py` |
| `analyze` | client, graph name, rows, requirements, actors | `Analysis` (paths per actor, dangerous paths, requirement statuses) | `engine/analyze.py` |
| `diff` | base `Analysis`, head `Analysis` | opened, closed, unchanged | `engine/analyze.py` |
| `min_cut` | client, graph name, rows, `Analysis`, sources, requirements | `MinCut` | `engine/mincut.py` |
| `apply_ops` | resources, ops, config | patched resources, or `PatchError` | `engine/patch.py` |
| `simulate` | client, head world and rows, ops, actors, requirements, candidate ID | `Candidate` | `engine/simulate.py` |
| `rule_candidates`, `rank` | rows, analysis, opened paths, cut | candidate drafts; ranked `Candidate` list | `engine/candidates.py` |
| `render_tf` | `.tf` file texts, ops | edited file texts, or `PatchError` | `engine/render_tf.py` |
| `blast_radius`, `rotate_list`, `containment` | client, graph, matched workflows | paths, secret IDs, ops | `engine/finding.py` |
| `staging_to_prod` | `Analysis`, rows | `StagingToProd` list | `engine/staging.py` (task FM4) |
| `unused_grants`, `use_beyond_intent` | client, graph, rows (base and head for the second) | lists | `engine/usage.py` |
| `choke_points` | client, graph | `ChokePoint` list | `graph/algos.py` |
| `run_pr`, `run_finding`, `run_scan` | worlds, PR text or advisory, `Deps` (client, LLM, Jev, settings) | `AnalysisResult` | `engine/pipeline.py` |

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
| `POST /apply` | `{repo, pr_number, candidate_id, requested_by}` | `{commit_sha}` | Commits the candidate's `.tf` edits to the PR branch. Refuses any file outside the world root |
| `POST /webhooks/github` | GitHub payload | `204` | `issue_comment` with `/theseus apply <ID>` from a user with write access calls apply; `pull_request` closed deletes graphs; `push` to `main` runs a scan |
| `GET /graphs` | | graph names | For the "under the hood" shot |
| `GET /` and `POST /try/{preset}` | | the Try-it page; an `AnalysisResult` | Runs the live engine on a fixture, with the LLM replayed |

## The PR comment (`agent/templates/comment.md`)

1. The marker `<!-- theseus:pr-comment -->`, so the comment is updated in place, never duplicated
2. The headline from section 18 of `04-engine.md`
3. Opened paths: a table (actor, target, hops), then one Mermaid `flowchart LR` per opened path (at most 3), each
   step linked to `blob/<head_sha>/<file>#L<line>`
4. Checkov's result on the same commit, one line
5. The minimum cut in one sentence: "No single permission can be removed without breaking required access"
   or "One change closes every path: `<edge>`"
6. The fix table: ID, fix, dangerous paths, required access, code calls, verdict; the recommended row in bold
7. "Reply `/theseus apply <ID>` to commit a fix."
8. Unknowns, if any
9. A collapsed details block: tool trace, unchanged paths, coverage ("Read <n> resources, modeled <m>; skipped <k>
   of types Theseus does not model, such as <the three most common>"), timings, model and Jev versions

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

The line numbers in `cites` above are placeholders: humans fill in the real ones from `demo-infra/` once F4 is
merged. For a cuttable result, `min_cut` is `{"value": 1, "cuttable": true, "cut": [["<src>", "<TYPE>", "<dst>"]]}`.
