# 03. Graph

Every node is a part of the infrastructure, every edge is a permission or a connection, and every edge
carries the evidence that proves it. Constants for everything below live in `theseus/contracts/schema.py`.

## Node IDs

IDs are strings, unique within a graph, and the same in every state of the same world. They follow one
grammar, `<kind>:<name>`, or `<scheme>://<path>` for a location inside a store (`schema.node_id` and
`schema.location_id`). The core kinds are fixed. Resource kinds belong to the cloud adapter: the rows marked
AWS below are the AWS adapter's (`08-core-and-adapters.md`).

| Kind | ID pattern | Example |
| --- | --- | --- |
| user | `user:<name>` | `user:priya-intern` |
| group | `group:<name>` | `group:support-engineers` |
| role | `role:<name>` | `role:prod-support` |
| workload | `workload:<name>`: the Lambda function name or the ECS service name | `workload:billing-api`, `workload:orders-api` |
| workflow | `workflow:<org>/<repo>/<file>` | `workflow:demo-org/docs-site/preview.yml` |
| action | `action:<owner>/<repo>` | `action:demo-thirdparty/file-diff` |
| entry | `entry:internet` | `entry:internet` |
| s3 location (AWS, `ObjectStorage`) | `s3://<bucket>/<prefix>` (prefix may be empty) | `s3://demo-company-files/invoices/` |
| secret (AWS, `Secret`) | `secret:<name>` | `secret:prod-db-credentials` |
| db (AWS, `Database`) | `db:<identifier>` | `db:customer-db` |
| dynamodb (AWS, `Database`) | `dynamodb:<table>` | `dynamodb:demo-orders` |
| other AWS kinds | `ssm-parameter:`, `opensearch:`, `log-group:`, `sqs:`, `sns:`, `kinesis:` (`adapters/aws/catalog.yaml`) | `log-group:/aws/lambda/billing-job` |
| req (requirement) | `req:<id>` | `req:R1`, `req:I1` (intent) |
| finding | `finding:<id>` | `finding:GHSA-demo-0001` |

## Labels and properties

