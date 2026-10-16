"""Service code into CALLS, REQUESTS and HAS_ENV edges, read with `ast`, never run (04-engine.md section 7).

Every fact a call needs comes from the rows the cloud adapter built. A folder's workload is the Workload node
whose `code_path` names it; an env var names what that workload's HAS_ENV edges with that `var` point at; a
database is what a secret the workload reads UNLOCKS. So this module knows Python and boto3, never the IaC.
"""

from __future__ import annotations

import ast
import logging
import posixpath
from collections import defaultdict
from dataclasses import dataclass, field
from typing import cast
from urllib.parse import urlsplit

from theseus.contracts.adapters import CodeRead, IacResource
from theseus.contracts.result import EdgeRow, EdgeType, Evidence, GraphRows, NodeRow

log = logging.getLogger(__name__)

# (boto3 service, method) -> (action, access). Any other call on a client is counted as skipped.
SDK_CALLS: dict[tuple[str, str], tuple[str, str]] = {
    ("s3", "put_object"): ("s3:PutObject", "write"),
    ("s3", "get_object"): ("s3:GetObject", "read"),
    ("dynamodb", "get_item"): ("dynamodb:GetItem", "read"),
    ("dynamodb", "batch_get_item"): ("dynamodb:BatchGetItem", "read"),
    ("dynamodb", "query"): ("dynamodb:Query", "read"),
    ("dynamodb", "scan"): ("dynamodb:Scan", "read"),
    ("dynamodb", "put_item"): ("dynamodb:PutItem", "write"),
    ("dynamodb", "update_item"): ("dynamodb:UpdateItem", "write"),
    ("dynamodb", "delete_item"): ("dynamodb:DeleteItem", "write"),
    ("dynamodb", "batch_write_item"): ("dynamodb:BatchWriteItem", "write"),
    ("secretsmanager", "get_secret_value"): ("secretsmanager:GetSecretValue", "read"),
}
HTTP_MODULES = {"httpx", "requests"}
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "request", "stream"}
CONNECTS = {("psycopg", "connect"), ("psycopg2", "connect"), ("sqlalchemy", "create_engine")}


@dataclass(frozen=True)
class Value:
    """What an expression is known to be: literal text (all of it, or its start), or an env var's value."""

    text: str = ""
    var: str | None = None
    whole: bool = True


@dataclass
class Call:
    """One call this reader models, found in one file."""

    kind: str  # "sdk", "http" or "connect"
    path: str
    line: int
    name: str  # the call as written, such as `_ddb.put_item`
    service: str = ""
    method: str = ""
    args: dict[str, Value | None] = field(default_factory=dict)
    tables: list[Value | None] = field(default_factory=list)


@dataclass
class Scan:
    """What one file holds: the calls it makes, the env vars it reads, and calls it skips."""

    path: str
    calls: list[Call] = field(default_factory=list)
    env_reads: list[tuple[str, int]] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)


def _env_var(node: ast.AST) -> str | None:
    """V for `os.environ["V"]` or `os.getenv("V")`."""
    if (
        isinstance(node, ast.Subscript)
        and ast.unparse(node.value) == "os.environ"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    ):
        return node.slice.value
    if (
        isinstance(node, ast.Call)
        and ast.unparse(node.func) == "os.getenv"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    return None


def _constants(tree: ast.Module) -> dict[str, ast.expr]:
    """Names assigned exactly once at module level, to the expression assigned. Imported names are not."""
    seen: dict[str, list[ast.expr | None]] = defaultdict(list)
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        seen[name.id].append(stmt.value if target is name else None)
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)) and isinstance(stmt.target, ast.Name):
            seen[stmt.target.id].append(stmt.value if isinstance(stmt, ast.AnnAssign) else None)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                seen[(alias.asname or alias.name).split(".")[0]].append(None)
    return {name: values[0] for name, values in seen.items() if len(values) == 1 and values[0] is not None}


