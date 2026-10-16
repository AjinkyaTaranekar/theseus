"""The demo inputs must preserve spec 02 before any engine can use them."""

from __future__ import annotations

import json
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

import hcl2
import pytest
import yaml

from theseus.errors import IngestError

ROOT = Path(__file__).resolve().parents[2]
WORLD = ROOT / "demo-infra"
FIXTURES = ROOT / "fixtures"
SPEC = (ROOT / "docs/spec/02-demo-world.md").read_text(encoding="utf-8")
IAM = "arn:aws:iam::111122223333:"
DDB = "arn:aws:dynamodb:eu-west-1:111122223333:table/demo-orders"
DB_SECRET = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:prod-db-credentials-*"
# F4's modeled files, whose lines every expected.json cites. C1 adds two more modeled files and two skipped.
F4_MODELED = ("people", "roles", "policies", "ci", "data", "services", "containers")
C1_MODELED = ("queues", "logs")
SKIPPED = ("network", "platform")
SCENARIOS = ["intern", "public-bucket", "compromised-action", "unused-grant", "code-pr"]

# Independent input expectations transcribed from spec 02, not from the generator or an IAM evaluator.
POLICY_CASES = [
    (
        "aws_iam_group_policy.support_assume",
        "AssumeProdSupport",
        ["sts:AssumeRole"],
        [IAM + "role/prod-support"],
    ),
    (
        "aws_iam_group_policy.analysts_assume",
        "AssumeAnalyticsRead",
        ["sts:AssumeRole"],
        [IAM + "role/analytics-read"],
    ),
    (
        "aws_iam_role_policy.prod_support_read",
        "ReadLogs",
        ["s3:GetObject", "s3:ListBucket"],
        ["arn:aws:s3:::demo-app-logs", "arn:aws:s3:::demo-app-logs/*"],
    ),
    (
        "aws_iam_role_policy.prod_support_read",
        "ReadInvoices",
        ["s3:GetObject"],
        ["arn:aws:s3:::demo-company-files/invoices/*"],
    ),
    ("aws_iam_role_policy.prod_support_read", "ReadDbSecret", ["secretsmanager:GetSecretValue"], [DB_SECRET]),
    (
        "aws_iam_policy.app_logs_read",
        "ReadAppLogs",
        ["s3:GetObject", "s3:ListBucket"],
        ["arn:aws:s3:::demo-app-logs", "arn:aws:s3:::demo-app-logs/*"],
    ),
    (
        "aws_iam_policy.data_lake_curated_read",
        "ReadCurated",
        ["s3:GetObject"],
        ["arn:aws:s3:::demo-data-lake/curated/*"],
    ),
    (
        "aws_iam_policy.orders_table_rw",
        "OrdersTableReadWrite",
        ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"],
        [DDB, DDB + "/index/*"],
    ),
    (
        "aws_iam_role_policy.github_deploy",
        "PublishSite",
        ["s3:PutObject"],
        ["arn:aws:s3:::demo-company-files/public/*"],
    ),
    (
        "aws_iam_role_policy.github_deploy",
        "AssumeProdSupportForMigrations",
        ["sts:AssumeRole"],
        [IAM + "role/prod-support"],
    ),
    (
        "aws_iam_role_policy.terraform_apply",
        "TerraformState",
        ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
        ["arn:aws:s3:::demo-terraform-state", "arn:aws:s3:::demo-terraform-state/*"],
    ),
    (
        "aws_iam_role_policy.terraform_apply",
        "ApplyInfra",
        [
            "iam:*",
            "lambda:*",
            "ecs:*",
            "ec2:*",
            "rds:*",
            "sqs:*",
            "sns:*",
            "kms:*",
            "logs:*",
            "events:*",
            "ecr:*",
            "route53:*",
            "apigateway:*",
            "dynamodb:CreateTable",
            "dynamodb:Describe*",
            "dynamodb:UpdateTable",
            "dynamodb:TagResource",
            "s3:CreateBucket",
            "s3:GetBucket*",
            "s3:PutBucket*",
            "secretsmanager:CreateSecret",
            "secretsmanager:DescribeSecret",
            "secretsmanager:TagResource",
        ],
        ["*"],
    ),
    (
        "aws_iam_role_policy.billing_job",
        "WriteInvoices",
        ["s3:PutObject"],
        ["arn:aws:s3:::demo-company-files/invoices/*"],
    ),
    (
        "aws_iam_role_policy.billing_job",
        "ReadPaymentsKey",
        ["secretsmanager:GetSecretValue"],
        ["arn:aws:secretsmanager:eu-west-1:111122223333:secret:payments-api-key-*"],
    ),
    ("aws_iam_role_policy.billing_job", "ReadOrders", ["dynamodb:Query"], [DDB, DDB + "/index/*"]),
    ("aws_iam_role_policy.billing_api", "ReadDbSecret", ["secretsmanager:GetSecretValue"], [DB_SECRET]),
    ("aws_iam_role_policy.support_portal", "LegacyDbSecret", ["secretsmanager:GetSecretValue"], [DB_SECRET]),
    ("aws_iam_role_policy.analytics_export", "ReadOrders", ["dynamodb:Scan"], [DDB]),
    (
        "aws_iam_role_policy.analytics_export",
        "RawZone",
        ["s3:PutObject", "s3:GetObject"],
        ["arn:aws:s3:::demo-data-lake/raw/*"],
    ),
    (
        "aws_iam_role_policy.analytics_export",
        "CuratedZone",
        ["s3:PutObject"],
        ["arn:aws:s3:::demo-data-lake/curated/*"],
    ),
]


