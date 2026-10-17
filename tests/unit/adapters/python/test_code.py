"""The Python code reader (04-engine.md section 7) on the demo services and on small made-up files."""

from __future__ import annotations

import ast
import random
from pathlib import Path

import pytest

from theseus.adapters.python.code import read_code
from theseus.contracts.adapters import CodeRead
from theseus.contracts.result import EdgeRow, Evidence, GraphRows, NodeRow

ROOT = Path(__file__).resolve().parents[4]
MAIN = ROOT / "demo-infra"
CODE_PR = ROOT / "fixtures/code-pr/head"

# The workloads and the data the services touch, as the cloud adapter declares them (spec 02 "The map").
WORKLOADS = {
    "orders-api": "services/orders_api",
    "orders-worker": "services/orders_worker",
    "billing-job": "services/billing_job",
    "billing-api": "services/billing_api",
    "support-portal": "services/support_portal",
    "analytics-export": "services/analytics_export",
    "invoice-mailer": "services/invoice_mailer",
    "receipt-renderer": "services/receipt_renderer",
}
RESOURCES = {
    "dynamodb:demo-orders": ("demo-orders", "dynamodb", "Database"),
    "secret:prod-db-credentials": ("prod-db-credentials", "secret", "Secret"),
    "secret:payments-api-key": ("payments-api-key", "secret", "Secret"),
    "db:customer-db": ("customer-db", "db", "Database"),
    "s3://demo-app-logs/": ("demo-app-logs", "s3", "ObjectStorage"),
    "s3://demo-company-files/invoices/": ("demo-company-files/invoices/", "s3", "ObjectStorage"),
    "s3://demo-company-files/public/": ("demo-company-files/public/", "s3", "ObjectStorage"),
    "s3://demo-data-lake/raw/": ("demo-data-lake/raw/", "s3", "ObjectStorage"),
    "s3://demo-data-lake/curated/": ("demo-data-lake/curated/", "s3", "ObjectStorage"),
    "sqs:order-events": ("order-events", "sqs", "MessageQueue"),
    "sns:invoice-created": ("invoice-created", "sns", "MessageTopic"),
    "secret:smtp-credentials": ("smtp-credentials", "secret", "Secret"),
}
# Each workload's Terraform environment, as the cloud adapter turns it into HAS_ENV (spec 02 workload table).
ENV = [
    ("orders-api", "ORDERS_TABLE", "dynamodb:demo-orders"),
    ("orders-api", "BILLING_API_URL", "workload:billing-api"),
    ("orders-worker", "ORDERS_TABLE", "dynamodb:demo-orders"),
    ("billing-job", "ORDERS_TABLE", "dynamodb:demo-orders"),
    ("billing-job", "INVOICES_BUCKET", "s3://demo-company-files/invoices/"),
    ("billing-job", "INVOICES_BUCKET", "s3://demo-company-files/public/"),
    ("billing-job", "PAYMENTS_SECRET", "secret:payments-api-key"),
    ("billing-api", "DB_SECRET", "secret:prod-db-credentials"),
    ("support-portal", "BILLING_API_URL", "workload:billing-api"),
    ("support-portal", "ORDERS_API_URL", "workload:orders-api"),
    ("analytics-export", "ORDERS_TABLE", "dynamodb:demo-orders"),
    ("analytics-export", "LAKE_BUCKET", "s3://demo-data-lake/raw/"),
    ("analytics-export", "LAKE_BUCKET", "s3://demo-data-lake/curated/"),
    ("invoice-mailer", "INVOICES_BUCKET", "s3://demo-company-files/invoices/"),
    ("invoice-mailer", "INVOICES_BUCKET", "s3://demo-company-files/public/"),
    ("invoice-mailer", "SMTP_SECRET", "secret:smtp-credentials"),
    ("receipt-renderer", "INVOICES_BUCKET", "s3://demo-company-files/invoices/"),
    ("receipt-renderer", "INVOICES_BUCKET", "s3://demo-company-files/public/"),
    ("receipt-renderer", "SMTP_SECRET", "secret:smtp-credentials"),
]
CODE_PR_ENV = [("support-portal", "DB_SECRET", "secret:prod-db-credentials")]
UNLOCKS = [("secret:prod-db-credentials", "db:customer-db")]