def _value(
    node: ast.AST | None, constants: dict[str, ast.expr], seen: frozenset[str] = frozenset()
) -> Value | None:
    """The expression's value, resolved through literals, env vars, module constants and string heads."""
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return Value(node.value) if isinstance(node.value, str) else None
    var = _env_var(node)
    if var is not None:
        return Value(var=var)
    if isinstance(node, ast.Name):
        if node.id in seen or node.id not in constants:
            return None
        return _value(constants[node.id], constants, seen | {node.id})
    if isinstance(node, ast.JoinedStr):
        return _join(node.values, constants, seen)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        parts: list[ast.expr] = []
        while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            parts.insert(0, node.right)
            node = node.left
        return _join([node, *parts], constants, seen)
    return None


def _join(parts: list[ast.expr], constants: dict[str, ast.expr], seen: frozenset[str]) -> Value | None:
    """Concatenated parts: known while each part is literal; the first part that is not makes the rest `*`."""
    out: Value | None = None
    for part in parts:
        if isinstance(part, ast.FormattedValue):
            plain = part.conversion == -1 and part.format_spec is None
            value = _value(part.value, constants, seen) if plain else None
        else:
            value = _value(part, constants, seen)
        if out is None:
            if value is None:
                return None
            out = value
        elif value is not None and value.var is None and out.var is None:
            out = Value(out.text + value.text, whole=value.whole)
        else:
            out = Value(out.text, out.var, whole=False)
        if not out.whole:
            return out
    return out


def _clients(scope: ast.AST) -> dict[str, str]:
    """Names assigned from `boto3.client("<service>")` in this scope, to their service."""
    body = scope.body if isinstance(scope, ast.Module) else list(ast.walk(scope))
    found: dict[str, str] = {}
    for stmt in body:
        if not (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)):
            continue
        call = stmt.value
        if ast.unparse(call.func) != "boto3.client":
            continue
        service = (
            call.args[0]
            if call.args
            else next((k.value for k in call.keywords if k.arg == "service_name"), None)
        )
        if isinstance(service, ast.Constant) and isinstance(service.value, str):
            found.update({t.id: service.value for t in stmt.targets if isinstance(t, ast.Name)})
    return found


class _Reader(ast.NodeVisitor):
    def __init__(self, path: str, tree: ast.Module) -> None:
        self.path = path
        self.constants = _constants(tree)
        self.scopes = [_clients(tree)]
        self.scan = Scan(path)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scopes.append({**self.scopes[-1], **_clients(node)})
        self.generic_visit(node)
        self.scopes.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_Subscript(self, node: ast.Subscript) -> None:
        var = _env_var(node)
        if var is not None:
            self.scan.env_reads.append((var, node.lineno))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        var = _env_var(node)
        if var is not None:
            self.scan.env_reads.append((var, node.lineno))
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            owner, method, name = func.value.id, func.attr, ast.unparse(func)
            keywords = {k.arg: k.value for k in node.keywords if k.arg}
            service = self.scopes[-1].get(owner)
            if service is not None:
                self._sdk(node, name, service, method, keywords)
            elif owner in HTTP_MODULES and method in HTTP_METHODS:
                position = 1 if method in {"request", "stream"} else 0
                url = node.args[position] if len(node.args) > position else keywords.get("url")
                value = _value(url, self.constants)
                self.scan.calls.append(Call("http", self.path, node.lineno, name, args={"url": value}))
            elif (owner, method) in CONNECTS:
                self.scan.calls.append(Call("connect", self.path, node.lineno, name))
        self.generic_visit(node)

    def _sdk(
        self, node: ast.Call, name: str, service: str, method: str, keywords: dict[str, ast.expr]
    ) -> None:
        if (service, method) not in SDK_CALLS:
            self.scan.skipped.append((node.lineno, name))
            return
        call = Call("sdk", self.path, node.lineno, name, service=service, method=method)
        if method.startswith("batch_"):
            items = keywords.get("RequestItems")
            call.tables = (
                [_value(k, self.constants) for k in items.keys]
                if isinstance(items, ast.Dict) and items.keys and None not in items.keys
                else [None]
            )
        else:
            target = {"s3": "Bucket", "dynamodb": "TableName", "secretsmanager": "SecretId"}[service]
            call.args = {"target": _value(keywords.get(target), self.constants)}
            if service == "s3":
                call.args["key"] = _value(keywords.get("Key"), self.constants)
        self.scan.calls.append(call)