def shell_path(path: Path | str, bash: str, *, native: bool = False) -> str:
    """Return a path in the namespace used by Git Bash or native Python."""
    if sys.platform != "win32":
        return path.as_posix() if isinstance(path, Path) else path
    result = subprocess.run(
        [
            bash,
            "-c",
            'PATH="/usr/bin:$PATH"; cygpath "$1" -- "$2"',
            "theseus-test",
            "-w" if native else "-u",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return result.stdout.rstrip("\r\n")


def run_plan_script(
    *arguments: Path, bin_dir: Path | None = None, env: dict[str, str | Path] | None = None
) -> subprocess.CompletedProcess[str]:
    """Return the plan script result using the same native Bash as the generator."""
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    bash = module["resolve_bash"]()
    paths = [shell_path(path, bash) for path in (ROOT / "tools/plan.sh", *arguments)]
    environment = {
        **os.environ,
        **{
            key: shell_path(value, bash) if isinstance(value, Path) else value
            for key, value in (env or {}).items()
        },
    }
    command = [bash, "--", *paths]
    if bin_dir is not None:
        # Set the POSIX PATH inside Bash; Windows process environments use a different separator.
        command = [
            bash,
            "-c",
            'export PATH="$1:/usr/bin:/bin"; shift; exec "$BASH" -- "$@"',
            "theseus-plan-test",
            shell_path(bin_dir, bash),
            *paths,
        ]
    return subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)


@pytest.fixture
def resources() -> dict[str, dict[str, Any]]:
    plan = json.loads((FIXTURES / "intern/base.plan.json").read_text(encoding="utf-8"))
    return {r["address"]: r["values"] for r in plan["planned_values"]["root_module"]["resources"]}


def test_every_spec_resource_has_its_exact_address_and_name(resources: dict[str, Any]) -> None:
    modeled = SPEC.split("## Terraform that Theseus models\n")[1].split("## Terraform that Theseus skips")[0]
    expected: set[str] = set()
    for address, name in re.findall(r"^\| `(aws_\w+\.\w+)` \| ([^|]*)\|", modeled, re.M):
        expected.add(address)
        assert address in resources
        if "`" in name:
            value = name.split("`")[1]
            field = {
                "aws_s3_bucket": "bucket",
                "aws_db_instance": "identifier",
                "aws_lambda_function": "function_name",
                "aws_ecs_task_definition": "family",
            }.get(address.split(".")[0], "name")
            assert resources[address][field] == value, address
    expected.update(
        f"aws_iam_role_policy_attachment.{name}_logs"
        for name in ("billing_job", "billing_api", "support_portal", "analytics_export")
    )
    assert declared(F4_MODELED + C1_MODELED) == expected
    assert declared(F4_MODELED + C1_MODELED + SKIPPED) == set(resources)


def declared(stems: tuple[str, ...]) -> set[str]:
    """Every resource address the named .tf files declare."""
    out: set[str] = set()
    for stem in stems:
        text = (WORLD / "terraform" / f"{stem}.tf").read_text(encoding="utf-8")
        out.update(f"{t}.{n}" for t, n in re.findall(r'^resource "(\w+)" "(\w+)"', text, re.M))
    return out


def test_modeled_and_skipped_types_live_in_separate_files() -> None:
    """Adding to a skipped file never moves a line an expected.json cites."""
    from theseus.adapters.aws.kinds import MODELED_TYPES

    for stem in SKIPPED:
        assert not {a.split(".")[0] for a in declared((stem,))} & MODELED_TYPES, stem
    for stem in C1_MODELED:
        assert {a.split(".")[0] for a in declared((stem,))} <= MODELED_TYPES, stem


def aws_service(resource_type: str) -> str:
    """The AWS service a resource type belongs to: VPC types are EC2's, CloudWatch is Logs or EventBridge."""
    word = resource_type.split("_")[1]
    if word in {"vpc", "subnet", "internet", "route", "security", "default"}:
        return "ec2"
    if word == "cloudwatch":
        return "logs" if resource_type.startswith("aws_cloudwatch_log_") else "events"
    return word


def test_the_world_looks_like_a_real_account(resources: dict[str, Any]) -> None:
    """About 120 resources across 16 AWS services, as spec 02 says, not a toy."""
    services = {aws_service(address.split(".")[0]) for address in resources}
    assert len(resources) >= 115
    assert len(services) >= 16, sorted(services)


def test_every_skipped_resource_spec_02_lists_exists(resources: dict[str, Any]) -> None:
    for prefix, count in {
        "aws_subnet.": 4,
        "aws_security_group.": 2,
        "aws_route_table_association.": 2,
        "aws_ecr_repository.": 2,
        "aws_cloudwatch_event_rule.": 2,
        "aws_cloudwatch_event_target.": 2,
        "aws_lambda_permission.": 2,
        "aws_s3_bucket_versioning.": 4,
        "aws_s3_bucket_server_side_encryption_configuration.": 4,
        "aws_s3_bucket_public_access_block.": 4,
        "aws_route53_record.": 2,
        "aws_cloudwatch_log_group.": 6,
        "aws_sqs_queue.": 2,
    }.items():
        assert sum(a.startswith(prefix) for a in resources) == count, prefix
    for address in (
        "aws_vpc.main",
        "aws_internet_gateway.main",
        "aws_route_table.public",
        "aws_vpc_security_group_ingress_rule.db_from_app",
        "aws_db_subnet_group.main",
        "aws_vpc_endpoint.s3",
        "aws_kms_key.queues",
        "aws_kms_alias.queues",
        "aws_sns_topic.invoice_created",
        "aws_route53_zone.internal",
        "aws_apigatewayv2_api.billing_internal",
    ):
        assert address in resources, address
    assert resources["aws_db_subnet_group.main"]["name"] == "demo-db-subnets"
    for bucket in ("app_logs", "company_files", "data_lake", "terraform_state"):
        block = resources[f"aws_s3_bucket_public_access_block.{bucket}"]
        assert all(
            block[k]
            for k in (
                "block_public_acls",
                "block_public_policy",
                "ignore_public_acls",
                "restrict_public_buckets",
            )
        )
        rule = resources[f"aws_s3_bucket_server_side_encryption_configuration.{bucket}"]["rule"][0]
        assert rule["apply_server_side_encryption_by_default"][0]["sse_algorithm"] == "AES256"


def has_unknown(value: Any) -> bool:
    if isinstance(value, dict):
        return any(has_unknown(v) for v in value.values())
    if isinstance(value, list):
        return any(has_unknown(v) for v in value)
    return value is True


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_all_modeled_fields_are_known(scenario: str) -> None:
    """Skipped types may reference computed attributes; the importer never reads them."""
    from theseus.adapters.aws.kinds import MODELED_TYPES

    fields = {
        "name",
        "function_name",
        "identifier",
        "family",
        "bucket",
        "user",
        "group",
        "groups",
        "role",
        "policy",
        "policy_arn",
        "assume_role_policy",
        "tags",
        "environment",
        "task_role_arn",
        "execution_role_arn",
        "container_definitions",
        "task_definition",
        "url",
        "client_id_list",
    }
    # P1: computed attributes the importer never reads. A bucket's or secret's `policy` is not a modeled
    # policy document (bucket policies are their own resource), and a queue is found by its name, not its URL.
    computed = {
        "aws_s3_bucket": {"policy"},
        "aws_secretsmanager_secret": {"policy"},
        "aws_sns_topic": {"policy"},
        "aws_sqs_queue": {"policy", "url"},
    }
    plans = sorted((FIXTURES / scenario).glob("*.plan.json"))
    assert plans
    for path in plans:
        plan = json.loads(path.read_text(encoding="utf-8"))
        assert plan["resource_changes"]
        for resource in plan["resource_changes"]:
            if resource["type"] not in MODELED_TYPES:
                continue
            for field in sorted(fields):
                if field in computed.get(resource["type"], set()):
                    continue
                assert not has_unknown(resource["change"]["after_unknown"].get(field)), (
                    path,
                    resource["address"],
                    field,
                )


def test_config_matches_spec_and_all_requirement_ids_exist(resources: dict[str, Any]) -> None:
    text = SPEC.split("## `theseus.yaml` (world root)")[1].split("```yaml\n")[1].split("```")[0]
    config = yaml.safe_load((WORLD / "theseus.yaml").read_text(encoding="utf-8"))
    assert config == yaml.safe_load(text)
    ids = {location["id"] for location in config["data_locations"]}
    for address, values in resources.items():
        kind = {
            "aws_iam_user": ("user", "name"),
            "aws_db_instance": ("db", "identifier"),
            "aws_secretsmanager_secret": ("secret", "name"),
            "aws_dynamodb_table": ("dynamodb", "name"),
            "aws_lambda_function": ("workload", "function_name"),
            "aws_ecs_service": ("workload", "name"),
        }.get(address.split(".")[0])
        if kind:
            ids.add(f"{kind[0]}:{values[kind[1]]}")
    ids.update(
        f"workflow:{p.relative_to(WORLD / 'workflows').as_posix()}"
        for p in (WORLD / "workflows").rglob("*.yml")
    )
    assert len(config["requirements"]) == 17
    for requirement in config["requirements"]:
        assert requirement["principal"] in ids
        assert requirement["resource"] in ids


def test_source_is_literal_and_contains_no_backend_or_data_sources() -> None:
    for path in sorted((WORLD / "terraform").glob("*.tf")):
        text = path.read_text(encoding="utf-8")
        if path.stem in F4_MODELED + C1_MODELED:
            assert not re.search(r"\baws_\w+\.\w+\.", text), path
        parsed = hcl2.loads(text)
        assert "data" not in parsed
        for block in parsed.get("terraform", []):
            assert "backend" not in block
    for folder in (
        "orders_api",
        "orders_worker",
        "billing_job",
        "billing_api",
        "support_portal",
        "analytics_export",
    ):
        assert (WORLD / "services" / folder / "__init__.py").read_bytes() == b""


def test_workflow_token_boundaries_and_deploy_jobs() -> None:
    workflow_root = WORLD / "workflows/demo-org"
    workflows = {
        p.relative_to(workflow_root).as_posix(): yaml.safe_load(p.read_text(encoding="utf-8"))
        for p in workflow_root.rglob("*.yml")
    }
    assert set(workflows) == {"infra/deploy.yml", "infra/ci.yml", "docs-site/preview.yml", "website/lint.yml"}
    for path, workflow in workflows.items():
        token = workflow.get("permissions", {}).get("id-token")
        assert (token == "write") == (path in {"infra/deploy.yml", "docs-site/preview.yml"})
        triggers = workflow.get("on", workflow.get(True))
        assert triggers == (
            {"push": {"branches": ["main"]}} if path == "infra/deploy.yml" else {"pull_request": None}
        )
    jobs = workflows["infra/deploy.yml"]["jobs"]
    assert jobs["apply"]["environment"] == "production"
    assert "environment" not in jobs["release"]
    assert jobs["release"]["needs"] == "apply"
    for path in ("docs-site/preview.yml", "website/lint.yml"):
        assert "demo-thirdparty/file-diff@v3" in (workflow_root / path).read_text(encoding="utf-8")


def test_policies_preserve_the_critical_grants(resources: dict[str, Any]) -> None:
    def statements(address: str, field: str = "policy") -> dict[str, Any]:
        return {s["Sid"]: s for s in json.loads(resources[address][field])["Statement"]}

    support = statements("aws_iam_role_policy.prod_support_read")
    assert set(support) == {"ReadLogs", "ReadInvoices", "ReadDbSecret"}
    assert support["ReadInvoices"]["Resource"] == "arn:aws:s3:::demo-company-files/invoices/*"
    assert support["ReadDbSecret"]["Resource"] == (
        "arn:aws:secretsmanager:eu-west-1:111122223333:secret:prod-db-credentials-*"
    )
    assert statements("aws_iam_role_policy.support_portal")["LegacyDbSecret"] == {
        "Sid": "LegacyDbSecret",
        "Effect": "Allow",
        "Action": "secretsmanager:GetSecretValue",
        "Resource": support["ReadDbSecret"]["Resource"],
    }
    deploy = statements("aws_iam_role.github_deploy", "assume_role_policy")["GitHubActionsOIDC"]
    apply = statements("aws_iam_role.terraform_apply", "assume_role_policy")["GitHubActionsOIDC"]
    issuer = "token.actions.githubusercontent.com"
    assert deploy["Condition"] == {
        "StringEquals": {f"{issuer}:aud": "sts.amazonaws.com"},
        "StringLike": {f"{issuer}:sub": "repo:demo-org/*"},
    }
    assert apply["Condition"] == {
        "StringEquals": {
            f"{issuer}:aud": "sts.amazonaws.com",
            f"{issuer}:sub": "repo:demo-org/infra:environment:production",
        }
    }
    assert statements("aws_iam_role_policy.github_deploy")["AssumeProdSupportForMigrations"]["Resource"] == (
        "arn:aws:iam::111122223333:role/prod-support"
    )
    assert resources["aws_secretsmanager_secret.prod_db"]["tags"]["db_instance"] == "customer-db"
    assert "db_instance" not in (resources["aws_secretsmanager_secret.payments"]["tags"] or {})


def test_workloads_use_their_own_roles_and_environment(resources: dict[str, Any]) -> None:
    environments = {
        "billing_job": {
            "INVOICES_BUCKET": "demo-company-files",
            "ORDERS_TABLE": "demo-orders",
            "PAYMENTS_SECRET": "payments-api-key",
            "INVOICE_TOPIC_ARN": "arn:aws:sns:eu-west-1:111122223333:invoice-created",
        },
        "billing_api": {"DB_SECRET": "prod-db-credentials", "DB_NAME": "customers"},
        "support_portal": {
            "BILLING_API_URL": "https://billing-api.internal.demo.test",
            "ORDERS_API_URL": "https://orders-api.internal.demo.test",
        },
        "analytics_export": {"ORDERS_TABLE": "demo-orders", "LAKE_BUCKET": "demo-data-lake"},
    }
    for name in ("billing_job", "billing_api", "support_portal", "analytics_export"):
        function = resources[f"aws_lambda_function.{name}"]
        role = name.replace("_", "-")
        assert function["role"] == f"arn:aws:iam::111122223333:role/{role}"
        assert function["runtime"] == "python3.12"
        assert function["handler"] == "handler.handler"
        assert function["s3_bucket"] == "demo-artifacts"
        assert function["tags"]["theseus_code_path"] == f"services/{name}"
        assert function["environment"] == [{"variables": environments[name]}]
        attachment = resources[f"aws_iam_role_policy_attachment.{name}_logs"]
        assert attachment["role"] == role
        assert attachment["policy_arn"] == "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
    for name in ("orders_api", "orders_worker"):
        task = resources[f"aws_ecs_task_definition.{name}"]
        assert task["task_role_arn"] == f"arn:aws:iam::111122223333:role/{name.replace('_', '-')}-task"
        assert task["execution_role_arn"] == "arn:aws:iam::111122223333:role/ecs-task-execution"
        assert task["cpu"] == "256" and task["memory"] == "512"
        env = {v["name"]: v["value"] for v in json.loads(task["container_definitions"])[0]["environment"]}
        expected_env = {
            "ORDERS_TABLE": "demo-orders",
            "ORDER_EVENTS_QUEUE_URL": "https://sqs.eu-west-1.amazonaws.com/111122223333/order-events",
        }
        if name == "orders_api":
            expected_env["BILLING_API_URL"] = "https://billing-api.internal.demo.test"
        assert env == expected_env
        service = resources[f"aws_ecs_service.{name}"]
        assert service["task_definition"] == name.replace("_", "-")
        assert service["tags"]["theseus_code_path"] == f"services/{name}"


def test_all_policy_sids_and_managed_attachments_match_spec(resources: dict[str, Any]) -> None:
    expected_sids = {
        "aws_iam_group_policy.support_assume": {"AssumeProdSupport"},
        "aws_iam_group_policy.analysts_assume": {"AssumeAnalyticsRead"},
        "aws_iam_role_policy.prod_support_read": {"ReadLogs", "ReadInvoices", "ReadDbSecret"},
        "aws_iam_policy.app_logs_read": {"ReadAppLogs"},
        "aws_iam_policy.data_lake_curated_read": {"ReadCurated"},
        "aws_iam_policy.orders_table_rw": {"OrdersTableReadWrite"},
        "aws_iam_role_policy.github_deploy": {"PublishSite", "AssumeProdSupportForMigrations"},
        "aws_iam_role_policy.terraform_apply": {"TerraformState", "ApplyInfra"},
        "aws_iam_role_policy.billing_job": {"WriteInvoices", "ReadPaymentsKey", "ReadOrders"},
        "aws_iam_role_policy.billing_api": {"ReadDbSecret"},
        "aws_iam_role_policy.support_portal": {"LegacyDbSecret"},
        "aws_iam_role_policy.analytics_export": {"ReadOrders", "RawZone", "CuratedZone"},
    }
    actual = {
        address: {s["Sid"] for s in json.loads(value["policy"])["Statement"]}
        for address, value in resources.items()
        if address.split(".")[0] in {"aws_iam_policy", "aws_iam_group_policy", "aws_iam_role_policy"}
    }
    assert actual == expected_sids
    for name in ("orders_api", "orders_worker"):
        attached = resources[f"aws_iam_role_policy_attachment.{name}_table"]
        assert attached["role"] == name.replace("_", "-") + "-task"
        assert attached["policy_arn"] == "arn:aws:iam::111122223333:policy/orders-table-rw"
    for name in ("prod_support", "analytics_read"):
        policy = json.loads(resources[f"aws_iam_role.{name}"]["assume_role_policy"])
        assert policy["Statement"] == [
            {
                "Sid": "TrustAccountPrincipals",
                "Effect": "Allow",
                "Principal": {"AWS": "arn:aws:iam::111122223333:root"},
                "Action": "sts:AssumeRole",
            }
        ]


def test_fixture_metadata_and_pr_text_match_the_approved_formats() -> None:
    modes = {
        "intern": "pr",
        "public-bucket": "pr",
        "compromised-action": "finding",
        "unused-grant": "scan",
        "code-pr": "pr",
    }
    for name, mode in modes.items():
        metadata = yaml.safe_load((FIXTURES / name / "scenario.yaml").read_text(encoding="utf-8"))
        assert set(metadata) == {"name", "mode", "world", "description"}
        assert metadata["name"] == name and metadata["mode"] == mode
        assert metadata["world"] == "demo-infra"
        assert metadata["description"]
    advisory = json.loads((FIXTURES / "compromised-action/advisory.json").read_text(encoding="utf-8"))
    assert set(advisory) == {"id", "action", "affected_versions", "text"}
    assert advisory["id"] == "GHSA-demo-0001"
    assert advisory["action"] == "demo-thirdparty/file-diff"
    assert advisory["affected_versions"] == ["v1", "v2", "v3"]
    for name in ("intern", "public-bucket", "code-pr"):
        section = SPEC.split(f"### `{name}`")[1].split("\n### ")[0]
        title = re.search(r'\*\*PR title:\*\* "(.+)"', section)
        body = re.search(r'\*\*PR body:\*\* "(.+)"', section)
        assert title and body
        assert (FIXTURES / name / "pr.md").read_text(encoding="utf-8") == (f"# {title[1]}\n\n{body[1]}\n")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_fixture_layout_and_changes_are_exact(scenario: str) -> None:
    root = FIXTURES / scenario
    base = json.loads((root / "base.plan.json").read_text(encoding="utf-8"))
    base_resources = {r["address"]: r["values"] for r in base["planned_values"]["root_module"]["resources"]}
    for source in sorted(WORLD.rglob("*")):
        if source.is_file() and source.suffix in {".tf", ".py", ".yaml", ".yml"}:
            assert (root / "base" / source.relative_to(WORLD)).read_bytes() == source.read_bytes()
    assert not list((root / "base").rglob(".terraform"))
    assert not list((root / "base").rglob("*.tfstate*"))
    if scenario in {"compromised-action", "unused-grant"}:
        assert not (root / "head").exists()
        assert not (root / "head.plan.json").exists()
        assert not (root / "pr.md").exists()
        assert (root / "advisory.json").exists() == (scenario == "compromised-action")
        return
    head = json.loads((root / "head.plan.json").read_text(encoding="utf-8"))
    head_resources = {r["address"]: r["values"] for r in head["planned_values"]["root_module"]["resources"]}
    if scenario == "code-pr":
        assert set(head_resources) == set(base_resources)
        portal = "aws_lambda_function.support_portal"
        env = head_resources[portal]["environment"][0]["variables"]
        assert env == {
            **base_resources[portal]["environment"][0]["variables"],
            "DB_SECRET": "prod-db-credentials",
        }
        assert {a: v for a, v in head_resources.items() if a != portal} == {
            a: v for a, v in base_resources.items() if a != portal
        }
        changed = sorted(
            p.relative_to(root / "head").as_posix()
            for p in (root / "head").rglob("*")
            if p.is_file()
            and (
                not (root / "base" / p.relative_to(root / "head")).exists()
                or (root / "base" / p.relative_to(root / "head")).read_bytes() != p.read_bytes()
            )
        )
        assert changed == [
            "services/support_portal/export.py",
            "services/support_portal/handler.py",
            "services/support_portal/views.py",
            "terraform/services.tf",
        ]
        head_text = (root / "head/services/support_portal").joinpath
        assert "received" in head_text("views.py").read_text(encoding="utf-8")
        assert "SecretId=DB_SECRET" in head_text("export.py").read_text(encoding="utf-8")
        assert "psycopg.connect(" in head_text("export.py").read_text(encoding="utf-8")
        assert "/admin/export" in head_text("handler.py").read_text(encoding="utf-8")
        return
    added = (
        "aws_iam_user_group_membership.priya_support"
        if scenario == "intern"
        else ("aws_s3_bucket_policy.company_files_public")
    )
    flipped = "aws_s3_bucket_public_access_block.company_files"
    assert set(head_resources) - set(base_resources) == {added}
    assert {a: v for a, v in head_resources.items() if a not in {added, flipped}} == {
        a: v for a, v in base_resources.items() if a != flipped
    }
    if scenario == "public-bucket":
        # A public policy is rejected while Block Public Access is on, so the PR turns those two settings off.
        assert head_resources[flipped] == {
            **base_resources[flipped],
            "block_public_policy": False,
            "restrict_public_buckets": False,
        }
    else:
        assert head_resources[flipped] == base_resources[flipped]
    if scenario == "intern":
        assert head_resources[added]["user"] == "priya-intern"
        assert head_resources[added]["groups"] == ["support-engineers"]
    else:
        assert json.loads(head_resources[added]["policy"])["Statement"] == [
            {
                "Sid": "PublicRead",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": "arn:aws:s3:::demo-company-files/*",
            }
        ]


def test_plan_script_rejects_bad_arguments_without_terraform() -> None:
    result = run_plan_script()
    assert result.returncode == 2
    assert "Usage:" in result.stderr


@pytest.mark.parametrize("fail_at", [1, 2])
def test_generator_does_not_publish_a_failed_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    target = tmp_path / "fixtures/intern"
    target.mkdir(parents=True)
    (target / "base.plan.json").write_text("previous verified plan", encoding="utf-8")

    calls = 0

    def fail(command: list[str], **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise subprocess.CalledProcessError(1, command)
        Path(command[-1]).write_bytes((FIXTURES / "intern/base.plan.json").read_bytes())

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(IngestError):
        module["generate"]("intern", WORLD, tmp_path / "fixtures")
    assert calls == fail_at
    assert (target / "base.plan.json").read_text(encoding="utf-8") == "previous verified plan"


def test_generator_is_repeatable_and_preserves_unowned_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    assert "expected.json" not in module["OWNED"]
    target = tmp_path / "fixtures/intern"
    target.mkdir(parents=True)
    (target / "human-review.md").write_text("Keep this review", encoding="utf-8")
    timestamp = iter(["first run", "first run", "second run", "second run"])

    def fake_plan(command: list[str], **kwargs: Any) -> None:
        plan = json.loads((FIXTURES / "intern/base.plan.json").read_text(encoding="utf-8"))
        plan["timestamp"] = next(timestamp)
        Path(command[-1]).write_text(json.dumps(plan), encoding="utf-8")

    monkeypatch.setattr(subprocess, "run", fake_plan)
    module["generate"]("intern", WORLD, tmp_path / "fixtures")
    first = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    module["generate"]("intern", WORLD, tmp_path / "fixtures")
    second = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert first == second
    assert (target / "human-review.md").read_text(encoding="utf-8") == "Keep this review"
    assert "timestamp" not in json.loads((target / "base.plan.json").read_text(encoding="utf-8"))


def test_generator_removes_stale_inputs_for_non_pr_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    target = tmp_path / "fixtures/unused-grant"
    (target / "head").mkdir(parents=True)
    (target / "head.plan.json").write_text("stale", encoding="utf-8")
    (target / "pr.md").write_text("stale", encoding="utf-8")
    (target / "advisory.json").write_text("stale", encoding="utf-8")

    def fake_plan(command: list[str], **kwargs: Any) -> None:
        Path(command[-1]).write_bytes((FIXTURES / "intern/base.plan.json").read_bytes())

    monkeypatch.setattr(subprocess, "run", fake_plan)
    module["generate"]("unused-grant", WORLD, tmp_path / "fixtures")
    assert sorted(p.name for p in target.iterdir()) == ["base", "base.plan.json", "scenario.yaml"]


def test_generator_builds_code_pr_from_the_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))

    def fake_plan(command: list[str], **kwargs: Any) -> None:
        Path(command[-1]).write_bytes((FIXTURES / "intern/base.plan.json").read_bytes())

    monkeypatch.setattr(subprocess, "run", fake_plan)
    module["generate"]("code-pr", WORLD, tmp_path / "fixtures")
    head = tmp_path / "fixtures/code-pr/head"
    assert (head / "services/support_portal/export.py").exists()
    assert "recieved" not in (head / "services/support_portal/views.py").read_text(encoding="utf-8")
    assert 'DB_SECRET       = "prod-db-credentials"' in (head / "terraform/services.tf").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("times", [0, 2])
def test_an_edit_that_does_not_match_exactly_once_is_refused(tmp_path: Path, times: int) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    (tmp_path / "a.txt").write_text("x\n" * times, encoding="utf-8")
    scenario = module["Scenario"](
        mode="pr", description="d", edits=[module["Edit"](file="a.txt", find="x\n", replace="y\n")]
    )
    with pytest.raises(IngestError, match=f"appears {times} times"):
        module["apply_changes"](scenario, tmp_path)


def test_plan_script_isolates_state_and_preserves_output_on_failure(tmp_path: Path) -> None:
    source = tmp_path / "source with spaces"
    source.mkdir()
    (source / "main.tf").write_text("terraform {}", encoding="utf-8")
    (source / "terraform.tfstate").write_text("old state", encoding="utf-8")
    output = tmp_path / "plan with spaces.json"
    output.write_text("previous plan", encoding="utf-8")
    executable = tmp_path / "terraform"
    executable.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'dir="${1#-chdir=}"\n'
        '[[ "$dir" != "$SOURCE" && -f "$dir/main.tf" && ! -e "$dir/terraform.tfstate" ]] || exit 90\n'
        '[[ "$AWS_EC2_METADATA_DISABLED" == true ]] || exit 90\n'
        '[[ -z "${AWS_PROFILE+x}" && -z "${AWS_DEFAULT_PROFILE+x}"'
        ' && -z "${AWS_SESSION_TOKEN+x}" ]] || exit 90\n'
        '[[ -f "$AWS_CONFIG_FILE" && ! -s "$AWS_CONFIG_FILE" ]] || exit 90\n'
        '[[ -f "$AWS_SHARED_CREDENTIALS_FILE" && ! -s "$AWS_SHARED_CREDENTIALS_FILE" ]] || exit 90\n'
        'case "$2" in\n'
        '  init) [[ "$*" == *"-backend=false"* ]] || exit 90 ;;\n'
        '  plan) [[ "$*" == *"-refresh=false"* ]] || exit 90; exit 9 ;;\n'
        "  *) exit 8 ;;\n"
        "esac\n",
        encoding="utf-8",
        newline="\n",
    )
    executable.chmod(0o755)
    result = run_plan_script(
        source,
        output,
        bin_dir=tmp_path,
        env={
            "SOURCE": source,
            "AWS_PROFILE": "synthetic-profile",
            "AWS_DEFAULT_PROFILE": "synthetic-default",
            "AWS_SESSION_TOKEN": "mock",
            "AWS_CONFIG_FILE": source / "missing-config",
            "AWS_SHARED_CREDENTIALS_FILE": source / "missing-credentials",
        },
    )
    assert result.returncode == 9, result.stderr
    assert output.read_text(encoding="utf-8") == "previous plan"
    assert not list(tmp_path.glob(".theseus-plan.*"))


@pytest.mark.parametrize(
    "payload", ["null", "[]", "{}", "invalid json", "errored", "incomplete", "bad resources", "bad changes"]
)
def test_generator_rejects_malformed_plan_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    target = tmp_path / "fixtures/intern"
    target.mkdir(parents=True)
    (target / "base.plan.json").write_text("previous plan", encoding="utf-8")
    if payload in {"errored", "incomplete", "bad resources", "bad changes"}:
        data = json.loads((FIXTURES / "intern/base.plan.json").read_text(encoding="utf-8"))
        if payload == "errored":
            data["errored"] = True
        elif payload == "incomplete":
            data["complete"] = False
        elif payload == "bad resources":
            data["planned_values"]["root_module"]["resources"] = {}
        else:
            data["resource_changes"] = {}
        payload = json.dumps(data)

    def malformed(command: list[str], **kwargs: Any) -> None:
        Path(command[-1]).write_text(payload, encoding="utf-8")

    monkeypatch.setattr(subprocess, "run", malformed)
    with pytest.raises(IngestError):
        module["generate"]("intern", WORLD, tmp_path / "fixtures")
    assert (target / "base.plan.json").read_text(encoding="utf-8") == "previous plan"
    assert not list((tmp_path / "fixtures").glob(".intern-*"))


@pytest.mark.parametrize(
    "address,sid,actions,arns", POLICY_CASES, ids=[f"{c[0]}/{c[1]}" for c in POLICY_CASES]
)
def test_every_data_policy_statement_matches_spec(
    resources: dict[str, Any], address: str, sid: str, actions: list[str], arns: list[str]
) -> None:
    policy = json.loads(resources[address]["policy"])
    assert set(policy) == {"Version", "Statement"}
    assert policy["Version"] == "2012-10-17"
    statement = next(s for s in policy["Statement"] if s["Sid"] == sid)
    assert set(statement) == {"Sid", "Effect", "Action", "Resource"}
    assert statement["Effect"] == "Allow"
    actual_actions = statement["Action"]
    actual_resources = statement["Resource"]
    assert set(actual_actions if isinstance(actual_actions, list) else [actual_actions]) == set(actions)
    assert set(actual_resources if isinstance(actual_resources, list) else [actual_resources]) == set(arns)


@pytest.mark.parametrize(
    "name",
    [
        "billing_job",
        "billing_api",
        "support_portal",
        "analytics_export",
        "orders_api_task",
        "orders_worker_task",
        "ecs_task_execution",
    ],
)
def test_every_service_role_trusts_only_its_service(resources: dict[str, Any], name: str) -> None:
    policy = json.loads(resources[f"aws_iam_role.{name}"]["assume_role_policy"])
    service = (
        "ecs-tasks.amazonaws.com"
        if name in {"orders_api_task", "orders_worker_task", "ecs_task_execution"}
        else "lambda.amazonaws.com"
    )
    assert policy == {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "sts:AssumeRole",
                "Principal": {"Service": service},
            }
        ],
    }


@pytest.mark.parametrize(
    "name,user,group",
    [
        ("sam_support", "sam-support", "support-engineers"),
        ("alex_analysts", "alex-analyst", "data-analysts"),
        ("jordan_platform", "jordan-platform", "platform-engineers"),
    ],
)
def test_baseline_memberships_are_exact(resources: dict[str, Any], name: str, user: str, group: str) -> None:
    values = resources[f"aws_iam_user_group_membership.{name}"]
    assert values["user"] == user
    assert values["groups"] == [group]


def test_other_managed_attachments_and_data_settings_match_spec(resources: dict[str, Any]) -> None:
    platform = resources["aws_iam_group_policy_attachment.platform_logs"]
    assert (platform["group"], platform["policy_arn"]) == ("platform-engineers", IAM + "policy/app-logs-read")
    analysts = resources["aws_iam_role_policy_attachment.analytics_read_curated"]
    assert (analysts["role"], analysts["policy_arn"]) == (
        "analytics-read",
        IAM + "policy/data-lake-curated-read",
    )
    execution = resources["aws_iam_role_policy_attachment.ecs_task_execution"]
    assert execution["role"] == "ecs-task-execution"
    assert execution["policy_arn"] == "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
    database = resources["aws_db_instance.customer"]
    for key, value in {
        "engine": "postgres",
        "engine_version": "16",
        "instance_class": "db.t4g.micro",
        "manage_master_user_password": True,
        "db_subnet_group_name": "demo-db-subnets",
        "storage_encrypted": True,
    }.items():
        assert database[key] == value
    assert database.get("password") is None
    table = resources["aws_dynamodb_table.orders"]
    assert table["billing_mode"] == "PAY_PER_REQUEST" and table["hash_key"] == "order_id"
    assert table["point_in_time_recovery"] == [{"enabled": True}]
    (index,) = table["global_secondary_index"]
    assert (index["name"], index["hash_key"], index["range_key"]) == ("by_status", "status", "created_at")


@pytest.mark.parametrize("name,count", [("orders_api", 2), ("orders_worker", 1)])
def test_ecs_runtime_settings_match_spec(resources: dict[str, Any], name: str, count: int) -> None:
    service = resources[f"aws_ecs_service.{name}"]
    assert service["desired_count"] == count
    assert service["launch_type"] == "FARGATE"
    assert service["cluster"] == "arn:aws:ecs:eu-west-1:111122223333:cluster/demo-apps"
    assert service["network_configuration"][0]["subnets"] == [
        "subnet-0a1b2c3d4e5f60001",
        "subnet-0a1b2c3d4e5f60002",
    ]
    task = resources[f"aws_ecs_task_definition.{name}"]
    assert task["network_mode"] == "awsvpc" and task["requires_compatibilities"] == ["FARGATE"]
    (container,) = json.loads(task["container_definitions"])
    image_name = name.replace("_", "-")
    assert container["name"] == image_name
    assert container["image"] == f"111122223333.dkr.ecr.eu-west-1.amazonaws.com/{image_name}:2.3.1"


@pytest.mark.parametrize(
    "scenario,changed", [("intern", "terraform/people.tf"), ("public-bucket", "terraform/data.tf")]
)
def test_head_preserves_all_base_files_and_existing_source_lines(scenario: str, changed: str) -> None:
    base = FIXTURES / scenario / "base"
    head = FIXTURES / scenario / "head"
    base_files = {p.relative_to(base): p.read_bytes() for p in base.rglob("*") if p.is_file()}
    head_files = {p.relative_to(head): p.read_bytes() for p in head.rglob("*") if p.is_file()}
    assert set(base_files) == set(head_files)
    assert head_files[Path(changed)].startswith(base_files[Path(changed)])
    flipped = {Path("terraform/platform.tf")} if scenario == "public-bucket" else set()
    assert {p for p in base_files if base_files[p] != head_files[p]} == {Path(changed)} | flipped
    for path in flipped:
        # Two values change in place inside company-files' block, so no line an expected.json cites moves.
        base_lines = base_files[path].decode("utf-8").splitlines()
        head_lines = head_files[path].decode("utf-8").splitlines()
        start = base_lines.index('resource "aws_s3_bucket_public_access_block" "company_files" {')
        pairs = enumerate(zip(base_lines, head_lines, strict=True))
        assert [(i - start, h) for i, (b, h) in pairs if b != h] == [
            (3, "  block_public_policy     = false"),
            (5, "  restrict_public_buckets = false"),
        ]


def test_failed_rollback_keeps_recovery_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    target = tmp_path / "fixtures/intern"
    (target / "base").mkdir(parents=True)
    (target / "base/old.tf").write_text("previous source", encoding="utf-8")
    replace = os.replace

    def fail_publish_and_rollback(source: Path, destination: Path) -> None:
        if destination == target / "head" or (
            source == target / "base" and destination.parent.name != "previous"
        ):
            raise OSError("simulated persistent disk error")
        replace(source, destination)

    def fake_plan(command: list[str], **kwargs: Any) -> None:
        Path(command[-1]).write_bytes((FIXTURES / "intern/base.plan.json").read_bytes())

    monkeypatch.setattr(subprocess, "run", fake_plan)
    monkeypatch.setattr(os, "replace", fail_publish_and_rollback)
    with pytest.raises(IngestError, match="Recovery files are preserved") as error:
        module["generate"]("intern", WORLD, tmp_path / "fixtures")
    (recovery,) = list((tmp_path / "fixtures").glob(".intern-*"))
    assert (recovery / "previous/base/old.tf").read_text(encoding="utf-8") == "previous source"
    assert str(recovery) in str(error.value)


@pytest.mark.parametrize("failed_stage", ["plan", "validation", "publish"])
def test_cleanup_failure_preserves_the_generation_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failed_stage: str,
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    target = tmp_path / "fixtures/intern"
    target.mkdir(parents=True)
    previous = target / "base.plan.json"
    previous.write_text("previous verified plan", encoding="utf-8")

    def fake_plan(command: list[str], **kwargs: Any) -> None:
        if failed_stage == "plan":
            raise subprocess.CalledProcessError(19, command)
        payload = b"{}" if failed_stage == "validation" else (FIXTURES / "intern/base.plan.json").read_bytes()
        Path(command[-1]).write_bytes(payload)

    def fail_publish(source: Path, destination: Path) -> None:
        raise OSError("simulated publish failure")

    def fail_cleanup(path: Path) -> None:
        raise PermissionError("simulated cleanup failure")

    monkeypatch.setattr(subprocess, "run", fake_plan)
    monkeypatch.setattr(module["shutil"], "rmtree", fail_cleanup)
    if failed_stage == "publish":
        monkeypatch.setattr(os, "replace", fail_publish)
    expected = {
        "plan": "returned non-zero exit status 19",
        "validation": "Terraform did not return a complete plan",
        "publish": "simulated publish failure",
    }
    with pytest.raises(IngestError, match=expected[failed_stage]):
        module["generate"]("intern", WORLD, target.parent)
    assert previous.read_text(encoding="utf-8") == "previous verified plan"
    assert "simulated cleanup failure" in caplog.text
    assert "staging directory" in caplog.text
    assert len(list(target.parent.glob(".intern-*"))) == 1


def test_cleanup_failure_after_success_is_still_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))

    def fake_plan(command: list[str], **kwargs: Any) -> None:
        Path(command[-1]).write_bytes((FIXTURES / "intern/base.plan.json").read_bytes())

    def fail_cleanup(path: Path) -> None:
        raise PermissionError("simulated cleanup failure")

    monkeypatch.setattr(subprocess, "run", fake_plan)
    monkeypatch.setattr(module["shutil"], "rmtree", fail_cleanup)
    with pytest.raises(IngestError, match="Could not remove staging directory") as error:
        module["generate"]("intern", WORLD, tmp_path / "fixtures")
    assert isinstance(error.value.__cause__, PermissionError)
    assert (tmp_path / "fixtures/intern/base.plan.json").is_file()


@pytest.mark.parametrize(
    "args,status,expected",
    [
        ([], 2, "required"),
        (["unknown"], 2, "invalid choice"),
        (["--help"], 0, "usage:"),
    ],
)
def test_generator_cli_reports_invalid_requests(args: list[str], status: int, expected: str) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/make_fixture.py"), *args], capture_output=True, text=True
    )
    assert result.returncode == status
    assert expected in result.stdout + result.stderr


@pytest.mark.parametrize(
    "failed_file", ["base", "head", "base.plan.json", "head.plan.json", "scenario.yaml", "pr.md"]
)
def test_generator_rolls_back_a_failed_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_file: str
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    target = tmp_path / "fixtures/intern"
    for side in ("base", "head"):
        (target / side).mkdir(parents=True)
        (target / side / "old.tf").write_text("previous source", encoding="utf-8")
    for name in ("base.plan.json", "head.plan.json", "scenario.yaml", "pr.md", "human-review.md"):
        (target / name).write_text(f"Previous {name}", encoding="utf-8")
    before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}

    def fake_plan(command: list[str], **kwargs: Any) -> None:
        Path(command[-1]).write_bytes((FIXTURES / "intern/base.plan.json").read_bytes())

    replace = os.replace
    failed = False

    def fail_once(source: Path, destination: Path) -> None:
        nonlocal failed
        if destination == target / failed_file and not failed:
            failed = True
            raise OSError("simulated disk error during publish")
        replace(source, destination)

    monkeypatch.setattr(subprocess, "run", fake_plan)
    monkeypatch.setattr(os, "replace", fail_once)
    with pytest.raises(IngestError, match="simulated disk error"):
        module["generate"]("intern", WORLD, tmp_path / "fixtures")
    after = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert before == after
    assert not list((tmp_path / "fixtures").glob(".intern-*"))


@pytest.mark.parametrize("failed_stage", ["init", "plan", "show", "none"])
@pytest.mark.parametrize("existing_output", [False, True])
def test_plan_script_handles_every_terraform_exit_stage(
    tmp_path: Path, failed_stage: str, existing_output: bool
) -> None:
    source = tmp_path / "source with spaces"
    source.mkdir()
    (source / "main.tf.json").write_text('{"terraform": {}}', encoding="utf-8")
    output = tmp_path / "result with spaces.json"
    if existing_output:
        output.write_text("previous plan", encoding="utf-8")
    record = tmp_path / "work-path"
    executable = tmp_path / "terraform"
    executable.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'work="${1#-chdir=}"\n'
        '[[ -f "$work/main.tf.json" ]] || exit 90\n'
        'printf "%s" "$work" > "$WORK_RECORD"\n'
        'if [[ "$2" == "$FAIL_STAGE" ]]; then\n'
        '  echo "partial output"\n'
        "  exit 7\n"
        "fi\n"
        'if [[ "$2" == show ]]; then echo \'{"ok": true}\'; fi\n',
        encoding="utf-8",
        newline="\n",
    )
    executable.chmod(0o755)
    result = run_plan_script(
        source,
        output,
        bin_dir=tmp_path,
        env={"FAIL_STAGE": failed_stage, "WORK_RECORD": record},
    )
    assert result.returncode == (0 if failed_stage == "none" else 7), result.stderr
    if failed_stage == "none":
        assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
    elif existing_output:
        assert output.read_text(encoding="utf-8") == "previous plan"
    else:
        assert not output.exists()
    bash = runpy.run_path(str(ROOT / "tools/make_fixture.py"))["resolve_bash"]()
    recorded_work = Path(shell_path(record.read_text(encoding="utf-8"), bash, native=True))
    assert not recorded_work.exists()
    assert not list(tmp_path.glob(".theseus-plan.*"))
    assert sorted(p.name for p in source.iterdir()) == ["main.tf.json"]


def test_plan_script_cleans_up_when_output_tempfile_creation_fails(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.tf").write_text("terraform {}", encoding="utf-8")
    work = tmp_path / "work"
    executable = tmp_path / "mktemp"
    executable.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'if [[ "$1" == -d ]]; then\n'
        '  mkdir "$EXPECTED_WORK"\n'
        '  echo "$EXPECTED_WORK"\n'
        "else\n"
        "  exit 7\n"
        "fi\n",
        encoding="utf-8",
        newline="\n",
    )
    executable.chmod(0o755)
    result = run_plan_script(
        source,
        tmp_path / "result.json",
        bin_dir=tmp_path,
        env={"EXPECTED_WORK": work},
    )
    assert result.returncode == 7
    assert not work.exists()


@pytest.mark.parametrize("symlink", [False, True])
@pytest.mark.parametrize("populated", [False, True])
def test_plan_script_rejects_directory_output_before_running_terraform(
    tmp_path: Path, symlink: bool, populated: bool
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.tf").write_text("terraform {}", encoding="utf-8")
    directory = tmp_path / "existing directory"
    directory.mkdir()
    if populated:
        (directory / "human-review.md").write_text("preserve this review", encoding="utf-8")
    output = tmp_path / "output.json"
    if symlink:
        output.symlink_to(directory, target_is_directory=True)
    else:
        directory.rename(output)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    executable = tmp_path / "terraform"
    executable.write_text(
        "#!/usr/bin/env bash\n"
        'touch "$REVIEW_TERRAFORM_CALLED"\n'
        'if [[ "$2" == show ]]; then echo \'{"valid": true}\'; fi\n',
        encoding="utf-8",
        newline="\n",
    )
    executable.chmod(0o755)
    marker = tmp_path / "terraform-called"
    result = run_plan_script(
        source,
        output,
        bin_dir=tmp_path,
        env={"REVIEW_TERRAFORM_CALLED": marker},
    )
    assert result.returncode == 2, result.stderr
    assert "Output path is a directory" in result.stderr
    assert not marker.exists()
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before
    assert output.is_symlink() is symlink
    assert not list(tmp_path.glob(".theseus-plan.*"))


def test_generator_excludes_local_artifacts_and_never_opens_answer_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    source = tmp_path / "world"
    (source / "terraform").mkdir(parents=True)
    (source / "terraform/main.tf").write_text("terraform {}", encoding="utf-8")
    artifacts = [
        ".terraform/provider",
        ".terraform.lock.hcl",
        "terraform.tfstate",
        "terraform.tfstate.backup",
        "tfplan",
        "old.plan.json",
        "__pycache__/cached.pyc",
        ".env",
        ".env.local",
        ".DS_Store",
    ]
    for name in artifacts:
        path = source / "terraform" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic local artifact")
    target = tmp_path / "fixtures/unused-grant"
    target.mkdir(parents=True)
    review = target / "human-review.md"
    review.write_bytes(b"Human-owned content")
    original_open = Path.open

    def guarded_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.name == "expected.json":
            raise AssertionError("The generator must never open an answer key")
        return original_open(path, *args, **kwargs)

    def fake_plan(command: list[str], **kwargs: Any) -> None:
        Path(command[-1]).write_bytes((FIXTURES / "intern/base.plan.json").read_bytes())

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(subprocess, "run", fake_plan)
    module["generate"]("unused-grant", source, tmp_path / "fixtures")
    assert [
        p.relative_to(target / "base").as_posix() for p in (target / "base").rglob("*") if p.is_file()
    ] == ["terraform/main.tf"]
    assert review.read_bytes() == b"Human-owned content"


def test_provider_is_pinned_and_uses_only_literal_mock_settings() -> None:
    plan = json.loads((FIXTURES / "intern/base.plan.json").read_text(encoding="utf-8"))
    provider = plan["configuration"]["provider_config"]["aws"]
    assert provider["full_name"] == "registry.terraform.io/hashicorp/aws"
    assert provider["version_constraint"] == "~> 6.69"
    configured = provider["expressions"]
    for key, value in {
        "access_key": "mock",
        "secret_key": "mock",
        "region": "eu-west-1",
        "skip_credentials_validation": True,
        "skip_requesting_account_id": True,
        "skip_metadata_api_check": True,
    }.items():
        assert configured[key] == {"constant_value": value}
    assert 'required_version = "= 1.16.6"' in (WORLD / "terraform/providers.tf").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["github_deploy", "terraform_apply"])
def test_ci_roles_use_the_exact_oidc_issuer_and_action(resources: dict[str, Any], name: str) -> None:
    provider = resources["aws_iam_openid_connect_provider.github"]
    assert provider["url"] == "https://token.actions.githubusercontent.com"
    assert provider["client_id_list"] == ["sts.amazonaws.com"]
    policy = json.loads(resources[f"aws_iam_role.{name}"]["assume_role_policy"])
    assert policy["Version"] == "2012-10-17"
    (statement,) = policy["Statement"]
    assert set(statement) == {"Sid", "Effect", "Principal", "Action", "Condition"}
    assert statement["Sid"] == "GitHubActionsOIDC" and statement["Effect"] == "Allow"
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert statement["Principal"] == {"Federated": IAM + "oidc-provider/token.actions.githubusercontent.com"}


def test_resources_remain_in_the_files_assigned_by_spec() -> None:
    modeled = SPEC.split("## Terraform that Theseus models\n")[1].split("## Terraform that Theseus skips")[0]
    expected: dict[str, str] = {}
    for filename, table in re.findall(r"### `([^`]+\.tf)`\n(.*?)(?=\n### |\Z)", modeled, re.S):
        for address in re.findall(r"^\| `(aws_\w+\.\w+)`", table, re.M):
            expected[address] = filename
    for name in ("billing_job", "billing_api", "support_portal", "analytics_export"):
        expected[f"aws_iam_role_policy_attachment.{name}_logs"] = "services.tf"
    actual: dict[str, str] = {}
    paths = sorted((WORLD / "terraform").glob("*.tf"))
    assert {p.stem for p in paths} == {"providers", *F4_MODELED, *C1_MODELED, *SKIPPED}
    for path in paths:
        if path.stem in SKIPPED:
            continue  # test_every_skipped_resource_spec_02_lists_exists checks these against the skip table
        for kind, name in re.findall(
            r'^resource "([^"]+)" "([^"]+)"', path.read_text(encoding="utf-8"), re.M
        ):
            address = f"{kind}.{name}"
            assert address not in actual
            actual[address] = path.name
    assert actual == expected


@pytest.mark.parametrize("configured", ["absolute", "on-path"])
def test_bash_override_takes_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    executable = tmp_path / "chosen shell" / "bash"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\n", encoding="utf-8", newline="\n")
    executable.chmod(0o755)
    value = str(executable) if configured == "absolute" else "chosen-bash"
    monkeypatch.setenv("THESEUS_BASH", value)
    monkeypatch.setattr(
        module["shutil"], "which", lambda command: str(executable) if command == value else None
    )
    assert module["resolve_bash"]() == str(executable)


@pytest.mark.parametrize("configured", ["missing-bash", "a-directory"])
def test_invalid_bash_override_is_reported_instead_of_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    directory = tmp_path / configured
    if configured == "a-directory":
        directory.mkdir()
    monkeypatch.setenv("THESEUS_BASH", str(directory))
    with pytest.raises(IngestError, match="THESEUS_BASH"):
        module["resolve_bash"]()


@pytest.mark.parametrize("git_bin", ["cmd", "bin", "mingw64/bin"])
def test_windows_bash_is_found_beside_git_before_the_wsl_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_bin: str
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    git_root = tmp_path / "Git with spaces"
    executable = git_root / "usr/bin/bash.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    executable.chmod(0o755)
    monkeypatch.delenv("THESEUS_BASH", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        module["shutil"],
        "which",
        lambda command: {
            "git": str(git_root / git_bin / "git.exe"),
            "bash": r"C:\Windows\System32\bash.exe",
        }.get(command),
    )
    assert module["resolve_bash"]() == str(executable)


@pytest.mark.parametrize("setting", ["ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"])
def test_windows_bash_is_found_in_standard_install_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    root = tmp_path / "installed programs"
    executable = root / ("Programs/Git" if setting == "LOCALAPPDATA" else "Git") / "usr/bin/bash.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    executable.chmod(0o755)
    for key in ("THESEUS_BASH", "ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(setting, str(root))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(module["shutil"], "which", lambda command: None)
    assert module["resolve_bash"]() == str(executable)


@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_bash_can_fall_back_to_a_native_shell_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    executable = tmp_path / "native/bin/bash"
    executable.parent.mkdir(parents=True)
    executable.touch()
    executable.chmod(0o755)
    for key in ("THESEUS_BASH", "ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(
        module["shutil"], "which", lambda command: str(executable) if command == "bash" else None
    )
    assert module["resolve_bash"]() == str(executable)


@pytest.mark.parametrize("directory", ["System32", "Sysnative", "WindowsApps"])
def test_windows_wsl_launchers_are_not_used_as_native_bash(
    monkeypatch: pytest.MonkeyPatch, directory: str
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    for key in ("THESEUS_BASH", "ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        module["shutil"],
        "which",
        lambda command: rf"C:\Windows\{directory}\bash.exe" if command == "bash" else None,
    )
    with pytest.raises(IngestError, match="Git Bash|Git for Windows|THESEUS_BASH"):
        module["resolve_bash"]()


def test_missing_bash_has_an_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    monkeypatch.delenv("THESEUS_BASH", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(module["shutil"], "which", lambda command: None)
    with pytest.raises(IngestError, match="THESEUS_BASH"):
        module["resolve_bash"]()


def test_generator_resolves_bash_once_for_both_plans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    chosen = str(tmp_path / "Git with spaces/usr/bin/bash.exe")
    resolved: list[str] = []
    commands: list[list[str]] = []

    def resolve() -> str:
        resolved.append(chosen)
        return chosen

    def fake_plan(command: list[str], **kwargs: Any) -> None:
        commands.append(command)
        Path(command[-1]).write_bytes((FIXTURES / "intern/base.plan.json").read_bytes())

    monkeypatch.setitem(module["generate"].__globals__, "resolve_bash", resolve)
    monkeypatch.setattr(subprocess, "run", fake_plan)
    module["generate"]("intern", WORLD, tmp_path / "fixtures")
    assert resolved == [chosen]
    assert len(commands) == 2
    assert all(command[0] == chosen for command in commands)


def test_generator_cli_resolves_bash_once_for_all_scenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    resolved: list[str] = []
    generated: list[tuple[str, str]] = []

    def resolve() -> str:
        resolved.append("chosen-bash")
        return "chosen-bash"

    def generate(name: str, world: Path, fixtures: Path, *, bash: str | None = None) -> None:
        generated.append((name, bash))

    monkeypatch.setitem(module["main"].__globals__, "resolve_bash", resolve)
    monkeypatch.setitem(module["main"].__globals__, "generate", generate)
    monkeypatch.setattr(sys, "argv", ["make_fixture.py", "all"])
    assert module["main"]() == 0
    assert resolved == ["chosen-bash"]
    assert generated == [(name, "chosen-bash") for name in sorted(module["SCENARIOS"])]


@pytest.mark.parametrize("native", [False, True])
def test_windows_shell_paths_use_cygpath_without_losing_spaces(
    monkeypatch: pytest.MonkeyPatch, native: bool
) -> None:
    path = "/tmp/work with spaces " if native else r"C:\Users\A Person\project"
    converted = r"C:\Program Files\Git\tmp\work with spaces " if native else "/c/Users/A Person/project"
    commands: list[list[str]] = []

    def convert(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=converted + "\n", stderr="")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", convert)
    assert shell_path(path, "chosen-bash", native=native) == converted
    assert commands[0][0] == "chosen-bash"
    assert commands[0][-2:] == ["-w" if native else "-u", path]


def test_windows_shell_test_path_is_set_inside_bash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[tuple[list[str], dict[str, Any]]] = []
    chosen = "chosen-bash"

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append((command, kwargs))
        if "cygpath" in command[2]:
            return subprocess.CompletedProcess(command, 0, stdout="/c/test path\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setattr(runpy, "run_path", lambda path: {"resolve_bash": lambda: chosen})
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_plan_script(
        tmp_path / "source", tmp_path / "result.json", bin_dir=tmp_path, env={"SOURCE": tmp_path}
    )
    command, kwargs = commands[-1]
    assert result.returncode == 0
    assert command[0] == chosen
    assert command[1] == "-c"
    assert command[4] == "/c/test path"
    assert kwargs["env"]["SOURCE"] == "/c/test path"
    assert kwargs["env"]["SYSTEMROOT"] == r"C:\Windows"


def test_missing_bash_does_not_create_or_replace_fixture_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))

    def unavailable() -> str:
        raise IngestError("Set THESEUS_BASH")

    monkeypatch.setitem(module["generate"].__globals__, "resolve_bash", unavailable)
    with pytest.raises(IngestError, match="THESEUS_BASH"):
        module["generate"]("intern", WORLD, tmp_path / "fixtures")
    assert not (tmp_path / "fixtures").exists()


def test_windows_plan_command_has_the_selected_shell_utilities_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    bash = str(tmp_path / "Git with spaces/usr/bin/bash.exe")
    output = tmp_path / "plan.json"
    commands: list[tuple[list[str], dict[str, Any]]] = []

    def fake_plan(command: list[str], **kwargs: Any) -> None:
        commands.append((command, kwargs))
        output.write_bytes((FIXTURES / "intern/base.plan.json").read_bytes())

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("PATH", "existing-search-path")
    monkeypatch.setattr(subprocess, "run", fake_plan)
    module["plan_world"](tmp_path / "world with spaces", output, bash=bash)
    command, kwargs = commands[0]
    assert command == [
        bash,
        "--",
        (ROOT / "tools/plan.sh").as_posix(),
        (tmp_path / "world with spaces/terraform").as_posix(),
        output.as_posix(),
    ]
    assert kwargs["env"]["PATH"] == str(Path(bash).parent) + os.pathsep + "existing-search-path"
    assert kwargs["check"] is True


@pytest.mark.parametrize("directory", ["System32", "Sysnative", "WindowsApps"])
def test_windows_bash_override_cannot_select_a_wsl_launcher(
    monkeypatch: pytest.MonkeyPatch, directory: str
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    launcher = rf"C:\Windows\{directory}\bash.exe"
    monkeypatch.setenv("THESEUS_BASH", launcher)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(module["shutil"], "which", lambda command: launcher)
    with pytest.raises(IngestError, match="THESEUS_BASH"):
        module["resolve_bash"]()


@pytest.mark.parametrize(
    "name",
    [
        "two spaces here",
        "an apostrophe's path",
        "ampersand & parentheses (1)",
        "literal $(echo expanded) and `echo expanded`",
        "semicolon; path",
        "café 店",
    ],
)
def test_plan_script_preserves_literal_paths_with_shell_characters(tmp_path: Path, name: str) -> None:
    directory = tmp_path / name
    source = directory / "source"
    source.mkdir(parents=True)
    (source / "main.tf").write_text("terraform {}", encoding="utf-8", newline="\n")
    output = directory / "result.json"
    record = directory / "source-record"
    executable = directory / "terraform"
    executable.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'work="${1#-chdir=}"\n'
        '[[ -f "$work/main.tf" ]] || exit 90\n'
        'if [[ "$2" == show ]]; then echo \'{"ok":true}\'; fi\n'
        'printf "%s" "$SOURCE" > "$SOURCE_RECORD"\n',
        encoding="utf-8",
        newline="\n",
    )
    executable.chmod(0o755)
    result = run_plan_script(
        source, output, bin_dir=directory, env={"SOURCE": source, "SOURCE_RECORD": record}
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
    bash = runpy.run_path(str(ROOT / "tools/make_fixture.py"))["resolve_bash"]()
    assert record.read_text(encoding="utf-8") == shell_path(source, bash)
    assert sorted(p.name for p in source.iterdir()) == ["main.tf"]
    assert not list(directory.glob(".theseus-plan.*"))


def test_generator_executes_the_plan_script_with_native_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    world = tmp_path / "world with spaces"
    (world / "terraform").mkdir(parents=True)
    (world / "terraform/people.tf").write_text("terraform {}\n", encoding="utf-8", newline="\n")
    tools = tmp_path / "test tools"
    tools.mkdir()
    record = tmp_path / "calls.txt"
    executable = tools / "terraform"
    executable.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'echo "$2" >> "$THESEUS_TEST_PLAN_CALLS"\n'
        'if [[ "$2" == show ]]; then\n'
        '  echo \'{"planned_values":{"root_module":{"resources":[]}},'
        '"resource_changes":[],"timestamp":"remove"}\'\n'
        "fi\n",
        encoding="utf-8",
        newline="\n",
    )
    executable.chmod(0o755)
    bash = module["resolve_bash"]()
    monkeypatch.setenv("THESEUS_BASH", bash)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("THESEUS_TEST_PLAN_CALLS", record.as_posix())
    module["generate"]("intern", world, tmp_path / "fixture output")
    assert record.read_text(encoding="utf-8").splitlines() == ["init", "plan", "show"] * 2
    for side in ("base", "head"):
        plan = json.loads((tmp_path / f"fixture output/intern/{side}.plan.json").read_text(encoding="utf-8"))
        assert plan == {"planned_values": {"root_module": {"resources": []}}, "resource_changes": []}
    assert not list((tmp_path / "fixture output").glob(".intern-*"))
