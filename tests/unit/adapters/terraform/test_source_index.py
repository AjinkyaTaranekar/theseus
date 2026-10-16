"""Source citations stay inside the correct resource and never guess a line."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from theseus.adapters.terraform.adapter import TerraformAdapter

ROOT = Path(__file__).resolve().parents[4]


def test_real_resource_and_statement_lines() -> None:
    files = {
        p.relative_to(ROOT / "demo-infra").as_posix(): p.read_text()
        for p in (ROOT / "demo-infra" / "terraform").glob("*.tf")
    }
    adapter = TerraformAdapter()
    roles = files["terraform/roles.tf"].splitlines()
    for address, sid in [
        ("aws_iam_role_policy.prod_support_read", "ReadInvoices"),
        ("aws_iam_role_policy.prod_support_read", "ReadDbSecret"),
    ]:
        # The statement's own `Sid = "..."` line, found in the file, so an added comment never breaks this.
        (line,) = [i for i, text in enumerate(roles, 1) if re.fullmatch(rf'\s*Sid\s*=\s*"{sid}"', text)]
        ev = adapter.locate(files, address, sid)
        assert ev.file == "terraform/roles.tf" and ev.line == line
        assert ev.part == sid


@pytest.mark.parametrize("address", ["aws_iam_role.a", 'module.app["blue"].aws_iam_role.a[0]'])
def test_comments_strings_heredocs_and_balanced_blocks(address: str) -> None:
    text = """# resource "aws_iam_role" "a" { }
/* resource "aws_iam_role" "a" { } */
locals {
  fake = <<EOF
resource "aws_iam_role" "a" { }
EOF
}
resource "aws_iam_role" "a" {
  note = "} fake {"
  assume_role_policy = jsonencode({
    Statement = [{ Sid = "Correct", Action = "sts:AssumeRole" }]
  })
}
resource "aws_iam_role" "b" {
  Sid = "Other"
}
"""
    files = (
        {"terraform/main.tf": text}
        if not address.startswith("module.")
        else {"terraform/main.tf": 'module "app" { source = "./app" }\n', "terraform/app/main.tf": text}
    )
    expected = "terraform/main.tf" if not address.startswith("module.") else "terraform/app/main.tf"
    ev = TerraformAdapter().locate(files, address, "Correct")
    assert (ev.file, ev.line) == (expected, 11)
    missing = TerraformAdapter().locate(files, address, "Other")
    assert missing.file == "unknown" and missing.line is None and missing.note


def test_absent_or_ambiguous_source_is_explicitly_unknown() -> None:
    adapter = TerraformAdapter()
    for files in [
        {},
        {
            "terraform/a.tf": 'resource "aws_iam_role" "a" {}\n',
            "terraform/b.tf": 'resource "aws_iam_role" "a" {}\n',
        },
    ]:
        ev = adapter.locate(files, "aws_iam_role.a", None)
        assert ev.file == "unknown" and ev.line is None and ev.note


def test_module_resource_uses_its_own_source() -> None:
    files = {
        "terraform/main.tf": 'resource "aws_iam_role" "a" {}\n',
        "terraform/modules/child/main.tf": '\nresource "aws_iam_role" "a" {}\n',
        "terraform/modules.tf": 'module "child" {\n  source = "./modules/child"\n}\n',
    }
    ev = TerraformAdapter().locate(files, "module.child.aws_iam_role.a", None)
    assert (ev.file, ev.line) == ("terraform/modules/child/main.tf", 2)


def test_header_citation_does_not_land_on_a_preceding_comment() -> None:
    text = '# resource "aws_iam_role" "a" {}\n\nresource "aws_iam_role" "a" {}\n'
    ev = TerraformAdapter().locate({"terraform/main.tf": text}, "aws_iam_role.a", None)
    assert ev.line == 3


def test_duplicate_sid_is_not_given_the_first_line() -> None:
    text = """resource "aws_iam_role_policy" "a" {
  policy = jsonencode({ Statement = [
    { Sid = "Repeated", Effect = "Allow" },
    { Sid = "Repeated", Effect = "Deny" }
  ] })
}
"""
    ev = TerraformAdapter().locate({"terraform/main.tf": text}, "aws_iam_role_policy.a", "Repeated")
    assert ev.file == "unknown" and ev.line is None and ev.note


def test_relocated_source_never_reuses_an_old_line() -> None:
    files = {"terraform/main.tf": 'resource "aws_iam_role" "a" {}\n'}
    adapter = TerraformAdapter()
    assert adapter.locate(files, "aws_iam_role.a", None).line == 1
    files["terraform/main.tf"] = "\n\n" + files["terraform/main.tf"]
    assert adapter.locate(files, "aws_iam_role.a", None).line == 3


def test_a_dash_in_a_heredoc_marker_does_not_expose_fake_resources() -> None:
    text = """locals {
  example = <<-END-TEXT
resource "aws_iam_role" "a" {}
END-TEXT
}

