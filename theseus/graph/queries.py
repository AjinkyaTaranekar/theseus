"""The canonical Cypher (03-graph.md, "Canonical queries" and "Loading"), each run in P1 on FalkorDB 4.22."""

from __future__ import annotations

from theseus.contracts.schema import MAX_PATH_EDGES, PATH_TYPES

# Q_PATHS: every route from one actor to a resource. The engine keeps only valid routes (04-engine.md).
Q_PATHS = (
    f"MATCH p = (a:Node {{id: $actor}})-[:{'|'.join(PATH_TYPES)}*1..{MAX_PATH_EDGES}]->(r:Resource) "
    "RETURN [rel IN relationships(p) | rel.eid] AS eids"
)

# Q_SET_FLOW: before each max-flow call, one row per (src, dst) pair of traversal and grant edges.
Q_SET_FLOW = """
MATCH ()-[f:FLOW]->() DELETE f
WITH count(*) AS dropped
UNWIND $rows AS r
MATCH (a:Node {id: r.src}), (b:Node {id: r.dst})
CREATE (a)-[:FLOW {eids: r.eids, capacity: r.capacity}]->(b)
"""

# Q_MAXFLOW: sources are the actor(s); sinks are its dangerous targets, minus any source.
Q_MAXFLOW = """
MATCH (s:Node) WHERE s.id IN $sources WITH collect(s) AS ss
MATCH (t:Node) WHERE t.id IN $sinks WITH ss, collect(t) AS ts
CALL algo.maxFlow({sourceNodes: ss, targetNodes: ts, capacityProperty: 'capacity',
                   relationshipTypes: ['FLOW']})
YIELD maxFlow, edges, edgeFlows
RETURN maxFlow, [e IN edges | e.eids] AS eids, edgeFlows
"""

# Q_REL_TYPES: the relationship types this graph has, for Q_BETWEENNESS.
Q_REL_TYPES = "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"

# Q_BETWEENNESS: choke points. $types: the traversal and grant types that Q_REL_TYPES returned.
Q_BETWEENNESS = """
CALL algo.betweenness({relationshipTypes: $types}) YIELD node, score
RETURN node.id AS id, score ORDER BY score DESC, id
"""

# Q_WORKFLOWS_USING: which workflows run a given Action (finding mode starts here).
Q_WORKFLOWS_USING = """
MATCH (w:Workflow)-[u:USES]->(:Action {id: $action})
RETURN w.id AS workflow, u.version AS version
"""

# Q_UNUSED_GRANTS: grants on a workload's own role to sensitive data that its code never calls.
Q_UNUSED_GRANTS = """
MATCH (w:Workload)-[:RUNS_AS]->(:Role)-[c:CAN]->(r:Resource {sensitive: true})
OPTIONAL MATCH (w)-[x:CALLS]->(r)
WITH w, c, r, x
WHERE x IS NULL OR NONE(g IN c.grants WHERE g IN x.grants)
RETURN w.id AS workload, r.id AS resource, c.eid AS eid
"""

# Q_CALLS: every code call, for usage capacities and "use beyond intent".
Q_CALLS = """
MATCH (w:Workload)-[x:CALLS]->(r:Resource)
UNWIND x.grants AS access
RETURN w.id AS workload, r.id AS resource, access, x.eid AS eid
"""

# Loading (03-graph.md, "Loading"): labels and relationship types cannot be parameters, so one query each.
INDEX = "CREATE INDEX FOR (n:Node) ON (n.id)"


def create_nodes(labels: list[str]) -> str:
    return f"UNWIND $rows AS r CREATE (n:{':'.join(labels)}) SET n = r"


def create_edges(edge_type: str) -> str:
    return (
        "UNWIND $rows AS r MATCH (a:Node {id: r.src}), (b:Node {id: r.dst}) "
        f"CREATE (a)-[e:{edge_type}]->(b) SET e = r.props"
    )


def delete_edges(edge_type: str) -> str:
    return f"UNWIND $rows AS r MATCH (:Node {{id: r.src}})-[e:{edge_type}]->(:Node {{id: r.dst}}) DELETE e"


DELETE_NODES = "UNWIND $ids AS i MATCH (n:Node {id: i}) DETACH DELETE n"
