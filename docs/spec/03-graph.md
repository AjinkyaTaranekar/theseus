# 03. Graph

Every node is a part of the infrastructure, every edge is a permission or a connection, and every edge
carries the evidence that proves it. Constants for everything below live in `theseus/contracts/schema.py`.

## Node IDs

IDs are strings, unique within a graph, and the same in every state of the same world.

| Kind | ID pattern | Example |
| --- | --- | --- |
| user | `user:<name>` | `user:priya-intern` |
| group | `group:<name>` | `group:support-engineers` |
| role | `role:<name>` | `role:prod-support` |
| workload | `workload:<name>`: the Lambda function name or the ECS service name | `workload:billing-api`, `workload:orders-api` |
| workflow | `workflow:<org>/<repo>/<file>` | `workflow:demo-org/docs-site/preview.yml` |
| action | `action:<owner>/<repo>` | `action:demo-thirdparty/file-diff` |
| entry | `entry:internet` | `entry:internet` |
| s3 resource | `s3://<bucket>/<prefix>` (prefix may be empty) | `s3://demo-company-files/invoices/` |
| secret resource | `secret:<name>` | `secret:prod-db-credentials` |
| db resource | `db:<identifier>` | `db:customer-db` |
| dynamodb resource | `dynamodb:<table>` | `dynamodb:demo-orders` |
| requirement | `req:<id>` | `req:R1`, `req:I1` (intent) |
| finding | `finding:<id>` | `finding:GHSA-demo-0001` |

## Labels and properties

Every node has the label `:Node` and one kind label. Users, groups, roles, workloads, workflows and the
entry also carry `:Principal`.

| Kind label | Extra labels | Properties beyond the common ones |
| --- | --- | --- |
| `User` | `Principal` | `arn` |
| `Group` | `Principal` | `arn` |
| `Role` | `Principal` | `arn`, `address` |
| `Workload` | `Principal` | `runtime` (`lambda` or `ecs`), `address` (the function or the ECS service), `code_path` (folder under `services/` from the `theseus_code_path` tag, or null) |
| `Workflow` | `Principal` | `repo`, `file`, `subs` (list of OIDC `sub` values it can present), `id_token` (bool) |
| `Action` | | `version` |
| `Entry` | `Principal` | none |
| `Resource` | | `kind` (`s3`, `secret`, `db`, `dynamodb`), `arn_pattern`, `address` |
| `Requirement` | | `req_id`, `access` (`read`, `write`, `assume`), `source` (`config`, `intent`) |
| `Finding` | | `finding_id`, `summary` (untrusted text, never evidence) |

Common properties on every node: `id`, `name` (the human label), `env` (`staging` or `prod`), and for
`Resource` nodes: `sensitivity` (`public`, `internal`, `confidential`, `regulated` or null),
`sensitive` (bool), `sensitivity_source` (`jev`, `human` or `unclassified`).

## Edges

| Type | From, to | Edge properties | Kind | Derived from |
| --- | --- | --- | --- | --- |
| `MEMBER_OF` | User to Group | | configured | `aws_iam_user_group_membership` |
| `CAN_ASSUME` | User, Group, Role to Role | | configured or unknown | The caller's `sts:AssumeRole` permission plus the target's trust policy |
| `TRUSTS` | Workflow to Role | | configured or unknown | GitHub OIDC trust matched against the workflow's `subs` (needs `id-token: write`) |
| `RUNS_AS` | Workload to Role | | configured | `aws_lambda_function.role`, or the `task_role_arn` of the task definition an `aws_ecs_service` runs |
| `USES` | Workflow to Action | `version`, `line` | configured | A `uses:` line in the workflow file |
| `CAN` | Principal to Resource | `grants` (list of `read`, `write`) | configured or unknown | Identity policies (inline and attached), and S3 bucket policies for `entry:internet` |
| `UNLOCKS` | Resource (secret) to Resource (db) | `grants` (`read`, `write`) | inferred | The secret's `db_instance` tag |
| `CALLS` | Workload to Resource | `action`, `access`, `file`, `line` | configured | Python code (task C2) |
| `REQUESTS` | Workload to Workload | `file`, `line` | configured | Python code calling another service's URL |
| `HAS_ENV` | Workload to Resource or Workload | `var` | configured | The Lambda's `environment` block, or the ECS task definition's container `environment` |
| `FOR` | Requirement to Principal | | configured | `theseus.yaml` or the PR's intent |
| `NEEDS` | Requirement to Resource | `access` | configured | Same |
| `AFFECTS` | Finding to Action or Workload | | assumed | The advisory |