@dataclass
class _Edge:
    grants: set[str] = field(default_factory=set)
    actions: set[str] = field(default_factory=set)
    evidence: set[tuple[str, int]] = field(default_factory=set)
    var: str | None = None


class _Graph:
    """The facts a call is resolved against, indexed from the cloud adapter's rows."""

    def __init__(self, rows: GraphRows) -> None:
        self.nodes: dict[str, NodeRow] = {n.id: n for n in rows.nodes}
        self.claims: dict[str, list[str]] = defaultdict(list)
        for n in rows.nodes:
            path = n.props.get("code_path")
            if "Workload" in n.labels and isinstance(path, str) and path.strip("/"):
                self.claims[posixpath.normpath(path.strip("/"))].append(n.id)
        self.env: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.unlocks: dict[str, list[str]] = defaultdict(list)
        for e in rows.edges:
            if e.type == "HAS_ENV" and isinstance(e.props.get("var"), str):
                self.env[(e.src, e.props["var"])].append(e.dst)
            elif e.type == "UNLOCKS":
                self.unlocks[e.src].append(e.dst)

    def kind(self, node_id: str) -> str | None:
        node = self.nodes.get(node_id)
        return node.props.get("kind") if node is not None and "Resource" in node.labels else None

    def named(self, workload: str, value: Value | None, kind: str) -> list[str]:
        """The resources of `kind` a whole value names: by literal name, or through the workload's env var."""
        if value is None or not value.whole:
            return []
        if value.var is not None:
            return sorted(t for t in self.env.get((workload, value.var), []) if self.kind(t) == kind)
        return sorted(i for i, n in self.nodes.items() if self.kind(i) == kind and n.name == value.text)

    def locations(self, workload: str, bucket: Value | None, key: Value | None) -> list[str]:
        """The bucket's s3 location with the longest prefix that the key's literal start begins with."""
        if bucket is None or not bucket.whole:
            return []
        if bucket.var is not None:
            candidates = [t for t in self.env.get((workload, bucket.var), []) if self.kind(t) == "s3"]
        else:
            candidates = [
                i for i in self.nodes if self.kind(i) == "s3" and i.startswith(f"s3://{bucket.text}/")
            ]
        start = key.text if key is not None and key.var is None else ""
        fits = [c for c in candidates if start.startswith(c.split("://", 1)[1].partition("/")[2])]
        return [max(fits, key=len)] if fits else []

    def workload_at(self, workload: str, url: Value | None) -> tuple[list[str], bool]:
        """The workloads a URL names, and whether its host is known at all (an unknown host is unresolved)."""
        if url is None:
            return [], False
        if url.var is not None:
            found = sorted(t for t in self.env.get((workload, url.var), []) if "Workload" in self._labels(t))
            return found, bool(found)
        rest = url.text.split("://", 1)[1] if "://" in url.text else None
        if rest is None or not (url.whole or any(c in rest for c in "/:?#")):
            return [], False
        host = urlsplit(url.text).hostname or ""
        target = f"workload:{host.split('.', 1)[0]}"
        return ([target] if "Workload" in self._labels(target) else []), True

    def _labels(self, node_id: str) -> list[str]:
        node = self.nodes.get(node_id)
        return node.labels if node is not None else []


