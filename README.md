<p align="center">
  <img src="theseus/web/logo.svg" width="112" alt="Theseus logo: a blue shield holding a graph, one coral path running down to the node it protects">
</p>

<h1 align="center">Theseus</h1>

<p align="center"><b>See what an infrastructure change really grants, before it merges.</b></p>

<p align="center">
  <a href="https://github.com/AjinkyaTaranekar/theseus/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/AjinkyaTaranekar/theseus/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="https://www.wemakedevs.org/hackathons/falkordb"><img alt="FalkorDB Graph Hacks: Track 01" src="https://img.shields.io/badge/FalkorDB_Graph_Hacks-Track_01-3F63F2"></a>
  <a href="#falkordb-and-cypher"><img alt="FalkorDB 4.22" src="https://img.shields.io/badge/FalkorDB-4.22-F2495C"></a>
  <img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&amp;logoColor=white">
  <img alt="Tests: 2258 passing" src="https://img.shields.io/badge/tests-2258_passing-73BF69">
  <a href="#try-the-tools-from-claude-code"><img alt="MCP: 10 graph tools" src="https://img.shields.io/badge/MCP-10_graph_tools-6E9FFF"></a>
  <a href="#before-the-pr-the-claude-code-plugin"><img alt="Claude Code plugin" src="https://img.shields.io/badge/Claude_Code-plugin-D97757"></a>
  <a href="https://guest-box.tail27b7c5.ts.net"><img alt="Live" src="https://img.shields.io/badge/live-online-73BF69"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-8F949D"></a>
</p>

<p align="center">
  <a href="https://guest-box.tail27b7c5.ts.net"><b>Website</b></a> ·
  <a href="https://guest-box.tail27b7c5.ts.net/dashboard/AjinkyaTaranekar/theseus?k=ea1c289117b62d09647ceab7975762cc#overview"><b>Live dashboard</b></a> ·
  <a href="#architecture"><b>Architecture</b></a> ·
  <a href="#run-it-locally"><b>Run it locally</b></a> ·
  <a href="#deploy-it"><b>Deploy</b></a> ·
  <a href="docs/architecture/"><b>Docs</b></a>
</p>

<p align="center">
  <a href="docs/media/theseus-demo.mp4"><img src="docs/media/theseus-demo-poster.jpg" width="720" alt="Watch the Theseus demo video, 2 minutes 53 seconds: the title card shows the Theseus shield logo, the line 'A graph agent that reviews infrastructure changes before they merge', and Team Project Hail Mary, Ajinkya Taranekar and Sakshi Chitnis"></a>
  <br><sub>The 2:53 demo video: <a href="docs/media/theseus-demo.mp4">play the MP4</a></sub>
</p>

<p align="center">
  <img src="theseus/web/shot-review.jpg" width="880" alt="Theseus's review of a demo pull request: it adds priya-intern to support-engineers at people.tf:83, and the graph shows four hops from her to customer-db, which holds regulated data. The merge is blocked.">
</p>