def graph(
    workloads: dict[str, str | None],
    resources: dict[str, tuple[str, str, str]],
    env: list[tuple[str, str, str]],
    unlocks: list[tuple[str, str]],
) -> GraphRows:
    """Rows in the shapes of 03-graph.md, as the cloud adapter hands them to the code adapter."""
    tf = Evidence(address="aws_lambda_function.x", file="terraform/services.tf", line=1)
    nodes = [
        NodeRow(
            id=f"workload:{name}",
            name=name,
            labels=["Node", "Principal", "Workload"],
            props={"runtime": "lambda", "address": f"aws_lambda_function.{name}", "code_path": path},
        )
        for name, path in workloads.items()
    ]
    nodes += [
        NodeRow(
            id=rid,
            name=name,
            labels=["Node", "Resource", category],
            category=category,
            provider="aws",
            props={"kind": kind, "address": f"x.{kind}"},
        )
        for rid, (name, kind, category) in resources.items()
    ]
    edges = [
        EdgeRow(
            eid="",
            type="HAS_ENV",
            src=f"workload:{w}",
            dst=dst,
            kind="configured",
            evidence=[tf],
            props={"var": var},
        )
        for w, var, dst in env
    ]
    edges += [
        EdgeRow(
            eid="", type="UNLOCKS", src=s, dst=d, kind="inferred", grants=["read", "write"], evidence=[tf]
        )
        for s, d in unlocks
    ]
    return GraphRows(nodes=nodes, edges=edges)


def demo_rows(extra_env: list[tuple[str, str, str]] | None = None) -> GraphRows:
    return graph(dict(WORKLOADS), RESOURCES, ENV + (extra_env or []), UNLOCKS)


def sources(root: Path) -> dict[str, str]:
    """Every service file under a world root, keyed by its path relative to the root."""
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted((root / "services").rglob("*.py"))
    }


def line_of(files: dict[str, str], path: str, needle: str) -> int:
    """The one line of `path` that contains `needle`."""
    found = [i for i, text in enumerate(files[path].splitlines(), 1) if needle in text]
    assert len(found) == 1, (path, needle, found)
    return found[0]


def edges(read: CodeRead, etype: str) -> dict[tuple[str, str], EdgeRow]:
    return {(e.src, e.dst): e for e in read.edges if e.type == etype}


def sites(edge: EdgeRow) -> list[tuple[str, int | None]]:
    return [(ev.file, ev.line) for ev in edge.evidence]