def read_code(files: dict[str, str], rows: GraphRows, resources: list[IacResource]) -> CodeRead:
    """CALLS, REQUESTS and HAS_ENV edges sorted by (type, src, dst), unknowns sorted, and calls skipped.

    `resources` is part of the CodeAdapter protocol; every fact this reader needs is already in `rows`.
    """
    graph = _Graph(rows)
    folders: dict[str, list[str]] = defaultdict(list)
    for path in files:
        folders[posixpath.dirname(path)].append(path)
    edges: dict[tuple[str, str, str], _Edge] = defaultdict(_Edge)
    unknowns: set[str] = set()
    skipped = 0

    for folder in sorted(folders):
        workloads = sorted(graph.claims.get(folder, []))
        if not workloads:
            log.info("no workload claims %s; its code is skipped", folder)
            unknowns.add(f"code: {folder} is claimed by no workload")
            continue
        scans: list[Scan] = []
        for path in sorted(folders[folder]):
            try:
                tree = ast.parse(files[path], filename=path)
            except SyntaxError:
                log.info("%s does not parse; skipped", path)
                unknowns.add(f"code: {path} does not parse")
                continue
            reader = _Reader(path, tree)
            reader.visit(tree)
            scans.append(reader.scan)
        for workload in workloads:
            skipped += _resolve(workload, scans, graph, edges, unknowns)

    out = []
    for (etype, src, dst), e in sorted(edges.items()):
        evidence = [Evidence(address=f, file=f, line=n) for f, n in sorted(e.evidence)]
        props: dict[str, object] = {}
        if etype == "CALLS":
            props = {"actions": sorted(e.actions)}
        elif etype == "HAS_ENV":
            props = {"var": e.var}
        out.append(
            EdgeRow(
                eid="",
                type=cast(EdgeType, etype),
                src=src,
                dst=dst,
                kind="configured",
                grants=sorted(e.grants),
                evidence=evidence,
                props=props,
            )
        )
    return CodeRead(edges=out, unknowns=sorted(unknowns), calls_skipped=skipped)


def _resolve(
    workload: str,
    scans: list[Scan],
    graph: _Graph,
    edges: dict[tuple[str, str, str], _Edge],
    unknowns: set[str],
) -> int:
    """Add one workload's edges and unknowns; return how many of its calls were skipped."""

    def unresolved(call: Call) -> None:
        log.info("%s:%d %s: target unresolved", call.path, call.line, call.name)
        unknowns.add(f"code: {call.path}:{call.line} {call.name} target unresolved")

    def add(etype: str, dst: str, call: Call, action: str | None = None, access: str | None = None) -> None:
        edge = edges[(etype, workload, dst)]
        edge.evidence.add((call.path, call.line))
        if action and access:
            edge.actions.add(action)
            edge.grants.add(access)

    skipped = 0
    connects: list[Call] = []
    secrets: set[str] = set()
    for scan in scans:
        for line, name in scan.skipped:
            log.info("%s:%d %s: a call Theseus does not model; counted as skipped", scan.path, line, name)
        skipped += len(scan.skipped)
        for var, line in scan.env_reads:
            # Only a var whose Terraform value names a node has a HAS_ENV edge; the read adds its code line.
            for target in graph.env.get((workload, var), []):
                edge = edges[("HAS_ENV", workload, target)]
                edge.evidence.add((scan.path, line))
                edge.var = var
        for call in scan.calls:
            if call.kind == "connect":
                connects.append(call)
                continue
            if call.kind == "http":
                targets, known = graph.workload_at(workload, call.args.get("url"))
                if targets:
                    for target in targets:
                        add("REQUESTS", target, call)
                elif known:
                    log.info(
                        "%s:%d %s: a host outside the graph; counted as skipped",
                        call.path,
                        call.line,
                        call.name,
                    )
                    skipped += 1
                else:
                    unresolved(call)
                continue
            action, access = SDK_CALLS[(call.service, call.method)]
            if call.service == "s3":
                targets = graph.locations(workload, call.args.get("target"), call.args.get("key"))
            elif call.tables:
                found = [graph.named(workload, t, "dynamodb") for t in call.tables]
                targets = sorted({t for ts in found for t in ts}) if all(found) else []
            else:
                kind = "secret" if call.service == "secretsmanager" else call.service
                targets = graph.named(workload, call.args.get("target"), kind)
            if not targets:
                unresolved(call)
            for target in targets:
                add("CALLS", target, call, action, access)
                if call.service == "secretsmanager":
                    secrets.add(target)
    databases = sorted({db for s in secrets for db in graph.unlocks.get(s, [])})
    for call in connects:
        if not databases:
            unresolved(call)
        for db in databases:
            add("CALLS", db, call, "db:connect", "read")
    return skipped
