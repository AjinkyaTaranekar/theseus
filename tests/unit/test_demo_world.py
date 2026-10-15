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
    assert set(resources) == expected


def has_unknown(value: Any) -> bool:
    if isinstance(value, dict):
        return any(has_unknown(v) for v in value.values())
    if isinstance(value, list):
        return any(has_unknown(v) for v in value)
    return value is True


@pytest.mark.parametrize("scenario", ["intern", "public-bucket", "compromised-action", "unused-grant"])
def test_all_modeled_fields_are_known(scenario: str) -> None:
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
    plans = sorted((FIXTURES / scenario).glob("*.plan.json"))
    assert plans
    for path in plans:
        plan = json.loads(path.read_text(encoding="utf-8"))
        assert plan["resource_changes"]
        for resource in plan["resource_changes"]:
            for field in sorted(fields):
                if field == "policy" and resource["type"] in {"aws_s3_bucket", "aws_secretsmanager_secret"}:
                    continue  # P1: these computed attributes are not modeled policy documents.
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
    modes = {"intern": "pr", "public-bucket": "pr", "compromised-action": "finding", "unused-grant": "scan"}
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
    for name in ("intern", "public-bucket"):
        section = SPEC.split(f"### `{name}`")[1].split("\n### ")[0]
        title = re.search(r'\*\*PR title:\*\* "(.+)"', section)
        body = re.search(r'\*\*PR body:\*\* "(.+)"', section)
        assert title and body
        assert (FIXTURES / name / "pr.md").read_text(encoding="utf-8") == (f"# {title[1]}\n\n{body[1]}\n")


@pytest.mark.parametrize("scenario", ["intern", "public-bucket", "compromised-action", "unused-grant"])
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
    added = (
        "aws_iam_user_group_membership.priya_support"
        if scenario == "intern"
        else ("aws_s3_bucket_policy.company_files_public")
    )
    assert set(head_resources) - set(base_resources) == {added}
    assert {a: v for a, v in head_resources.items() if a != added} == base_resources
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
    result = subprocess.run(["bash", str(ROOT / "tools/plan.sh")], capture_output=True, text=True)
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


def test_generator_rejects_code_pr_until_c1(tmp_path: Path) -> None:
    module = runpy.run_path(str(ROOT / "tools/make_fixture.py"))
    with pytest.raises(IngestError, match="C1"):
        module["generate"]("code-pr", WORLD, tmp_path / "fixtures")
    assert not (tmp_path / "fixtures").exists()


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
    )
    executable.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "tools/plan.sh"), str(source), str(output)],
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "SOURCE": str(source),
            "AWS_PROFILE": "synthetic-profile",
            "AWS_DEFAULT_PROFILE": "synthetic-default",
            "AWS_SESSION_TOKEN": "mock",
            "AWS_CONFIG_FILE": str(source / "missing-config"),
            "AWS_SHARED_CREDENTIALS_FILE": str(source / "missing-credentials"),
        },
        capture_output=True,
        text=True,
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
    assert {p for p in base_files if base_files[p] != head_files[p]} == {Path(changed)}


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


@pytest.mark.parametrize(
    "args,status,expected",
    [
        ([], 2, "required"),
        (["unknown"], 2, "invalid choice"),
        (["code-pr"], 1, "C1"),
        (["--help"], 0, "usage:"),
    ],
)
def test_generator_cli_reports_invalid_or_deferred_requests(
    args: list[str], status: int, expected: str
) -> None:
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
    )
    executable.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "tools/plan.sh"), str(source), str(output)],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", "FAIL_STAGE": failed_stage, "WORK_RECORD": str(record)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == (0 if failed_stage == "none" else 7), result.stderr
    if failed_stage == "none":
        assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
    elif existing_output:
        assert output.read_text(encoding="utf-8") == "previous plan"
    else:
        assert not output.exists()
    assert not Path(record.read_text(encoding="utf-8")).exists()
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
    )
    executable.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "tools/plan.sh"), str(source), str(tmp_path / "result.json")],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", "EXPECTED_WORK": str(work)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 7
    assert not work.exists()


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
    for path in (WORLD / "terraform").glob("*.tf"):
        for kind, name in re.findall(
            r'^resource "([^"]+)" "([^"]+)"', path.read_text(encoding="utf-8"), re.M
        ):
            address = f"{kind}.{name}"
            assert address not in actual
            actual[address] = path.name
    assert actual == expected
