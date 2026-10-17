# 09. Glossary

Terms used across these pages, in plain words. Code names are in `code font`.

| Term | Meaning |
| --- | --- |
| **Action** (GitHub Action) | A reusable step a workflow runs, such as `actions/checkout`. A node `action:<owner>/<name>` in the graph |
| **Actor** | Something that can start a path: a user, a workflow, a workload, or `entry:internet` (anyone on the internet) |
| **Adapter** | The only code that knows one vendor: `adapters/terraform/`, `aws/`, `github/`, `python/`. It turns that vendor's files into neutral graph rows |
| **Advisory** | A report that an Action is compromised, as a JSON file in `advisories/`. Starts finding mode |
| **AnalysisResult** | The engine's whole answer for one run, in `contracts/result.py`: paths, requirements, the cut, candidates, evidence |
| **Answer key** | A hand-written `fixtures/<scenario>/expected.json`: what the engine must find. Only humans edit it |
| **Articulation point** | A node whose removal splits the access graph into pieces (Tarjan's algorithm) |
| **Base, head** | The PR's target commit (before) and its latest commit (after) |
| **Blast radius** | Everything sensitive an actor could reach if it were compromised. For an outage: everything a down service takes with it |
| **Candidate** | A proposed fix: a list of patch ops, with an ID (A, B, C, D, S, K, U, or H1 for a person's) and, once simulated, a verdict |
| **Category** | What a resource holds, whatever the cloud calls it: `ObjectStorage`, `Database`, `Secret`, `LogStore` and so on. Core reasons on this, never on a vendor type |
| **Choke point** | A role that many routes pass through, by betweenness |
| **Composition root** | The only places that pick adapters and wire everything together: `cli.py` and `api/app.py` |
| **Containment** | Candidate K: limiting which workflows a role trusts, to cut off a compromised one |
| **Core** | Everything outside `adapters/`; it never names a vendor |
| **Coverage** | Whether a requirement makes a target acceptable for an actor. Also: how many resources Theseus modeled out of all it read |
| **Cypher** | The graph query language FalkorDB speaks. `MATCH (a)-[:CAN]->(r) RETURN r` reads "find what `a` can reach" |
| **Dangerous path** | A valid path to sensitive data that no `theseus.yaml` requirement covers |
| **Dependency** | Something that must keep working: a code call, or a `theseus.yaml` requirement. Used by posture and incidents |
| **Diff** | Comparing base and head paths: `opened`, `closed`, `unchanged` |
| **Documents graph** | The FalkorDB graph `theseus__docs`, where results are kept as `Doc {key, text}` nodes |
| **Edge** | A connection in the graph, such as `MEMBER_OF` or `CAN`, with evidence |
| **Engine** | The deterministic code that decides facts: `engine/`, `importer/`, `graph/` |
| **Evidence** | Where an edge comes from: the Terraform address, part, file and line |
| **FalkorDB** | The graph database Theseus runs on, a Redis module that speaks Cypher |
| **Finding mode** | Answering "what can a compromised Action reach, and how do we contain it?" |
| **FLOW edge** | A working edge the engine writes before a max-flow call, one per ordered pair of nodes with summed capacity. Never shown |
| **Fixture** | A frozen demo scenario under `fixtures/`: its base and head files, plans, PR text and answer key |
| **GRAPH.COPY** | FalkorDB's command to copy a whole graph; how each fix gets its own graph |
| **Incident** | An outage of one provider service, in one region or all: `{provider, service, region, severity}` |
| **Intent** | What the PR says it is for and which access it claims to need, read by the LLM from its title and body |
| **Jev** | TypeSafe's fast model that answers typed questions with calibrated probabilities. Rates sensitivity, steering, breakage and urgency |
| **LLM** | The large language model, GLM 5.3 by default. Reads intent and designs candidate B |
| **Max flow, minimum cut** | Graph algorithms. The minimum cut is the cheapest set of edges whose removal disconnects the actors from their dangerous targets; max flow finds it |
| **MCP** | Model Context Protocol: a standard way to give a model tools. Theseus serves ten graph tools over it |
| **Node ID** | A node's stable name: `<kind>:<name>` (`role:prod-support`) or `<scheme>://<path>` (`s3://demo-company-files/invoices/`) |
| **Outage basis** | What a posture run keeps so incidents can be answered later without the engine: service tags and each dependency's routes |
| **Patch op** | One edit a fix makes, such as `remove_membership {user, group}`, from the cloud adapter's catalog |
| **Plan** | Terraform's JSON description of every resource a commit would create, made without applying anything |
| **Posture** | The standing picture of `main`: reach, single points of failure, articulation points, unreached data, cost |
| **Principal** | Something that can act or be acted through: users, groups, roles, workloads, workflows, the internet entry |
| **Prune** | `python -m theseus prune`: lists, and with `--yes` deletes, the graphs of closed and merged PRs |
| **Record, replay, live** | The three model modes. Replay reads saved answers so tests and demos need no network |
| **Requirement** | An access something must keep: (principal, access, resource). `R<n>` from `theseus.yaml`, `I<n>` from the PR's intent |
| **Residual graph** | After max flow, the capacity left on each edge; walking it from the sources finds the cut |
| **Resource** | A data store: a storage location, a secret, a database, a table, a queue, a log group |
| **Scan** | Checking `main` for dangerous paths and grants no code uses |
| **Sensitivity** | A resource's class: `public`, `internal`, `confidential` or `regulated`. The last two are **sensitive** |
| **Signed link** | A page URL with `k=<signature>`, an HMAC of the page's key, so only people given the link can open it |
| **Single point of failure** | A node on every route of something that is needed |
| **State** | One version of the world (main, a PR's base or head, a fix), stored as its own graph |
| **Steering text** | PR text that tries to tell the reviewer what to report, approve or ignore |
| **Suggestion** | A GitHub review comment with a ` ```suggestion ` block the author can commit in one click |
| **Traversal edge** | `MEMBER_OF`, `CAN_ASSUME`, `TRUSTS`, `RUNS_AS`: "can become" or "is part of" |
| **Grant edge** | `CAN` and `UNLOCKS`: the last steps of a path, "can read or write this" |
| **`theseus.yaml`** | The world's config, reviewed by its owners: account, region, data locations, sensitivity overrides, requirements |
| **Unknown** | An edge, path or verdict that depends on something Theseus does not model. Reported, never guessed |
| **Unused grant** | Access a workload's role has to sensitive data that its code never calls |
| **Use beyond intent** | A new code call to sensitive data that the PR does not mention and `theseus.yaml` does not cover |
| **Valid path** | A simple path of at most 7 edges: traversal edges, one `CAN`, then optionally `UNLOCKS` from a secret |
| **Verdict** | A candidate's result: `pass`, `fail`, `unknown` or `invalid` |
| **Workflow** | A GitHub Actions file; a node `workflow:<org>/<repo>/<file>` that can log in to a role through OIDC trust |
| **Workload** | A running service, a Lambda function or an ECS service: `workload:<name>`, which runs as a role |
| **World root** | The folder Theseus reads and the only one it may write: `demo-infra/` in this repo |