def expected_calls(
    files: dict[str, str],
) -> dict[tuple[str, str], tuple[list[str], list[str], list[tuple[str, int]]]]:
    """Spec 02's services table: (workload, resource) -> (grants, actions, call sites)."""

    def at(path: str, *needles: str) -> list[tuple[str, int]]:
        return sorted((path, line_of(files, path, n)) for n in needles)

    api, worker = "services/orders_api/store.py", "services/orders_worker/fulfil.py"
    invoices, payments = "services/billing_job/invoices.py", "services/billing_job/payments.py"
    db, export = "services/billing_api/db.py", "services/analytics_export/export.py"
    mailer, renderer = "services/invoice_mailer/handler.py", "services/receipt_renderer/handler.py"
    return {
        ("workload:invoice-mailer", "s3://demo-company-files/invoices/"): (
            ["read"],
            ["s3:GetObject"],
            at(mailer, "_s3.get_object("),
        ),
        ("workload:invoice-mailer", "secret:smtp-credentials"): (
            ["read"],
            ["secretsmanager:GetSecretValue"],
            at(mailer, "_sm.get_secret_value("),
        ),
        ("workload:receipt-renderer", "s3://demo-company-files/invoices/"): (
            ["read"],
            ["s3:GetObject"],
            at(renderer, "_s3.get_object("),
        ),
        ("workload:receipt-renderer", "secret:smtp-credentials"): (
            ["read"],
            ["secretsmanager:GetSecretValue"],
            at(renderer, "_sm.get_secret_value("),
        ),
        ("workload:orders-api", "dynamodb:demo-orders"): (
            ["read", "write"],
            ["dynamodb:GetItem", "dynamodb:PutItem"],
            at(api, "_ddb.put_item(", "_ddb.get_item("),
        ),
        ("workload:orders-worker", "dynamodb:demo-orders"): (
            ["read", "write"],
            ["dynamodb:GetItem", "dynamodb:UpdateItem"],
            at(worker, "_ddb.get_item(", "_ddb.update_item("),
        ),
        ("workload:billing-job", "dynamodb:demo-orders"): (
            ["read"],
            ["dynamodb:Query"],
            at(invoices, "_ddb.query("),
        ),
        ("workload:billing-job", "s3://demo-company-files/invoices/"): (
            ["write"],
            ["s3:PutObject"],
            at(invoices, "_s3.put_object("),
        ),
        ("workload:billing-job", "secret:payments-api-key"): (
            ["read"],
            ["secretsmanager:GetSecretValue"],
            at(payments, "_sm.get_secret_value("),
        ),
        ("workload:billing-api", "secret:prod-db-credentials"): (
            ["read"],
            ["secretsmanager:GetSecretValue"],
            at(db, "_sm.get_secret_value("),
        ),
        ("workload:billing-api", "db:customer-db"): (["read"], ["db:connect"], at(db, "psycopg.connect(")),
        ("workload:analytics-export", "dynamodb:demo-orders"): (
            ["read"],
            ["dynamodb:Scan"],
            at(export, "_ddb.scan("),
        ),
        ("workload:analytics-export", "s3://demo-data-lake/raw/"): (
            ["read", "write"],
            ["s3:GetObject", "s3:PutObject"],
            at(export, '_s3.put_object(Bucket=LAKE_BUCKET, Key=f"raw/', "_s3.get_object("),
        ),
        ("workload:analytics-export", "s3://demo-data-lake/curated/"): (
            ["write"],
            ["s3:PutObject"],
            at(export, 'Key=f"curated/'),
        ),
    }


@pytest.fixture(scope="module")
def main_files() -> dict[str, str]:
    return sources(MAIN)


@pytest.fixture(scope="module")
def main_read(main_files: dict[str, str]) -> CodeRead:
    return read_code(main_files, demo_rows(), [])


# The demo services --------------------------------------------------------------------------------------


def test_every_call_in_the_services_table_becomes_its_edge(
    main_files: dict[str, str], main_read: CodeRead
) -> None:
    calls = edges(main_read, "CALLS")
    want = expected_calls(main_files)
    assert set(calls) == set(want)
    for key, (grants, actions, at) in want.items():
        edge = calls[key]
        assert (edge.grants, edge.props, sites(edge)) == (grants, {"actions": actions}, at), key
        assert edge.kind == "configured" and edge.eid == ""
        assert all(ev.address == ev.file and ev.part is None for ev in edge.evidence)


def test_services_request_the_workloads_their_urls_name(
    main_files: dict[str, str], main_read: CodeRead
) -> None:
    billing, clients = "services/orders_api/billing.py", "services/support_portal/clients.py"
    assert {k: sites(e) for k, e in edges(main_read, "REQUESTS").items()} == {
        ("workload:orders-api", "workload:billing-api"): [
            (billing, line_of(main_files, billing, "httpx.get("))
        ],
        ("workload:support-portal", "workload:billing-api"): sorted(
            (clients, line_of(main_files, clients, n))
            for n in ("{BILLING_API_URL}/invoices", "{BILLING_API_URL}/customers")
        ),
        ("workload:support-portal", "workload:orders-api"): [
            (clients, line_of(main_files, clients, "{ORDERS_API_URL}/orders"))
        ],
    }
    assert all(not e.props and not e.grants for e in edges(main_read, "REQUESTS").values())