resource "aws_iam_role" "a" {}
"""
    ev = TerraformAdapter().locate({"terraform/main.tf": text}, "aws_iam_role.a", None)
    assert (ev.file, ev.line) == ("terraform/main.tf", 7)


def test_a_duplicate_resource_remains_ambiguous_even_when_only_one_sid_matches() -> None:
    text = """resource "aws_iam_role_policy" "a" {
  policy = jsonencode({ Statement = [{ Sid = "Wanted" }] })
}
resource "aws_iam_role_policy" "a" {
  policy = jsonencode({ Statement = [{ Sid = "Other" }] })
}
"""
    ev = TerraformAdapter().locate({"terraform/main.tf": text}, "aws_iam_role_policy.a", "Wanted")
    assert ev.file == "unknown" and ev.line is None and ev.note


def test_nested_source_argument_is_not_the_module_source() -> None:
    files = {
        "terraform/main.tf": """module "child" {
  settings = { source = "./wrong" }
  source = "./right"
}
""",
        "terraform/wrong/main.tf": 'resource "aws_iam_role" "a" {}\n',
        "terraform/right/main.tf": '\nresource "aws_iam_role" "a" {}\n',
    }
    ev = TerraformAdapter().locate(files, "module.child.aws_iam_role.a", None)
    assert (ev.file, ev.line) == ("terraform/right/main.tf", 2)


def test_tags_and_policy_conditions_do_not_supply_a_statement_sid() -> None:
    text = """resource "aws_iam_role_policy" "a" {
  tags = { Sid = "Wanted" }
  policy = jsonencode({ Statement = [{
    Sid = "Actual"
    Condition = { StringEquals = { Sid = "Wanted" } }
  }] })
}
"""
    ev = TerraformAdapter().locate({"terraform/main.tf": text}, "aws_iam_role_policy.a", "Wanted")
    assert ev.file == "unknown" and ev.line is None and ev.note


def test_an_unclosed_resource_never_takes_a_later_resources_sid() -> None:
    text = """resource "aws_iam_role_policy" "a" {
resource "aws_iam_role_policy" "b" {
  policy = jsonencode({ Statement = [{ Sid = "Wrong" }] })
}
"""
    ev = TerraformAdapter().locate({"terraform/main.tf": text}, "aws_iam_role_policy.b", "Wrong")
    assert ev.file == "unknown" and ev.line is None and ev.note


def test_a_nested_policy_shaped_value_is_not_the_outer_statement() -> None:
    text = """resource "aws_iam_role_policy" "a" {
  policy = jsonencode({ Statement = [{
    Sid = var.sid
    Condition = { StringEquals = {
      Statement = jsonencode({ Statement = [{ Sid = "Wanted" }] })
    } }
  }] })
}
"""
    ev = TerraformAdapter().locate({"terraform/main.tf": text}, "aws_iam_role_policy.a", "Wanted")
    assert ev.file == "unknown" and ev.line is None and ev.note
