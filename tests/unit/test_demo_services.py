"""The demo company's service code (docs/spec/02-demo-world.md, "Services"), read as the code reader reads it:
with `ast`, never imported or run. Every resource name must come from an environment variable, every call in
the spec's table must exist, and the code must ask Terraform only for variables Terraform sets.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ROOT / "demo-infra" / "services"
PLAN = ROOT / "fixtures" / "intern" / "base.plan.json"

MODULES = {
    "orders_api": ["app.py", "store.py", "events.py", "billing.py"],
    "orders_worker": ["worker.py", "fulfil.py"],
    "billing_job": ["handler.py", "invoices.py", "payments.py"],
    "billing_api": ["handler.py", "db.py", "queries.py"],
    "support_portal": ["handler.py", "clients.py", "views.py"],
    "analytics_export": ["handler.py", "export.py"],
}
# The workload each folder belongs to: its Lambda function or ECS service in spec 02.
WORKLOADS = {
    "orders_api": ("ecs", "orders-api"),
    "orders_worker": ("ecs", "orders-worker"),
    "billing_job": ("lambda", "billing-job"),
    "billing_api": ("lambda", "billing-api"),
    "support_portal": ("lambda", "support-portal"),
    "analytics_export": ("lambda", "analytics-export"),
}
# Spec 02's table: (client service, method, the keyword naming the resource, the variable it comes from,
# the key's literal prefix or None). Nothing else a boto3 client calls.
BOTO_CALLS: dict[str, list[tuple[str, str, str, str, str | None]]] = {
    "orders_api/store.py": [
        ("dynamodb", "put_item", "TableName", "ORDERS_TABLE", None),
        ("dynamodb", "get_item", "TableName", "ORDERS_TABLE", None),
    ],
    "orders_api/events.py": [("sqs", "send_message", "QueueUrl", "ORDER_EVENTS_QUEUE_URL", None)],
    "orders_worker/worker.py": [
        ("sqs", "receive_message", "QueueUrl", "ORDER_EVENTS_QUEUE_URL", None),
        ("sqs", "delete_message", "QueueUrl", "ORDER_EVENTS_QUEUE_URL", None),
    ],
    "orders_worker/fulfil.py": [
        ("dynamodb", "get_item", "TableName", "ORDERS_TABLE", None),
        ("dynamodb", "update_item", "TableName", "ORDERS_TABLE", None),
    ],
    "billing_job/handler.py": [("sns", "publish", "TopicArn", "INVOICE_TOPIC_ARN", None)],
    "billing_job/invoices.py": [
        ("dynamodb", "query", "TableName", "ORDERS_TABLE", None),
        ("s3", "put_object", "Bucket", "INVOICES_BUCKET", "invoices/"),
    ],
    "billing_job/payments.py": [
        ("secretsmanager", "get_secret_value", "SecretId", "PAYMENTS_SECRET", None),
    ],
    "billing_api/db.py": [("secretsmanager", "get_secret_value", "SecretId", "DB_SECRET", None)],
    "analytics_export/export.py": [
        ("dynamodb", "scan", "TableName", "ORDERS_TABLE", None),
        ("s3", "put_object", "Bucket", "LAKE_BUCKET", "raw/orders/"),
        ("s3", "get_object", "Bucket", "LAKE_BUCKET", "raw/orders/"),
        ("s3", "put_object", "Bucket", "LAKE_BUCKET", "curated/daily_sales/"),
    ],
}
# (httpx method, the variable the URL starts with, or the literal host for the external payment provider).
HTTP_CALLS: dict[str, list[tuple[str, str]]] = {
    "orders_api/billing.py": [("get", "BILLING_API_URL")],
    "billing_job/payments.py": [("post", "https://api.payments.example")],
    "support_portal/clients.py": [
        ("get", "BILLING_API_URL"),
        ("get", "BILLING_API_URL"),
        ("get", "ORDERS_API_URL"),
    ],
}
RESOURCE_KEYWORDS = {"TableName", "Bucket", "SecretId", "QueueUrl", "TopicArn"}


def parse(relative: str) -> ast.Module:
    return ast.parse((SERVICES / relative).read_text(encoding="utf-8"), filename=relative)


def env_name(node: ast.AST) -> str | None:
    """`V` for `os.environ["V"]` or `os.getenv("V")`, else None."""
    if (
        isinstance(node, ast.Subscript)
        and ast.unparse(node.value) == "os.environ"
        and isinstance(node.slice, ast.Constant)
    ):
        return str(node.slice.value)
    if isinstance(node, ast.Call) and ast.unparse(node.func) == "os.getenv" and node.args:
        first = node.args[0]
        return str(first.value) if isinstance(first, ast.Constant) else None
    return None


def module_env(tree: ast.Module) -> dict[str, str]:
    """Module-level names assigned exactly once, from an environment variable."""
    counts: dict[str, int] = {}
    found: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign | ast.AnnAssign):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    counts[target.id] = counts.get(target.id, 0) + 1
                    if stmt.value is not None and (var := env_name(stmt.value)):
                        found[target.id] = var
    return {name: var for name, var in found.items() if counts[name] == 1}


def clients(tree: ast.Module) -> dict[str, str]:
    """Module-level names assigned from `boto3.client("<service>")`."""
    out = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            if (
                ast.unparse(call.func) == "boto3.client"
                and call.args
                and isinstance(call.args[0], ast.Constant)
            ):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        out[target.id] = str(call.args[0].value)
    return out


def resolves_to(node: ast.AST, names: dict[str, str]) -> str | None:
    """The environment variable a value comes from, directly or through a module-level name."""
    if isinstance(node, ast.Name):
        return names.get(node.id)
    return env_name(node)


def key_prefix(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        return str(node.values[0].value)
    return None


def boto_calls(relative: str) -> list[tuple[str, str, str, str, str | None]]:
    tree = parse(relative)
    names, made = module_env(tree), clients(tree)
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in made
        ):
            kwargs = {k.arg: k.value for k in node.keywords if k.arg}
            keyword = next((k for k in RESOURCE_KEYWORDS if k in kwargs), None)
            assert keyword, f"{relative}:{node.lineno} {ast.unparse(node.func)} names no resource"
            var = resolves_to(kwargs[keyword], names)
            assert var, f"{relative}:{node.lineno} {keyword} does not come from an environment variable"
            prefix = key_prefix(kwargs["Key"]) if "Key" in kwargs else None
            out.append((made[node.func.value.id], node.func.attr, keyword, var, prefix))
    return out


def http_calls(relative: str) -> list[tuple[str, str]]:
    tree = parse(relative)
    names = module_env(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if ast.unparse(node.func.value) != "httpx" or not node.args:
                continue
            url = node.args[0]
            first = url.values[0] if isinstance(url, ast.JoinedStr) and url.values else url
            if isinstance(first, ast.FormattedValue):
                var = resolves_to(first.value, names)
                assert var, f"{relative}:{node.lineno} the URL does not start with an environment variable"
                out.append((node.func.attr, var))
            else:
                text = first.value if isinstance(first, ast.Constant) else ""
                out.append((node.func.attr, "https://" + str(text).split("://", 1)[-1].split("/", 1)[0]))
    return out


ALL = [f"{folder}/{name}" for folder, names in MODULES.items() for name in names]


@pytest.mark.parametrize("relative", ALL)
def test_every_module_exists_and_reads_like_real_code(relative: str) -> None:
    path = SERVICES / relative
    lines = path.read_text(encoding="utf-8").splitlines()
    assert 40 <= len(lines) <= 150, (relative, len(lines))
    tree = parse(relative)
    assert ast.get_docstring(tree), relative
    assert "boto3.resource" not in path.read_text(encoding="utf-8")


def test_no_tests_or_other_modules_live_in_the_services() -> None:
    found = {p.relative_to(SERVICES).as_posix() for p in SERVICES.rglob("*.py")}
    assert found == set(ALL) | {f"{folder}/__init__.py" for folder in MODULES}


@pytest.mark.parametrize("relative", ALL)
def test_every_aws_call_is_the_spec_s_and_names_its_resource_from_the_environment(relative: str) -> None:
    assert sorted(boto_calls(relative)) == sorted(BOTO_CALLS.get(relative, []))


@pytest.mark.parametrize("relative", ALL)
def test_every_http_call_is_the_spec_s(relative: str) -> None:
    assert sorted(http_calls(relative)) == sorted(HTTP_CALLS.get(relative, []))


def test_billing_api_connects_to_the_database_with_the_secret() -> None:
    text = (SERVICES / "billing_api/db.py").read_text(encoding="utf-8")
    assert "psycopg.connect(" in text and 'os.environ["DB_NAME"]' in text


def test_support_portal_never_reads_a_secret_and_keeps_its_typo() -> None:
    for name in MODULES["support_portal"]:
        assert "get_secret_value" not in (SERVICES / "support_portal" / name).read_text(encoding="utf-8")
    assert "recieved" in (SERVICES / "support_portal/views.py").read_text(encoding="utf-8")


def environments() -> dict[str, set[str]]:
    """Each workload's environment variable names, from the committed plan."""
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    resources = plan["planned_values"]["root_module"]["resources"]
    out: dict[str, set[str]] = {}
    for r in resources:
        values: dict[str, Any] = r["values"]
        if r["type"] == "aws_lambda_function":
            block = values.get("environment") or [{}]
            out[f"lambda:{values['function_name']}"] = set(block[0].get("variables") or {})
        if r["type"] == "aws_ecs_task_definition":
            container = json.loads(values["container_definitions"])[0]
            out[f"ecs:{values['family']}"] = {e["name"] for e in container.get("environment", [])}
    return out


@pytest.mark.parametrize("folder", sorted(MODULES))
def test_the_code_reads_only_variables_terraform_sets(folder: str) -> None:
    runtime, name = WORKLOADS[folder]
    available = environments()[f"{runtime}:{name}"]
    for module in MODULES[folder]:
        for node in ast.walk(parse(f"{folder}/{module}")):
            var = env_name(node)
            if var:
                assert var in available, (
                    f"{folder}/{module}:{node.lineno} reads {var}, which Terraform never sets"
                )