def test_env_reads_add_their_code_line_to_the_terraform_has_env(
    main_files: dict[str, str], main_read: CodeRead
) -> None:
    want: dict[tuple[str, str], tuple[str, list[tuple[str, int]]]] = {}
    for workload, var, target in ENV:
        folder = WORKLOADS[workload] + "/"
        reads = sorted(
            (path, i)
            for path, text in main_files.items()
            if path.startswith(folder)
            for i, line in enumerate(text.splitlines(), 1)
            if f'os.environ["{var}"]' in line
        )
        assert reads, (workload, var)
        want[(f"workload:{workload}", target)] = (var, reads)
    got = {k: (e.props["var"], sites(e)) for k, e in edges(main_read, "HAS_ENV").items()}
    assert got == want


def test_unmodeled_services_and_outside_hosts_are_counted_not_edges(main_read: CodeRead) -> None:
    # sqs send, receive and delete; sns publish; the payment provider's charge endpoint.
    assert main_read.calls_skipped == 5
    assert not {e.dst for e in main_read.edges} & {"sqs:order-events", "sns:invoice-created"}
    assert main_read.unknowns == []


def test_support_portal_calls_no_data_on_main(main_read: CodeRead) -> None:
    assert not [e for e in main_read.edges if e.type == "CALLS" and e.src == "workload:support-portal"]