Common properties on every edge: `eid` (`e1`, `e2`, ... stable within a build), `kind` (`configured`,
`inferred`, `assumed`, `unknown`), `evidence` (JSON string, a list of Evidence objects), `capacity` (int,
set before each max-flow call, default 1).

**Evidence object:** `{"address": "aws_iam_role_policy.prod_support_read", "sid": "ReadDbSecret",
"file": "terraform/roles.tf", "line": 31, "note": null}`. For workflow edges, `address` is the workflow
path; for code edges, `address` is the Python file and `sid` is null.

**Traversal and grant edges.** Paths move along `MEMBER_OF`, `CAN_ASSUME`, `TRUSTS` and `RUNS_AS`, and end
on a grant edge: `CAN`, or `CAN` to a secret followed by `UNLOCKS`. `CALLS`, `REQUESTS`, `HAS_ENV`, `USES`,
`FOR`, `NEEDS` and `AFFECTS` are never traversed by the path query.

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

Each one must be verified against the FalkorDB version we run (task P1). The engine filters paths in Python
afterwards, so the Cypher stays simple.

```cypher
// Q_PATHS: every route from one actor to a resource. The engine keeps only valid routes (04-engine.md).
MATCH p = (a:Node {id: $actor})-[:MEMBER_OF|CAN_ASSUME|TRUSTS|RUNS_AS|CAN|UNLOCKS*1..7]->(r:Resource)
RETURN [rel IN relationships(p) | rel.eid] AS eids
```

```cypher
// Q_SET_CAPACITY: before each max-flow call
UNWIND $rows AS r MATCH ()-[e {eid: r.eid}]->() SET e.capacity = r.capacity
```

```cypher
// Q_MAXFLOW: sources are the actor(s); sinks are its dangerous targets
MATCH (s:Node) WHERE s.id IN $sources WITH collect(s) AS ss
MATCH (t:Node) WHERE t.id IN $sinks WITH ss, collect(t) AS ts
CALL algo.maxFlow({sourceNodes: ss, targetNodes: ts, capacityProperty: 'capacity',
                   relationshipTypes: ['MEMBER_OF', 'CAN_ASSUME', 'TRUSTS', 'RUNS_AS', 'CAN', 'UNLOCKS']})
YIELD maxFlow, edges, edgeFlows
RETURN maxFlow, [e IN edges | e.eid] AS eids, edgeFlows
```

```cypher
// Q_BETWEENNESS: choke points
CALL algo.betweenness({}) YIELD node, score
RETURN node.id AS id, score ORDER BY score DESC
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
WITH w, c, r, collect(x.access) AS used
WHERE NONE(g IN c.grants WHERE g IN used)
RETURN w.id AS workload, r.id AS resource, c.eid AS eid
```

```cypher
// Q_CALLS: every code call, for usage capacities and "use beyond intent"
MATCH (w:Workload)-[x:CALLS]->(r:Resource)
RETURN w.id AS workload, r.id AS resource, x.access AS access, x.eid AS eid
```

If `algo.maxFlow` is missing or its output is unusable (found in P1 or E4), the engine runs Edmonds-Karp in
Python on the same edges and capacities, and the README says so.