Every node has the label `:Node` and one kind label. Users, groups, roles, workloads, workflows and the
entry also carry `:Principal`. Nodes also carry [Cartography's ontology
labels](https://github.com/cartography-cncf/cartography/blob/master/cartography/models/ontology/labels.py)
where one fits: `UserAccount`, `UserGroup` and `PermissionRole` on users, groups and roles; a workload's from
the catalog; and a resource's category, so `MATCH (n:Database)` reads the same as on a Cartography graph.

| Kind label | Extra labels | Properties beyond the common ones |
| --- | --- | --- |
| `User` | `Principal` | `arn` (AWS) |
| `Group` | `Principal` | `arn` (AWS) |
| `Role` | `Principal` | `arn` (AWS), `address` |
| `Workload` | `Principal`, and its Cartography label where one fits (`Function`, `ComputeService`, `ComputeInstance`, `CICDPipeline`) | `runtime` (from the cloud adapter's catalog: `lambda`, `ecs`, `ec2`, ...), `address` (the function or the ECS service), `code_path` (folder under `services/` from the `theseus_code_path` tag, or null) |
| `Workflow` | `Principal` | `repo`, `file`, `subs` (list of OIDC `sub` values it can present), `id_token` (bool) |
| `Action` | | `version` |
| `Entry` | `Principal` | none |
| `Resource` | its category (`ObjectStorage`, `Database`, `Secret`, ...) | `kind` (the ID prefix its cloud adapter declares), `category` (one of `RESOURCE_CATEGORIES`), `provider` (`aws`), `address`, `arn_pattern` (AWS) |
| `Requirement` | | `req_id`, `access` (`read`, `write`, `assume`), `source` (`config`, `intent`) |
| `Finding` | | `finding_id`, `summary` (untrusted text, never evidence) |

Common properties on every node, typed fields on `NodeRow`: `id`, `name` (the human label), `env` (`staging`
or `prod`), and for `Resource` nodes: `category`, `provider`, `sensitivity` (`public`, `internal`,
`confidential`, `regulated` or null), `sensitive` (bool), `sensitivity_source` (`jev`,
`fallback`, `human` or `unclassified`). The per-kind properties in the table above go in `NodeRow.props`. Properties marked AWS are
set by the AWS adapter for its own use; core code never reads them, and reasons on `category`, never on
`kind`.

## Edges

Edge types are core and the same for every cloud. The "Derived from" column is how the v1 adapters (AWS,
Terraform, GitHub Actions, Python) produce each one.

| Type | From, to | Edge properties | Kind | Derived from |
| --- | --- | --- | --- | --- |
| `MEMBER_OF` | User to Group | | configured | `aws_iam_user_group_membership` |
| `CAN_ASSUME` | User, Group, Role to Role | | configured or unknown | The caller's `sts:AssumeRole` permission plus the target's trust policy |
| `TRUSTS` | Workflow to Role | | configured or unknown | GitHub OIDC trust matched against the workflow's `subs` (needs `id-token: write`) |
| `RUNS_AS` | Workload to Role | | configured | `aws_lambda_function.role`, or the `task_role_arn` of the task definition an `aws_ecs_service` runs |
| `USES` | Workflow to Action | `version`, `line` | configured | A `uses:` line in the workflow file |
| `CAN` | Principal to Resource | `grants` (list of `read`, `write`) | configured or unknown | Identity policies (inline and attached), and S3 bucket policies for `entry:internet` |
| `UNLOCKS` | Resource (secret) to Resource (db) | `grants` (`read`, `write`) | inferred | The secret's `db_instance` tag |
| `CALLS` | Workload to Resource | `grants` (the accesses, `read`, `write`), `actions` (sorted, such as `dynamodb:PutItem`) | configured | Python code (task C2). One edge per (workload, resource) however many calls; each call adds its file and line as evidence |
| `REQUESTS` | Workload to Workload | none | configured | Python code calling another service's URL. One edge per pair; each call adds its file and line as evidence |
| `HAS_ENV` | Workload to Resource or Workload | `var` | configured | The Lambda's `environment` block, or the ECS task definition's container `environment`; the code reader adds each line that reads `var` as evidence |
| `FOR` | Requirement to Principal | | configured | `theseus.yaml` or the PR's intent |
| `NEEDS` | Requirement to Resource | `access` | configured | Same |
| `AFFECTS` | Finding to Action or Workload | | assumed | The advisory |
| `FLOW` | Node to Node | `eids` (list), `capacity` | internal | Written by the engine before each max-flow call (Q_SET_FLOW): one per (source, target) pair of traversal and grant edges. Never shown, never evidence |

Common properties on every edge: `eid` (`e1`, `e2`, ... stable within a build), `kind` (`configured`,
`inferred`, `assumed`, `unknown`), `evidence` (JSON string, a list of Evidence objects). `FLOW` edges carry
only `eids` and `capacity`.

**Evidence object:** `{"address": "aws_iam_role_policy.prod_support_read", "part": "ReadDbSecret",
"file": "terraform/roles.tf", "line": 31, "note": null}`. For workflow edges, `address` is the workflow
path; for code edges, `address` is the Python file and `part` is null. `part` is the piece of the resource that
decided the edge: for AWS, an IAM statement's Sid.

**Traversal and grant edges.** Paths move along `MEMBER_OF`, `CAN_ASSUME`, `TRUSTS` and `RUNS_AS`, and end
on a grant edge: `CAN`, or `CAN` to a secret followed by `UNLOCKS`. `CALLS`, `REQUESTS`, `HAS_ENV`, `USES`,
`FOR`, `NEEDS`, `AFFECTS` and `FLOW` are never traversed by the path query.

## One graph per state

Graph names: `<world>__<state>`, using only `a-z`, `0-9`, `-` and `_`. The world is the world root's folder name
(`demo-infra` in the monorepo).

| State | Graph name |
| --- | --- |
| Default branch | `demo-infra__main` |
| PR 42 base and head | `demo-infra__pr42-base`, `demo-infra__pr42-head` |
| Candidate B on PR 42 | `demo-infra__pr42-fix-B` |
| A fixture | `fx__intern__base`, `fx__intern__head` |
| A finding | `demo-infra__finding-GHSA-demo-0001` |

A candidate is made with `GRAPH.COPY` of the head graph and then rebuilt from the patched resources, never by
deleting an edge from the picture. PR graphs are deleted when the PR closes. Candidate graphs are deleted
after the result is posted.

## Loading

1. Delete the graph if it exists.
2. Create nodes with one `UNWIND $rows` query per label combination (labels cannot be parameters).
3. Create `INDEX FOR (n:Node) ON (n.id)`.
4. Create edges with one `UNWIND $rows ... MATCH (a:Node {id: r.src}), (b:Node {id: r.dst}) CREATE` query per edge type.

## Canonical queries (`theseus/graph/queries.py`)

Each one ran in task P1 against FalkorDB 4.22.0 on FalkorDB Cloud, on a toy graph with known answers. The
engine filters paths in Python afterwards, so the Cypher stays simple.

```cypher
// Q_PATHS: every route from one actor to a resource. The engine keeps only valid routes (04-engine.md).
MATCH p = (a:Node {id: $actor})-[:MEMBER_OF|CAN_ASSUME|TRUSTS|RUNS_AS|CAN|UNLOCKS*1..7]->(r:Resource)
RETURN [rel IN relationships(p) | rel.eid] AS eids
```

```cypher
// Q_SET_FLOW: before each max-flow call. One row per (src, dst) pair of traversal and grant edges, with eids
// sorted and capacities summed (04-engine.md section 12). Replaces every FLOW edge from the last call.
MATCH ()-[f:FLOW]->() DELETE f
WITH count(*) AS dropped
UNWIND $rows AS r
MATCH (a:Node {id: r.src}), (b:Node {id: r.dst})
CREATE (a)-[:FLOW {eids: r.eids, capacity: r.capacity}]->(b)
```

```cypher
// Q_MAXFLOW: sources are the actor(s); sinks are its dangerous targets, minus any source
MATCH (s:Node) WHERE s.id IN $sources WITH collect(s) AS ss
MATCH (t:Node) WHERE t.id IN $sinks WITH ss, collect(t) AS ts
CALL algo.maxFlow({sourceNodes: ss, targetNodes: ts, capacityProperty: 'capacity', relationshipTypes: ['FLOW']})
YIELD maxFlow, edges, edgeFlows
RETURN maxFlow, [e IN edges | e.eids] AS eids, edgeFlows
```

```cypher
// Q_REL_TYPES: the relationship types this graph has, for Q_BETWEENNESS
CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType
```

```cypher
// Q_BETWEENNESS: choke points. $types: the traversal and grant types that Q_REL_TYPES returned
CALL algo.betweenness({relationshipTypes: $types}) YIELD node, score
RETURN node.id AS id, score ORDER BY score DESC, id
```

```cypher
// Q_WORKFLOWS_USING: which workflows run a given Action (finding mode starts here)
MATCH (w:Workflow)-[u:USES]->(:Action {id: $action})
RETURN w.id AS workflow, u.version AS version
```

```cypher
// Q_UNUSED_GRANTS: grants on a workload's own role to sensitive data that its code never calls
MATCH (w:Workload)-[:RUNS_AS]->(:Role)-[c:CAN]->(r:Resource {sensitive: true})
OPTIONAL MATCH (w)-[x:CALLS]->(r)
WITH w, c, r, x
WHERE x IS NULL OR NONE(g IN c.grants WHERE g IN x.grants)
RETURN w.id AS workload, r.id AS resource, c.eid AS eid
```

```cypher
// Q_CALLS: every code call, for usage capacities and "use beyond intent"
MATCH (w:Workload)-[x:CALLS]->(r:Resource)
UNWIND x.grants AS access
RETURN w.id AS workload, r.id AS resource, access, x.eid AS eid
```

### What FalkorDB 4.22 requires (found in P1)

- **`algo.maxFlow` takes exactly one relationship type.** Passing the six path types is an error, and so is
  leaving `relationshipTypes` out. That is why the engine writes `FLOW` edges (Q_SET_FLOW) and runs max flow
  over those alone.
- **No parallel edges of that type.** Two `FLOW` edges between the same ordered pair of nodes fail with "must
  not contain multi-edges", so Q_SET_FLOW merges them. Edges in opposite directions are fine.
- **Sources and sinks must not overlap**, or the call fails.
- **Output:** `maxFlow` is a float. `edges` lists only the edges that carry flow, in no fixed order, and
  `edgeFlows` matches it item by item. An edge missing from `edges` has flow 0. Sort before using either.
- **Configuration keys:** `sourceNodes`, `targetNodes`, `capacityProperty`, `relationshipTypes`. An unknown key
  is an error. `YIELD *` is not supported, so name every output.
- **`algo.betweenness`** accepts several types, but fails on a type the graph does not have (hence
  Q_REL_TYPES), and `{}` counts every type, `FLOW` and `CALLS` included. Scores are unnormalized floats.
- **`GRAPH.COPY`:** `Graph.copy(name)` in the `falkordb` client (1.8.0) took about 100 ms on the toy graph. The
  copy keeps the `Node(id)` index, and changing it leaves the source untouched.
- **Latency:** every query took 10 to 20 ms from a laptop to the instance, almost all of it network.
- **Procedures on the instance:** `algo.AStar`, `algo.BFS`, `algo.HarmonicCentrality`, `algo.MSF`,
  `algo.SPpaths`, `algo.SSpaths`, `algo.WCC`, `algo.betweenness`, `algo.labelPropagation`, `algo.maxFlow`,
  `algo.pageRank`.

If `algo.maxFlow` fails on a real graph (task E4), the engine runs Edmonds-Karp in Python on the same `FLOW`
rows, and the README says so.
