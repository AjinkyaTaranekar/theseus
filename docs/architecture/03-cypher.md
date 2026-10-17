# 03. Cypher

This page lists every Cypher query Theseus runs against FalkorDB. The text is copied from
[`theseus/graph/queries.py`](../../theseus/graph/queries.py) and [`theseus/graph/store.py`](../../theseus/graph/store.py);
when you change a query there, change it here.

All queries run through one method, `FalkorStore._query(graph, cypher, params)`, which selects the graph and
turns any Redis error into a `GraphError`. Values always go in as parameters (`$actor`, `$rows`), never pasted
into the query text. The only text that is built is a label set or an edge type, which Cypher cannot take as a
parameter, and those come from the schema constants, never from user input.

The example results below are real: they come from running the store on the `intern` fixture's head graph,
`fx__intern__head`.

## Contents

| Query | Answers | Used by |
| --- | --- | --- |
| [`Q_PATHS`](#q_paths-every-route-from-an-actor) | Every route from one actor to a resource | PR, finding, scan, posture, the MCP tools |
| [`Q_SET_FLOW`](#q_set_flow-the-flow-network) | Writes the network max flow runs on | The minimum cut |
| [`Q_MAXFLOW`](#q_maxflow-the-maximum-flow) | The maximum flow from the actors to their dangerous targets | The minimum cut |
| [`Q_REL_TYPES`](#q_rel_types-and-q_betweenness-choke-points) | Which relationship types the graph has | `betweenness` |
| [`Q_BETWEENNESS`](#q_rel_types-and-q_betweenness-choke-points) | FalkorDB's betweenness score per node | `betweenness` (not shown in results; see below) |
| [`Q_WORKFLOWS_USING`](#q_workflows_using-who-runs-this-action) | Which workflows use an Action, at which version | Finding mode |
| [`Q_UNUSED_GRANTS`](#q_unused_grants-grants-no-code-uses) | Grants on a workload's role to sensitive data its code never calls | Scan mode, posture |
| [`Q_CALLS`](#q_calls-every-code-call) | Every code call, one row per access | Capacities, "use beyond intent" |
| [Loading queries](#loading-a-graph) | Create nodes, the index, edges; delete edges and nodes | `load`, `apply_delta` |
| [View queries](#reading-a-whole-graph-back) | Every node and every edge, as stored | The review page, the dashboard's Graph view |
| [Document queries](#the-documents-graph) | Keep and read results by key or prefix | The pages and the dashboard |

## Q_PATHS: every route from an actor

**Question:** from this actor (a user, a workflow, a service, or `entry:internet`), which routes of traversal
and grant edges end at a resource?

In the code it is built from the schema, so the edge list and the hop limit cannot drift apart:

```python
Q_PATHS = (
    f"MATCH p = (a:Node {{id: $actor}})-[:{'|'.join(PATH_TYPES)}*1..{MAX_PATH_EDGES}]->(r:Resource) "
    "RETURN [rel IN relationships(p) | rel.eid] AS eids"
)
```

With `PATH_TYPES` and `MAX_PATH_EDGES = 7` from `theseus/contracts/schema.py`, FalkorDB receives:

```cypher
MATCH p = (a:Node {id: $actor})-[:MEMBER_OF|CAN_ASSUME|TRUSTS|RUNS_AS|CAN|UNLOCKS*1..7]->(r:Resource)
RETURN [rel IN relationships(p) | rel.eid] AS eids
```

- **Parameters:** `$actor`, a node ID such as `user:priya-intern`.
- **Returns:** one row per route, the list of its edges' `eid`s.
- **Called by:** `FalkorStore.paths`, from `analyze` in `theseus/engine/analyze.py`, once per actor per graph.
- **Example:** `paths("fx__intern__head", "user:priya-intern")` returns 4 routes. The first three:

  | eids | Steps |
  | --- | --- |
  | `e136, e91, e66` | `MEMBER_OF` support-engineers, `CAN_ASSUME` prod-support, `CAN` `s3://demo-app-logs/` |
  | `e136, e91, e67` | the same, then `CAN` `s3://demo-company-files/invoices/` |
  | `e136, e91, e68` | the same, then `CAN` `secret:prod-db-credentials` |

**Why only `eid`s?** The engine already holds every edge's full row in memory (`GraphRows`), so the query only
needs to say *which* edges form each route. That keeps the result small.

**Why the engine filters afterwards.** Cypher's variable-length match may revisit a node, and it allows any
order of edge types. A **valid path** is stricter ([spec 04](../spec/04-engine.md), section 9): no node twice,
traversal edges first, then one `CAN`, then optionally one `UNLOCKS` when the `CAN` reached a secret.
`_record` in `theseus/engine/analyze.py` drops every route that breaks those rules. Doing the walk in FalkorDB
and the rules in Python keeps the query simple, and the rules testable.

## Q_SET_FLOW: the flow network

**Question:** none. This query writes the network that `Q_MAXFLOW` runs on.

```cypher
MATCH ()-[f:FLOW]->() DELETE f
WITH count(*) AS dropped
UNWIND $rows AS r
MATCH (a:Node {id: r.src}), (b:Node {id: r.dst})
CREATE (a)-[:FLOW {eids: r.eids, capacity: r.capacity}]->(b)
```

- **Parameters:** `$rows`, a list of `{src, dst, eids, capacity}` built by `capacities` in
  `theseus/engine/mincut.py`: one row per ordered pair of nodes joined by traversal or grant edges, with the
  pair's capacities summed and its `eids` sorted.
- **Returns:** nothing used.
- **Called by:** `FalkorStore.max_flow`, right before `Q_MAXFLOW`.
- **Example:** on the intern's head graph, 98 rows, such as `group:data-analysts` to `role:analytics-read` with
  capacity 1,000,000, because a `theseus.yaml` requirement needs that edge.

**Why FLOW edges?** FalkorDB's `algo.maxFlow` takes exactly one relationship type and refuses parallel edges of
that type. Our graph has six path types and can have two edges between the same pair. So before each max-flow
call, the engine writes one `FLOW` edge per pair, deleting the previous set first. The capacities decide what the
cut may remove:

| Capacity | Edges |
| --- | --- |
| `BIG` = 1,000,000 | Every `RUNS_AS` and `UNLOCKS` edge, and every edge on a path that satisfies a `theseus.yaml` requirement or an approved intent requirement |
| `USED` = 1,000 | A `CAN` edge that a service's code uses (a `CALLS` edge from a workload running as that role, to the same resource, with a shared access) |
| 1 | Every other edge |

## Q_MAXFLOW: the maximum flow

**Question:** how much "flow" can go from these actors to their dangerous targets over the `FLOW` network?

```cypher
MATCH (s:Node) WHERE s.id IN $sources WITH collect(s) AS ss
MATCH (t:Node) WHERE t.id IN $sinks WITH ss, collect(t) AS ts
CALL algo.maxFlow({sourceNodes: ss, targetNodes: ts, capacityProperty: 'capacity',
                   relationshipTypes: ['FLOW']})
YIELD maxFlow, edges, edgeFlows
RETURN maxFlow, [e IN edges | e.eids] AS eids, edgeFlows
```

- **Parameters:** `$sources`, the actors with opened dangerous paths; `$sinks`, their dangerous targets minus any
  source (FalkorDB refuses overlapping sets).
- **Returns:** one row: the flow value, and for each edge that carries flow its `eids` and its flow.
- **Called by:** `FalkorStore.max_flow`, from `min_cut` in `theseus/engine/mincut.py`.
- **Example:** with only `theseus.yaml`'s requirements, `priya-intern`'s flow is 1, carried by her membership
  `e136`. In the intern PR, her own intent requirement ("read the app logs") protects that membership too, so
  the value reaches 1,000,000 or more: no cut keeps every requirement, and the answer key says
  `cuttable: false` (`fixtures/intern/expected.json`).

**From flow to cut.** Max flow returns flows, not the cut. `min_cut` walks the **residual graph** from the
sources: an edge is still crossable if it has capacity left, or if flow runs backwards along it
(`reachable` in `theseus/graph/algos.py`). The cut is every `FLOW` edge from a reached node to an unreached
one; each cut `FLOW` edge stands for all the original edges in its `eids`, and each is reported with its
evidence.

**Reading the value.** A value below `BIG` means a cut exists that breaks no requirement: `cuttable` is true.
A value of `BIG` or more means every cut would break something a requirement needs, so a simple removal cannot
fix it, and the fix agent is asked to design a structural fix such as a new, narrower role.

**Fallback.** If the FalkorDB call fails, `max_flow` in `theseus/graph/algos.py` runs Edmonds-Karp in Python on
the same rows, and logs that it did.

## Q_REL_TYPES and Q_BETWEENNESS: choke points

```cypher
CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType
```

```cypher
CALL algo.betweenness({relationshipTypes: $types}) YIELD node, score
RETURN node.id AS id, score ORDER BY score DESC, id
```

- **Parameters:** `$types`, the path types this graph actually has. `algo.betweenness` fails on a type the
  graph lacks, so `Q_REL_TYPES` runs first and the store keeps only the types it returns.
- **Returns:** every node with its betweenness score, highest first.
- **Called by:** `FalkorStore.betweenness`.

**Why results use Python's score instead.** A **choke point** is a role that many routes pass through.
`algo.betweenness` is a sampled estimate: on the `compromised-action` graph its ranking changed from one run to
the next, and a ranking that changes between runs is not a fact the engine can report. So `choke_points` in
`theseus/graph/algos.py` computes the exact score with Brandes' algorithm on the state's rows, and keeps the top
5 roles. `store.betweenness` still answers for anyone who wants FalkorDB's own numbers.

## Q_WORKFLOWS_USING: who runs this Action

**Question:** which workflows use this GitHub Action, and at which version?

```cypher
MATCH (w:Workflow)-[u:USES]->(:Action {id: $action})
RETURN w.id AS workflow, u.version AS version
```

- **Parameters:** `$action`, such as `action:demo-thirdparty/file-diff`.
- **Returns:** one row per workflow that uses it.
- **Called by:** `FalkorStore.workflows_using`, at the start of finding mode.
- **Example:** `workflow:demo-org/docs-site/preview.yml` and `workflow:demo-org/website/lint.yml`, both at `v3`.

## Q_UNUSED_GRANTS: grants no code uses

**Question:** which grants on a service's own role reach sensitive data that the service's code never calls?

```cypher
MATCH (w:Workload)-[:RUNS_AS]->(:Role)-[c:CAN]->(r:Resource {sensitive: true})
OPTIONAL MATCH (w)-[x:CALLS]->(r)
WITH w, c, r, x
WHERE x IS NULL OR NONE(g IN c.grants WHERE g IN x.grants)
RETURN w.id AS workload, r.id AS resource, c.eid AS eid
```

- **Parameters:** none.
- **Returns:** one row per (workload, resource, grant edge) with no matching call. A call that exists but uses a
  different access (the code writes, the grant only reads) still counts as unused.
- **Called by:** `FalkorStore.unused_grants`, from scan mode (`theseus/engine/usage.py`).
- **Example:** on the demo world, three rows: `invoice-mailer` and `receipt-renderer` to
  `secret:payments-api-key` (their shared role holds the grant, neither function's code reads it), and
  `support-portal` to `secret:prod-db-credentials`.

## Q_CALLS: every code call

**Question:** what does each service's code read or write?

```cypher
MATCH (w:Workload)-[x:CALLS]->(r:Resource)
UNWIND x.grants AS access
RETURN w.id AS workload, r.id AS resource, access, x.eid AS eid
```

- **Parameters:** none.
- **Returns:** one row per (workload, resource, access).
- **Called by:** `FalkorStore.calls`. The engine uses the calls to give used grants their `USED` capacity, and to
  find **use beyond intent**: a call the head adds to sensitive data that the PR did not mention.
- **Example:** `workload:analytics-export` reads `dynamodb:demo-orders` (`e1`), writes
  `s3://demo-data-lake/curated/` (`e2`).

`CALLS` edges come from reading the Python with `ast`, never running it: a `boto3` client call whose bucket,
table or secret name the reader can resolve (`theseus/adapters/python/code.py`).

## Loading a graph

From `theseus/graph/queries.py`. Labels and relationship types cannot be parameters, so each label set and each
type gets its own query text, built by a small function; the rows always go in as `$rows`.

```cypher
UNWIND $rows AS r CREATE (n:Node:Principal:User) SET n = r
```

That is `create_nodes(["Node", "Principal", "User"])`: one query per label set.

```cypher
CREATE INDEX FOR (n:Node) ON (n.id)
```

```cypher
UNWIND $rows AS r MATCH (a:Node {id: r.src}), (b:Node {id: r.dst}) CREATE (a)-[e:MEMBER_OF]->(b) SET e = r.props
```

That is `create_edges("MEMBER_OF")`: one query per edge type.

To turn a copy into a fix's graph, `apply_delta` removes what changed, then adds the new rows with the two
queries above:

```cypher
UNWIND $rows AS r MATCH (:Node {id: r.src})-[e:CAN]->(:Node {id: r.dst}) DELETE e
```

That is `delete_edges("CAN")`.

```cypher
UNWIND $ids AS i MATCH (n:Node {id: i}) DETACH DELETE n
```

That is `DELETE_NODES`.

## Reading a whole graph back

From `FalkorStore.view`, for the pages that draw a graph:

```cypher
MATCH (n:Node) RETURN labels(n), properties(n)
```

```cypher
MATCH (a:Node)-[e]->(b:Node) RETURN a.id, type(e), b.id, properties(e)
```

`_view` then sorts them, parses each edge's evidence back from JSON, and leaves out `FLOW` edges, which the
engine writes and nobody should see.

## The documents graph

From `FalkorStore` in `theseus/graph/store.py`, on the graph `theseus__docs`
([02. FalkorDB](02-falkordb.md), "The documents graph"):

```cypher
MERGE (d:Doc {key: $key}) SET d.text = $text
```

```cypher
MATCH (d:Doc {key: $key}) RETURN d.text
```

```cypher
MATCH (d:Doc) WHERE d.key STARTS WITH $prefix RETURN d.key ORDER BY d.key
```

```cypher
MATCH (d:Doc) WHERE d.key STARTS WITH $prefix RETURN d.key, d.text ORDER BY d.key
```

The last one, `read_docs`, lets the dashboard read every review of a repo in one round trip.

## Graph operations that are not Cypher

| Operation | Client call | Used for |
| --- | --- | --- |
| `GRAPH.COPY` | `db.select_graph(src).copy(dst)` | One graph per candidate fix (`FalkorStore.copy`) |
| Delete a graph | `db.select_graph(graph).delete()` | Replacing a graph before loading it |
| List graphs | `db.list_graphs()` | Checking a graph exists before reading it |
