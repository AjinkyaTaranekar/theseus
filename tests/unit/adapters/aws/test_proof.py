"""Where AWS publishes each price, and the read-only check that a resource is idle (aws/proof.py)."""

from __future__ import annotations

from theseus.adapters.aws.cost import monthly_cost
from theseus.adapters.aws.proof import PRICING, proof_fields
from theseus.contracts.adapters import IacResource


def res(type_: str, label: str, **values: object) -> IacResource:
    return IacResource(address=f"{type_}.{label}", type=type_, name=label, provider="aws", values=values)


def test_a_database_links_its_engine_s_pricing_page_and_a_connections_check() -> None:
    db = res("aws_db_instance", "reports_replica", identifier="reports-replica", engine="postgres")
    found = proof_fields(db, "eu-west-1")
    assert found["pricing_url"] == "https://aws.amazon.com/rds/postgresql/pricing/"
    assert "--metric-name DatabaseConnections" in found["idle_check"]
    assert "Value=reports-replica" in found["idle_check"] and "--region eu-west-1" in found["idle_check"]
    assert found["idle_expect"].startswith("Every daily Maximum is 0")
    # A snapshot comes before anything is stopped or removed.
    assert found["retire"][0].startswith(
        "aws rds create-db-snapshot --db-instance-identifier reports-replica"
    )


def test_every_check_reads_and_never_changes_anything() -> None:
    checks = [
        proof_fields(res("aws_db_instance", "a", identifier="a"), "eu-west-1"),
        proof_fields(res("aws_lambda_function", "a", function_name="a"), "eu-west-1"),
        proof_fields(res("aws_dynamodb_table", "a", name="a"), "eu-west-1"),
        proof_fields(res("aws_secretsmanager_secret", "a", name="a"), "eu-west-1"),
        proof_fields(res("aws_sqs_queue", "a", name="a"), "eu-west-1"),
        proof_fields(res("aws_sns_topic", "a", name="a"), "eu-west-1"),
        proof_fields(res("aws_cloudwatch_log_group", "a", name="a"), "eu-west-1"),
        proof_fields(res("aws_s3_bucket", "a", bucket="a"), "eu-west-1"),
    ]
    for found in checks:
        verb = found["idle_check"].split()[2]
        assert verb.startswith(("get-", "describe-", "ls")), found["idle_check"]


def test_a_name_unknown_at_plan_gives_no_check_and_every_page_is_aws_s_own() -> None:
    assert "idle_check" not in proof_fields(res("aws_db_instance", "a"), "eu-west-1")
    assert all(url.startswith("https://aws.amazon.com/") for url in PRICING.values())


def test_each_priced_line_carries_its_pricing_page() -> None:
    lines = monthly_cost(
        [res("aws_kms_key", "k"), res("aws_secretsmanager_secret", "s", name="s")], "eu-west-1"
    )
    assert {line.address: line.pricing_url for line in lines} == {
        "aws_kms_key.k": "https://aws.amazon.com/kms/pricing/",
        "aws_secretsmanager_secret.s": "https://aws.amazon.com/secrets-manager/pricing/",
    }