def test_every_backend_call_is_an_edge_a_skip_or_an_unknown(
    main_files: dict[str, str], main_read: CodeRead
) -> None:
    found: set[tuple[str, int]] = set()
    for path, text in main_files.items():
        tree = ast.parse(text)
        clients = {
            t.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and ast.unparse(node.value.func) == "boto3.client"
            for t in node.targets
            if isinstance(t, ast.Name)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = ast.unparse(node.func.value)
                if owner in clients or ast.unparse(node.func) in {
                    "httpx.get",
                    "httpx.post",
                    "psycopg.connect",
                }:
                    found.add((path, node.lineno))
    cited = {site for e in main_read.edges if e.type in {"CALLS", "REQUESTS"} for site in sites(e)}
    assert cited <= found
    assert len(found) == len(cited) + main_read.calls_skipped + len(main_read.unknowns)


def test_code_pr_head_adds_exactly_the_two_calls_its_export_makes(main_read: CodeRead) -> None:
    files = sources(CODE_PR)
    head = read_code(files, demo_rows(CODE_PR_ENV), [])
    export = "services/support_portal/export.py"
    before, after = edges(main_read, "CALLS"), edges(head, "CALLS")
    assert {k: v for k, v in after.items() if k not in before} == {
        k: after[k]
        for k in [
            ("workload:support-portal", "secret:prod-db-credentials"),
            ("workload:support-portal", "db:customer-db"),
        ]
    }
    secret = after[("workload:support-portal", "secret:prod-db-credentials")]
    db = after[("workload:support-portal", "db:customer-db")]
    assert (secret.grants, secret.props, sites(secret)) == (
        ["read"],
        {"actions": ["secretsmanager:GetSecretValue"]},
        [(export, line_of(files, export, "_sm.get_secret_value("))],
    )
    assert (db.grants, db.props, sites(db)) == (
        ["read"],
        {"actions": ["db:connect"]},
        [(export, line_of(files, export, "psycopg.connect("))],
    )
    assert {k: sites(v) for k, v in after.items() if k in before} == {k: sites(v) for k, v in before.items()}
    has_env = edges(head, "HAS_ENV")[("workload:support-portal", "secret:prod-db-credentials")]
    assert sites(has_env) == [(export, line_of(files, export, 'os.environ["DB_SECRET"]'))]
    assert head.calls_skipped == main_read.calls_skipped and head.unknowns == []


# Small made-up worlds -----------------------------------------------------------------------------------

SMALL_RESOURCES = {
    "dynamodb:t": ("t", "dynamodb", "Database"),
    "secret:s": ("s", "secret", "Secret"),
    "db:d": ("d", "db", "Database"),
    "s3://b/in/": ("b/in/", "s3", "ObjectStorage"),
    "s3://b/out/": ("b/out/", "s3", "ObjectStorage"),
    "s3://logs/": ("logs", "s3", "ObjectStorage"),
    "s3://lake/": ("lake", "s3", "ObjectStorage"),
    "s3://lake/raw/": ("lake/raw/", "s3", "ObjectStorage"),
    "s3://lake/raw/pii/": ("lake/raw/pii/", "s3", "ObjectStorage"),
}
SMALL_ENV = [
    ("w", "TABLE", "dynamodb:t"),
    ("w", "SECRET", "secret:s"),
    ("w", "BUCKET", "s3://b/in/"),
    ("w", "BUCKET", "s3://b/out/"),
    ("w", "PEER_URL", "workload:peer"),
]


def small(files: dict[str, str]) -> CodeRead:
    rows = graph({"w": "services/w", "peer": None}, SMALL_RESOURCES, SMALL_ENV, [("secret:s", "db:d")])
    return read_code(files, rows, [])


def one(source: str) -> CodeRead:
    return small({"services/w/a.py": "import os\n\nimport boto3\nimport httpx\nimport requests\n\n" + source})


def summary(read: CodeRead) -> set[tuple[str, str, tuple[str, ...]]]:
    return {(e.type, e.dst, tuple(e.grants)) for e in read.edges if e.type != "HAS_ENV"}


@pytest.mark.parametrize(
    "source,want",
    [
        (
            'c = boto3.client("dynamodb")\nc.get_item(TableName="t", Key={})\n',
            ("CALLS", "dynamodb:t", ("read",)),
        ),
        (
            'c = boto3.client("dynamodb")\nc.put_item(TableName=os.getenv("TABLE"), Item={})\n',
            ("CALLS", "dynamodb:t", ("write",)),
        ),
        (
            'T = os.environ["TABLE"]\nc = boto3.client("dynamodb")\nc.scan(TableName=T)\n',
            ("CALLS", "dynamodb:t", ("read",)),
        ),
        (
            'B = os.environ["BUCKET"]\nc = boto3.client("s3")\n'
            'c.put_object(Bucket=B, Key=f"out/{day}.csv")\n',
            ("CALLS", "s3://b/out/", ("write",)),
        ),
        (
            'c = boto3.client("s3")\nc.get_object(Bucket="b", Key="in/" + name)\n',
            ("CALLS", "s3://b/in/", ("read",)),
        ),
        (
            'c = boto3.client("s3")\nc.put_object(Bucket="logs", Key=f"{day}/x.log")\n',
            ("CALLS", "s3://logs/", ("write",)),
        ),
        (
            'def f():\n    sm = boto3.client("secretsmanager")\n'
            '    return sm.get_secret_value(SecretId="s")\n',
            ("CALLS", "secret:s", ("read",)),
        ),
        ('URL = os.environ["PEER_URL"]\nrequests.get(URL + "/health")\n', ("REQUESTS", "workload:peer", ())),
        ("httpx.post(f\"{os.environ['PEER_URL']}/x\", json={})\n", ("REQUESTS", "workload:peer", ())),
        ('httpx.get("https://peer.internal.example/status")\n', ("REQUESTS", "workload:peer", ())),
    ],
)
def test_a_value_resolves_through_literals_env_constants_and_heads(
    source: str, want: tuple[str, str, tuple[str, ...]]
) -> None:
    read = one(source)
    assert summary(read) == {want}
    assert read.unknowns == [] and read.calls_skipped == 0
    (edge,) = [e for e in read.edges if e.type != "HAS_ENV"]
    (site,) = sites(edge)
    assert site[0] == "services/w/a.py" and "(" in one_line(source, site[1])


def one_line(source: str, line: int) -> str:
    return ("import os\n\nimport boto3\nimport httpx\nimport requests\n\n" + source).splitlines()[line - 1]


@pytest.mark.parametrize(
    "source,call",
    [
        ('T = "t"\nT = "u"\nc = boto3.client("dynamodb")\nc.get_item(TableName=T)\n', "c.get_item"),
        (
            'from config import TABLE\nc = boto3.client("dynamodb")\nc.get_item(TableName=TABLE)\n',
            "c.get_item",
        ),
        ('c = boto3.client("s3")\nc.put_object(Bucket="b", Key=f"{day}/x")\n', "c.put_object"),
        ('c = boto3.client("dynamodb")\nc.get_item(TableName=os.environ["NOT_SET"])\n', "c.get_item"),
        ('c = boto3.client("dynamodb")\nc.get_item(TableName="missing")\n', "c.get_item"),
        ('requests.get(base + "/x")\n', "requests.get"),
        ('import psycopg\npsycopg.connect(host="h")\n', "psycopg.connect"),
    ],
)
def test_an_unresolved_target_is_an_unknown_and_no_edge(source: str, call: str) -> None:
    read = one(source)
    assert summary(read) == set()
    (unknown,) = read.unknowns
    assert unknown.startswith("code: services/w/a.py:") and unknown.endswith(f" {call} target unresolved")
    line = int(unknown.split(":")[2].split()[0])
    assert call.split(".")[1] + "(" in one_line(source, line)


@pytest.mark.parametrize(
    "key,location",
    [
        ('"raw/pii/2024.csv"', "s3://lake/raw/pii/"),
        ('f"raw/orders/{day}.jsonl"', "s3://lake/raw/"),
        ('"raw/"', "s3://lake/raw/"),
        ('f"curated/{day}.csv"', "s3://lake/"),
        ("key", "s3://lake/"),
    ],
)
def test_a_key_lands_in_the_longest_location_prefix_it_starts_with(key: str, location: str) -> None:
    read = one(f'c = boto3.client("s3")\nc.put_object(Bucket="lake", Key={key}, Body=b"")\n')
    assert summary(read) == {("CALLS", location, ("write",))}


def test_connect_follows_the_secret_the_workload_calls_in_another_module() -> None:
    read = small(
        {
            "services/w/secrets.py": (
                'import boto3\n_sm = boto3.client("secretsmanager")\n_sm.get_secret_value(SecretId="s")\n'
            ),
            "services/w/db.py": "import sqlalchemy\nengine = sqlalchemy.create_engine(url)\n",
        }
    )
    assert summary(read) == {("CALLS", "secret:s", ("read",)), ("CALLS", "db:d", ("read",))}
    (db,) = [e for e in read.edges if e.dst == "db:d"]
    assert sites(db) == [("services/w/db.py", 2)] and db.props == {"actions": ["db:connect"]}


def test_other_hosts_methods_and_services_are_counted_as_skipped() -> None:
    read = one(
        'httpx.post("https://api.payments.example/v1/charges", json={})\n'
        'c = boto3.client("dynamodb")\nc.list_tables()\n'
        'q = boto3.client("sqs")\nq.send_message(QueueUrl="u", MessageBody="m")\n'
    )
    assert summary(read) == set() and read.unknowns == [] and read.calls_skipped == 3


def test_unclaimed_folders_and_unparsable_files_are_unknowns() -> None:
    read = small(
        {
            "services/orphan/a.py": 'import boto3\nboto3.client("s3").put_object(Bucket="b", Key="in/x")\n',
            "services/w/bad.py": "def broken(:\n",
            "services/w/ok.py": 'import boto3\nc = boto3.client("dynamodb")\nc.get_item(TableName="t")\n',
        }
    )
    assert read.unknowns == [
        "code: services/orphan is claimed by no workload",
        "code: services/w/bad.py does not parse",
    ]
    assert summary(read) == {("CALLS", "dynamodb:t", ("read",))}


def test_code_is_read_never_run() -> None:
    read = one(
        'raise SystemExit("never imported")\nc = boto3.client("dynamodb")\nc.get_item(TableName="t")\n'
    )
    assert summary(read) == {("CALLS", "dynamodb:t", ("read",))}


def test_output_is_sorted_and_independent_of_file_order(
    main_files: dict[str, str], main_read: CodeRead
) -> None:
    items = list(main_files.items())
    random.Random(7).shuffle(items)
    assert read_code(dict(items), demo_rows(), []) == main_read
    assert [(e.type, e.src, e.dst) for e in main_read.edges] == sorted(
        (e.type, e.src, e.dst) for e in main_read.edges
    )
    assert all(sites(e) == sorted(sites(e)) for e in main_read.edges)