Theseus reviews every Terraform change
as a graph in FalkorDB. It traces each path from a person, workflow or service to sensitive data, compares that
with what the PR says and what the code calls, says where the change lands, proves the smallest fix on a copy of
the graph, and acts: it blocks the merge, commits the fix a person approves, and contains a compromised
workflow. Built for [FalkorDB Graph Hacks](https://www.wemakedevs.org/hackathons/falkordb), **Track 01: Agents
That Act on Connected Data**.

### See it live

| | |
| --- | --- |
| **The website** | <https://guest-box.tail27b7c5.ts.net>: every way in, how it decides, and the Try-it presets, where the real engine runs on FalkorDB |
| **The live dashboard** | [Theseus on this repository](https://guest-box.tail27b7c5.ts.net/dashboard/AjinkyaTaranekar/theseus?k=ea1c289117b62d09647ceab7975762cc#overview): `main`'s posture, pull requests, findings, incidents, who reaches what, weak points, the graph, and cost with proof |
| **Demo video** | [Watch on YouTube](https://www.youtube.com/watch?v=oKLoHeoLxqk) (2:53; the file is also in [`docs/media`](docs/media/theseus-demo.mp4)): the problem, the architecture, a pull request blocked and fixed, the plugin, and the dashboard |
| **A real review** | [Demo PR #125](https://github.com/AjinkyaTaranekar/theseus/pull/125): an intern joins a support group "to read prod logs"; Theseus comments *"This PR would let priya-intern read and change customer-db"*, and `/theseus apply` commits the fix that turns the check green |
| **More demo PRs** | [#137](https://github.com/AjinkyaTaranekar/theseus/pull/137) makes a bucket public; [#124](https://github.com/AjinkyaTaranekar/theseus/pull/124) is a typo fix whose code reads the customer database; [#129](https://github.com/AjinkyaTaranekar/theseus/pull/129) tries to steer the review; [#126](https://github.com/AjinkyaTaranekar/theseus/pull/126) offboards a contractor and closes 6 paths; [#128](https://github.com/AjinkyaTaranekar/theseus/pull/128) is safe |
| **A containment PR** | [PR #111](https://github.com/AjinkyaTaranekar/theseus/pull/111), opened by Theseus for a compromised GitHub Action, and [issue #112](https://github.com/AjinkyaTaranekar/theseus/issues/112), the secret to rotate |

### One graph, six ways in

| Surface | What it does | Where |
| --- | --- | --- |
| **GitHub agent** | Reviews every PR that touches the infrastructure: a required `Theseus` check, one comment in plain words, labels, a note on the changed line, a suggested fix. `/theseus apply` commits the fix that passed | Every PR; [demo PRs](#see-it-live) |
| **Website** | The dashboard of `main`: pull requests, findings, incidents, who reaches what, weak points and "what if this is compromised", the graph, cost with proof | [Live dashboard](https://guest-box.tail27b7c5.ts.net/dashboard/AjinkyaTaranekar/theseus?k=ea1c289117b62d09647ceab7975762cc#overview) |
| **Claude Code plugin** | The check before a PR exists: `/theseus:check`, `/theseus:investigate`, `/theseus:help`, a skill that knows the tools, and a hook that stops a commit that would open a path to sensitive data | `/plugin install theseus --marketplace AjinkyaTaranekar/theseus` ([more](#before-the-pr-the-claude-code-plugin)) |
| **MCP server** | Ten graph tools for any MCP client, and `check_change` on the working tree | `python -m theseus.mcp.server --repo .` ([more](#try-the-tools-from-claude-code)) |
| **CLI** | Check the working tree, analyze a PR, map an advisory, report `main`'s posture, rank an outage | `python -m theseus check`, `analyze`, `finding`, `posture`, `incident` |
| **The graph** | One FalkorDB graph per commit, a `GRAPH.COPY` per candidate fix, Cypher for the paths, labels from Cartography's ontology | [Graph model](#graph-model), [Cypher](#falkordb-and-cypher) |

### How it decides

Two models share one graph, and neither decides facts. **Jev**, the System One model, gives fast typed answers
with a probability: is this data sensitive, is this text steering the review, how likely is a fix to break
something. Its labels land on the graph's nodes. **The LLM**, the System Two model, reads what the PR says it
needs and designs fixes by calling the engine's graph tools. **The engine** decides what is reachable on
FalkorDB, tests every fix on a graph copy, and returns UNKNOWN where it can't model. **A person** approves every
write.

## Architecture

```mermaid
flowchart LR
  subgraph IN["Inputs"]
    PR["PR title and body"]
    TF["Terraform plan JSON"]
    CODE["Python service code"]
    WF["GitHub workflows"]
    ADV["Advisories, status feeds"]
  end
  AD["Adapters: AWS, Terraform, GitHub Actions, Python"]
  subgraph FDB["FalkorDB"]
    G1[("A graph per state: base, head, main")]
    G2[("A GRAPH.COPY per candidate fix")]
  end
  S1["System One: Jev<br/>typed answers with a probability"]
  S2["System Two: the LLM<br/>reads intent, designs fixes"]
  EN{{"Engine: Cypher paths, maxFlow cut, simulation<br/>decides facts, says UNKNOWN"}}
  OUT["Check, comment, labels, fix commit,<br/>containment PR, dashboard, MCP"]
  P(["A person approves"])
  IN --> AD --> G1
  S1 -- "labels each node's sensitivity" --> G1
  G1 <--> EN
  EN <--> G2
  S2 -- "calls the ten graph tools" --> EN
  EN --> OUT --> P
  P -- "/theseus apply" --> OUT
```

| | System One: Jev | System Two: the LLM | The engine on FalkorDB |
| --- | --- | --- | --- |
| **Its job** | Fast, typed judgments, each with a probability | Reading what the PR says it needs; designing structural fixes; explaining | Deciding facts |
| **What it is asked** | Is this resource's data sensitive? Is this PR text steering the review? How likely is this fix to break something? | What access does the PR say it needs? Which fix closes the cut without breaking a requirement? | Which paths exist? What does each fix close and what does it break? |
| **How it meets the graph** | Its answers set each node's `sensitivity` before the graph loads; an override in `theseus.yaml` always wins | Only through the ten graph tools, over MCP or in process; never by writing to the graph | Cypher on each state's graph, `algo.maxFlow` for the cut, `GRAPH.COPY` for every candidate |
| **Can it decide?** | No. It can stop an approval (steering), never grant one | No. Every fix it proposes is re-checked on a graph copy | Yes, and it returns UNKNOWN for anything outside the IAM subset it models |

**How FalkorDB carries it.** Every state of the infrastructure is its own graph: `demo-infra__pr129-base`,
`demo-infra__pr129-head`, `demo-infra__main`. Each edge keeps the file and line that created it. A
variable-length Cypher match finds every route from every actor to every resource, `algo.maxFlow` finds the
fewest edges that close the dangerous ones, and each candidate fix runs on its own `GRAPH.COPY` before it gets a
verdict. The queries are in [FalkorDB and Cypher](#falkordb-and-cypher), and the full design is in
[docs/architecture/](docs/architecture/).

### In pictures

<table>
  <tr>
    <td width="50%"><img src="theseus/web/shot-comment.jpg" alt="Theseus's comment on pull request #129: Merge blocked, what it asked for against what it would get, the cited path and a tested fix"><br><b>On the pull request.</b> What it asked for against what it would get, the path with its lines, and a fix tested on a graph copy; text that tries to steer the review is flagged and ignored.</td>
    <td width="50%"><img src="theseus/web/shot-dashboard.jpg" alt="The dashboard overview for main: where to start, then dangerous paths, blocked PRs, advisories, single points of failure, unused grants and cost"><br><b>The dashboard of main.</b> Where to start, each item with its proof.</td>
  </tr>
  <tr>
    <td width="50%"><img src="theseus/web/shot-weak.jpg" alt="Weak points: a single point of failure, every route through it, and what breaks if it goes"><br><b>Weak points.</b> A single point of failure, every route through it, and what breaks if it goes.</td>
    <td width="50%"><img src="theseus/web/shot-whatif.jpg" alt="What if shared-lambda is compromised: three sensitive resources through three routes, traced on main's graph in FalkorDB"><br><b>What if it's compromised?</b> Traced live on main's graph in FalkorDB, hop by hop.</td>
  </tr>
</table>

## How it works

**The engine decides facts; models propose; a person approves.**

1. **Read.** A GitHub Action plans the PR's base and head with Terraform (no cloud account) and sends the plan
   JSON. The backend also reads the `.tf` files for line numbers, the workflows and the Python service code.
2. **Build.** Each state becomes its own FalkorDB graph (`demo-infra__pr85-base`, `demo-infra__pr85-head`). Every
   edge carries the file and line that created it.
3. **Compare.** A variable-length Cypher match finds every route from every actor to every resource. The diff says
   which dangerous paths the PR opens. The LLM reads what the PR *says* it is for, as untrusted data, and the
   engine compares that with what it *grants*.
4. **Cut.** `algo.maxFlow`, inside FalkorDB, finds the fewest edges that close every opened route without cutting
   access a requirement in `theseus.yaml` needs.
5. **Fix.** Rule fixes and one fix the LLM designs (it calls five of the ten graph tools, in process) are each
   applied to a `GRAPH.COPY` of the head and re-analyzed. Each gets a verdict: `pass`, `fail`, `unknown` or
   `invalid`.
6. **Act.** One PR comment, a required check, labels, and the passing fix as GitHub suggestions on the PR's
   own lines. A reviewer commits a suggestion, or comments `/theseus apply`, and the GitHub App commits the
   Terraform for the fix that passed; Theseus then reviews the new head.

The same graph serves four more modes: **finding** (an advisory such as a compromised Action becomes a
containment PR and a rotate list), **scan** (dangerous paths already on `main`, and grants no code calls),
**posture** (a dashboard of who reaches what, single points of failure, articulation points and the cost with
what could be saved; [setup](docs/onboarding.md)) and **incidents** (pick or paste an outage, such as "AWS
Lambda is down in eu-west-1", or let the nightly check of AWS Health and GitHub's status page find one, and see
what goes down, who loses access and which dependencies break). How it is built:
[docs/architecture/](docs/architecture/).

![How Theseus works: three inputs, one graph per state, one human decision](docs/images/end-to-end-flow.png)

**The demo world is synthetic.** [`demo-infra/`](demo-infra/) is a made-up online store in this repo: 137
planned Terraform resources, eight Python services on Lambda and ECS, five GitHub workflows and a
`theseus.yaml`. There is no AWS account and no GitHub org behind it ([spec 02](docs/spec/02-demo-world.md)).

## Graph model

Every node is a part of the infrastructure, every edge is a permission or a connection, and every edge carries
the evidence that proves it. The full schema is [spec 03](docs/spec/03-graph.md); its constants are in
[`theseus/contracts/schema.py`](theseus/contracts/schema.py).

```mermaid
flowchart LR
  User -- MEMBER_OF --> Group
  User & Group & Role -- CAN_ASSUME --> Role
  Workflow -- TRUSTS --> Role
  Workload -- RUNS_AS --> Role
  Workflow -- USES --> Action
  Role & User & Group & Entry -- CAN --> Resource
  Secret[Resource: secret] -- UNLOCKS --> DB[Resource: database]
  Workload -- "CALLS, HAS_ENV" --> Resource
  Workload -- REQUESTS --> Workload
  Requirement -- FOR --> P[any principal]
  Requirement -- NEEDS --> Resource
  Finding -- AFFECTS --> Action
```

**Nodes.** Every node has the label `:Node`, a kind label, and `:Principal` if it can act. IDs follow one grammar,
`<kind>:<name>` or `<scheme>://<path>`, and stay the same in every state of a world. Resources also carry
[Cartography's ontology labels](https://github.com/cartography-cncf/cartography/blob/master/cartography/models/ontology/labels.py)
(`Database`, `Secret`, `ObjectStorage`, ...) and a `category`, the only thing core code reasons on.

| Kind | Example ID |
| --- | --- |
| User, Group, Role | `user:priya-intern`, `group:support-engineers`, `role:prod-support` |
| Workload (Lambda or ECS service) | `workload:billing-api` |
| Workflow, Action | `workflow:demo-org/docs-site/preview.yml`, `action:demo-thirdparty/file-diff` |
| Entry | `entry:internet` |
| Resource | `s3://demo-company-files/invoices/`, `secret:prod-db-credentials`, `db:customer-db`, `dynamodb:demo-orders` |
| Requirement, Finding | `req:R1`, `finding:GHSA-demo-0001` |

**Edges.** Paths walk the traversal edges and end on a grant edge. Code edges come from reading the Python with
`ast`, never running it. Context edges are never traversed.

| Role | Types |
| --- | --- |
| Traversal | `MEMBER_OF`, `CAN_ASSUME`, `TRUSTS` (GitHub OIDC trust matched on `sub`), `RUNS_AS` |
| Grant | `CAN` (`grants`: `read`, `write`), `UNLOCKS` (a secret to its database) |
| Code | `CALLS`, `REQUESTS`, `HAS_ENV` |
| Context | `USES`, `FOR`, `NEEDS`, `AFFECTS` |
| Internal | `FLOW`, written before each max-flow call, never shown |

Each edge has an `eid`, a `kind` (`configured`, `inferred`, `assumed` or `unknown`) and evidence such as
`{"address": "aws_iam_user_group_membership.priya_support", "file": "terraform/people.tf", "line": 83}`. The LLM's
explanations must cite evidence IDs, and a checker rejects any ID that does not exist. One state is one graph:
`demo-infra__main`, `demo-infra__pr85-head`, `demo-infra__pr85-fix-b`, `fx__intern__head`.

![The intern and a compromised Action both reach one choke point](docs/images/graph-model.png)

## FalkorDB and Cypher

All Cypher is in [`theseus/graph/queries.py`](theseus/graph/queries.py) and runs through the FalkorDB store in
[`theseus/graph/store.py`](theseus/graph/store.py); the Python algorithms are in
[`theseus/graph/algos.py`](theseus/graph/algos.py) and [`theseus/engine/posture.py`](theseus/engine/posture.py).
Each canonical query was first checked against FalkorDB 4.22.0 on a toy graph with a known answer.

**Every route from an actor** (`Q_PATHS`). The engine keeps a route only if each hop is a valid step and it ends on
one grant.

```cypher
MATCH p = (a:Node {id: $actor})-[:MEMBER_OF|CAN_ASSUME|TRUSTS|RUNS_AS|CAN|UNLOCKS*1..7]->(r:Resource)
RETURN [rel IN relationships(p) | rel.eid] AS eids
```

**The minimum cut** (`Q_SET_FLOW`, `Q_MAXFLOW`). `algo.maxFlow` takes one relationship type and no parallel edges,
so the engine first writes one `FLOW` edge per (source, target) pair with its capacity: 1,000,000 for an edge a
requirement needs, 1,000 for a grant the code calls, 1 otherwise. A max flow of 1,000,000 or more means no cut
keeps every requirement, so the agent must design a structural fix.

```cypher
MATCH ()-[f:FLOW]->() DELETE f
WITH count(*) AS dropped
UNWIND $rows AS r
MATCH (a:Node {id: r.src}), (b:Node {id: r.dst})
CREATE (a)-[:FLOW {eids: r.eids, capacity: r.capacity}]->(b)
```

```cypher
MATCH (s:Node) WHERE s.id IN $sources WITH collect(s) AS ss
MATCH (t:Node) WHERE t.id IN $sinks WITH ss, collect(t) AS ts
CALL algo.maxFlow({sourceNodes: ss, targetNodes: ts, capacityProperty: 'capacity',
                   relationshipTypes: ['FLOW']})
YIELD maxFlow, edges, edgeFlows
RETURN maxFlow, [e IN edges | e.eids] AS eids, edgeFlows
```

**Finding mode and code checks** (`Q_WORKFLOWS_USING`, `Q_UNUSED_GRANTS`, `Q_CALLS`).

```cypher
MATCH (w:Workflow)-[u:USES]->(:Action {id: $action}) RETURN w.id AS workflow, u.version AS version

MATCH (w:Workload)-[:RUNS_AS]->(:Role)-[c:CAN]->(r:Resource {sensitive: true})
OPTIONAL MATCH (w)-[x:CALLS]->(r)
WITH w, c, r, x
WHERE x IS NULL OR NONE(g IN c.grants WHERE g IN x.grants)
RETURN w.id AS workload, r.id AS resource, c.eid AS eid
```

**Choke points** (`Q_BETWEENNESS`) and **candidate fixes** (`GRAPH.COPY`, then delete and create the changed rows;
`theseus/graph/load.py`).

```cypher
CALL algo.betweenness({relationshipTypes: $types}) YIELD node, score
RETURN node.id AS id, score ORDER BY score DESC, id
```

| Algorithm | Runs in | Used for |
| --- | --- | --- |
| Variable-length path match | FalkorDB | Every route on base, head and each candidate graph |
| `algo.maxFlow` on `FLOW` edges | FalkorDB | The minimum cut in PR, finding and scan modes. Edmonds-Karp in Python runs on the same rows only if the call fails, and logs it |
| `GRAPH.COPY` | FalkorDB | One graph per candidate fix, so a fix is tested without touching the head |
| Residual walk after max flow | Python | Turning flows into the cut edges, each with its evidence |
| Brandes betweenness | Python | Choke points. `algo.betweenness` is a sampled estimate whose ranking changed between runs on one graph, and a ranking that changes is not a fact, so results use the exact score |
| Tarjan's articulation points | Python | Posture: nodes whose removal splits the access graph |

**The product does not run without FalkorDB.** `theseus serve` refuses to start without it, `/health` reports
`degraded` when it goes away, and the in-memory store exists only for offline tests.

## Run it locally

A fresh clone needs Docker and Python 3.12, and no keys: the LLM and Jev replay from [`recordings/`](recordings/),
and the engine runs live on a local FalkorDB. One command after the clone:

```bash
git clone https://github.com/AjinkyaTaranekar/theseus.git && cd theseus
```

```bash
docker run -d -p 6379:6379 falkordb/falkordb:v4.22.0 && python3.12 -m venv .venv && .venv/bin/pip install -e . && .venv/bin/python -m theseus serve
```

Open <http://localhost:8000> and pick a preset; `GET /health` answers `{"status":"ok","falkordb":"4.22.0",...}`. If
port 6379 is taken, map another (`-p 6380:6379`) and start the API with `FALKORDB_PORT=6380`. On Windows use
`py -3.12 -m venv .venv` and `.venv\Scripts\...`. For FalkorDB Cloud, copy `.env.example` to `.env` and fill in
the `FALKORDB_*` settings.

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q                 # offline: unit, golden, contract, replay, e2e
.venv/bin/pytest -q -m falkordb     # the same answers from FalkorDB as from the in-memory store
```

Check a change on your own machine before a PR (Terraform on the PATH, no cloud account), or ask the graph from
Claude Code:

```bash
.venv/bin/python -m theseus check --intent "Logs for Priya"   # exit 2 when the change would be blocked
/plugin install theseus --marketplace AjinkyaTaranekar/theseus  # inside Claude Code; set THESEUS_PYTHON first
```

To review your own pull requests, install the GitHub App and add `theseus.yaml` and the workflows:
[docs/onboarding.md](docs/onboarding.md). Every setting is in [`.env.example`](.env.example).

## Try the tools from Claude Code

The ten graph tools are one registry with two users. The fix agent calls five of them in process, as plain Python
calls. The same registry is also an [MCP](https://modelcontextprotocol.io) server over stdio, so an outside client
such as Claude Code can ask the graph questions itself.

| | Over MCP | In process |
| --- | --- | --- |
| Who calls | An MCP client, such as Claude Code | The fix agent (`theseus/agent/fixer.py`) |
| Tools | All ten | `explain_path`, `shortest_route`, `min_cut`, `check_requirements`, `simulate_fix` |
| Call record | The resource `theseus://tool-trace` | The result's `tool_trace`, shown in the PR comment and on the Try-it page |

[`.mcp.json`](.mcp.json) starts the server on `fixtures/intern`. It loads the fixture's two graphs into the
FalkorDB from [Run it locally](#run-it-locally) (or the one the `FALKORDB_*` settings name) and answers from the recordings, so it
needs no keys. It runs `${THESEUS_PYTHON:-python}`, and a stock macOS has no `python` on its PATH, so name your
virtualenv's Python in the shell that starts Claude Code, from the repository root:

```bash
export THESEUS_PYTHON=.venv/bin/python        # macOS and Linux
```

On Windows, in Command Prompt (`$env:THESEUS_PYTHON=".venv\Scripts\python.exe"` in PowerShell):

```bat
set THESEUS_PYTHON=.venv\Scripts\python.exe
```

Start `claude` there and accept the project's `theseus` server. `/mcp` lists it and its tools, and
`claude mcp list` shows `✓ Connected`. If it says `Failed to connect`, check that FalkorDB is running and that
`THESEUS_PYTHON` is set in the shell that started Claude Code. Then ask, for example:

> What does the intern PR open?

Claude Code calls `diff_paths` on the two loaded graphs: 3 paths opened, none closed, 23 unchanged. Priya, the
intern, now reaches `db:customer-db`, the invoices in `s3://demo-company-files/invoices/` and
`secret:prod-db-credentials`.

> What is the cheapest way to cut off Priya's access?

It calls `min_cut` on `user:priya-intern` in the head graph. The answer is `cuttable: false`: the one edge that
closes every route is her group membership (`terraform/people.tf:83`), and a requirement needs it, so a cut would
break something that must keep working.

> Why can Priya reach the customer database?

It calls `explain_path`: `user:priya-intern`, `group:support-engineers`, `role:prod-support`,
`secret:prod-db-credentials`, `db:customer-db`, each step with the file and line that created it
(`terraform/people.tf:83` and `:56`, `terraform/roles.tf:36`, `terraform/data.tf:31`).

Each answer agrees with the fixture's hand-written `expected.json`, and `theseus://tool-trace` lists the calls.
To serve another fixture, change the last argument in `.mcp.json`. With `fixtures/compromised-action`, ask which
secrets the compromised preview workflow can reach: `secrets_reachable` answers `secret:prod-db-credentials`,
the fixture's rotate list.

## Before the PR: the Claude Code plugin

The plugin in [`plugins/theseus`](plugins/theseus) brings the same review to a developer's terminal, before a
commit or a pull request exists. Install it from this repository's marketplace:

```text
/plugin install theseus --marketplace AjinkyaTaranekar/theseus
```

Its server needs `THESEUS_PYTHON` set as above (a plugin's config takes no default), FalkorDB from
[Run it locally](#run-it-locally), and Terraform on the PATH. Plans need no cloud account.

| Part | What it does |
| --- | --- |
| `check_change` (MCP) | Plans the working tree and `main`, loads both into FalkorDB, and returns the verdict, each opened path hop by hop with its file and line, where the change lands, and the fix tested on a graph copy. The ten graph tools then answer about this change. |
| `/theseus:check [what it's for]` | Runs the check now. |
| `/theseus:investigate <question>` | Asks the graph, for example "what if casey-contractor is compromised?" |
| `/theseus:help` | What the plugin does and how to set it up. |
| The `theseus` skill | Tells Claude when to check and how to report: facts only from the tools, every hop cited, UNKNOWN kept. |
| The hook | Before `git commit`, `git push` or `gh pr create`, runs the check. A change that opens a path to sensitive data is stopped once, with the reason and the fix; running it again asks. Other commands pass at once. |

The same check runs without Claude Code; it exits 2 when the change would be blocked:

```bash
python -m theseus check --intent "Logs for Priya"
```

On the intern change (Priya added to `support-engineers`, not yet committed), it prints:

```text
Theseus check: BLOCKED. priya-intern can reach customer-db.
The change adds aws_iam_user_group_membership.priya_support.
It opens 3 dangerous paths and closes 0.
Impact: Lands on support-engineers, which 2 people and services reach; priya-intern gains access to 4
resources; 3 dependencies run through it, all kept.

How:
  1. priya-intern is in support-engineers (terraform/people.tf:83, new) → can become prod-support
     (terraform/people.tf:56) → can read prod-db-credentials (terraform/roles.tf:36) → opens customer-db
     (terraform/data.tf:31). customer-db holds personal, payment or health data.
  …
Fix A: Revert the added access. Tested on a copy of the graph: closes all 3 ways in, breaks nothing.
  remove_membership(group=support-engineers, user=priya-intern)
Built in FalkorDB: 86 nodes, 189 edges; 6.3 s.
```

The first check downloads the AWS provider once, several hundred megabytes kept in `.theseus/`, which took
about two minutes here. Later checks took about 15 seconds, and a side that has not changed is not planned
again.

## Live deployment

<https://guest-box.tail27b7c5.ts.net> serves the front page at `/` (every surface, the live dashboard and the
Try-it presets) and the health check at
[`/health`](https://guest-box.tail27b7c5.ts.net/health). It is a container on an Oracle ARM host, published
through Tailscale Funnel, with FalkorDB on FalkorDB Cloud, and it also receives the GitHub App's webhooks for the
demo PRs. How it is set up and deployed: [deploy/README.md](deploy/README.md).

## Deploy it

Theseus is one FastAPI container beside FalkorDB (FalkorDB Cloud or the `falkordb/falkordb` image). Full steps,
the App's permissions and recovery are in [deploy/README.md](deploy/README.md).

1. **Settings.** Copy [`.env.example`](.env.example) to `.env`: the `FALKORDB_*` connection, `THESEUS_TOKEN` (a
   long random string that signs every page link), `THESEUS_REPOS`, `THESEUS_WORLD_ROOT`, `DOMAIN`, and the
   GitHub App's ID, key and webhook secret.
2. **The GitHub App.** Create it from [`deploy/github-app-manifest.json`](deploy/github-app-manifest.json) and
   install it on the repository. It comments, checks and labels, and commits a fix only after a person asks.
3. **Run it.**
   - On a host with Docker and public ports: `deploy/deploy.sh user@host` runs
     [`deploy/docker-compose.yml`](deploy/docker-compose.yml) (the API and Caddy for HTTPS), waits for `/health`,
     and rolls back if it fails.
   - Behind Tailscale Funnel, as the live demo is: **Actions → Deploy → Run workflow**, or
     `gh workflow run deploy.yml -f ref=main`.
4. **Connect a repository.** Add `theseus.yaml` and the three workflows, set `THESEUS_URL` and `THESEUS_TOKEN` in
   the repository, require the `Theseus` check on `main`, and build `main`'s graph once from Actions
   ([docs/onboarding.md](docs/onboarding.md)). The dashboard's Setup page ticks off each step.

## Results

On a fresh clone of `main`, `pytest -q` gives 2,052 passed and 33 skipped (the FalkorDB tests; without Node,
two more skip), and `pytest -q -m falkordb` against a local FalkorDB 4.22.0 gives 33 passed. The golden tests
compare paths, requirements, the cut, verdicts and the rotate list with each scenario's hand-written
`expected.json`. The Try-it presets, on that clone, with FalkorDB in Docker on an Apple laptop:

| Preset | Opened dangerous paths | Max flow | Fix verdicts | Engine time |
| --- | --- | --- | --- | --- |
| `intern` | 3: `customer-db`, `prod-db-credentials`, `invoices/` | 1,000,000, not cuttable | A fail, B pass, C unknown, D fail | 1.4 s (first run) |
| `public-bucket` | 1: `entry:internet` to `invoices/` | 1 | A fail, S pass | 0.33 s |
| `code-pr` | none; *"Your code now reads customer-db"* | | | 0.11 s |

Fix B in the intern case is the LLM's own design, replayed from one live GLM 5.3 run: a new role,
`intern-logs-read`, that reads only the app logs and trusts her, a grant to assume it, and her removal from
`support-engineers`.

**Benchmark against Checkov:** _S2 numbers go here: cases, true and false positives against Checkov, misses, and
timings on a large generated graph._

## Limits

**A path is a modeled path under labeled assumptions, not proof that an attacker can get in.**

- **The IAM subset.** `Allow` and `Deny`, wildcards, inline and attached policies, assume-role trust and GitHub
  OIDC trust on `aud` and `sub`. Anything else (`NotAction`, other condition keys, permission boundaries, SCPs, KMS
  key policies) returns UNKNOWN instead of a guess, which is why fix C is UNKNOWN in the intern case.
- **It may over-report, never under-report,** when one group's `Deny` meets another group's `Allow`.
- **Not modeled:** privilege escalation by rewriting IAM, and network reachability.
- **Static code reading** resolves literals, environment variables and module constants. Values built at run
  time produce no edge and are listed as unknowns, so a grant reached only that way looks unused.
- **One cloud, one IaC format, one language** today (AWS, Terraform, GitHub Actions, Python), each behind an
  adapter, so a second cloud is a new adapter, not an engine change ([spec 08](docs/spec/08-core-and-adapters.md)).
- **Our own test data.** We wrote the demo world, its PRs and their answer keys.

## How we used AI

**Building it.** The spec, the task briefs and the planning documents were written before the event as notes,
which [rule 8](https://www.wemakedevs.org/hackathons/falkordb/rules) allows; product code started after it.
Claude Code and Codex wrote much of the code from those briefs, one task per branch, and the other person reviewed
every diff. Humans wrote every `expected.json`, and a hook blocks agents from writing them.
[`AI_USE.md`](AI_USE.md) records which agent wrote what in each task and what the humans changed, every agent
commit names it in a `Co-Authored-By` trailer, and [`AGENTS.md`](AGENTS.md) holds the rules every agent reads.

**Inside the product.** The LLM (GLM 5.3 on Crusoe, through LiteLLM) reads PR intent and designs one candidate fix
by calling five read-only or sandboxed tools of the registry, in process and not over MCP; it has no tool that
comments or commits. [The same registry is an MCP server](#try-the-tools-from-claude-code) for outside clients
such as Claude Code. Jev (TypeSafe) answers fast
typed questions, such as how sensitive a resource is, and can veto a fix but never approve one. PR text and
advisories reach a model only inside `<untrusted_...>` tags and never count as evidence.

## More

[The spec](docs/spec/README.md) · [task briefs](docs/tasks/README.md) · [plan](docs/plan-of-action.md) ·
[project overview and roadmap](docs/project-overview.md). Built on [FalkorDB](https://docs.falkordb.com/), with
ideas from [Cartography](https://github.com/cartography-cncf/cartography); [Checkov](https://www.checkov.io/) runs
beside Theseus in the same Action. Licensed under the [MIT License](LICENSE).
