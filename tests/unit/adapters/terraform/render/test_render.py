"""E9 edits are exact, parseable and atomic; snapshots are reviewer-owned examples, not golden keys."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import hcl2
import pytest

from theseus.adapters.terraform.adapter import TerraformAdapter
from theseus.adapters.terraform.render import render as render_files
from theseus.contracts.result import PatchOp
from theseus.errors import PatchError

ROOT = Path(__file__).resolve().parents[5]
SNAPSHOTS = Path(__file__).parent / "snapshots"
GENERATED = "terraform/theseus_fixes.tf"
ACCOUNT = "111122223333"
SOURCE = """# Keep this file's unrelated text exactly.
resource "aws_iam_user" "priya" { name = "priya-intern" }
resource "aws_iam_group" "support" { name = "support-engineers" }
resource "aws_iam_group" "interns" { name = "interns" }
resource "aws_iam_user_group_membership" "priya" {
  user = "priya-intern"
  groups = ["support-engineers", "other"]
}
resource "aws_iam_role" "deploy" {
  name = "github-deploy"
  assume_role_policy = jsonencode({
    Statement = [{
      Action = "sts:AssumeRoleWithWebIdentity"
      Principal = {
        Federated = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
      }
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike = { "token.actions.githubusercontent.com:sub" = "repo:demo-org/*" }
      }
    }]
  })
}
resource "aws_iam_role_policy" "read" {
  role = "github-deploy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "Read" Effect = "Allow" Action = "s3:GetObject" Resource = "*" },
      { Sid = "Keep" Effect = "Allow" Action = "s3:ListBucket" Resource = "safe" }
    ]
  })
}
"""
STATEMENT = {
    "sid": "ReadLogs",
    "effect": "Allow",
    "actions": ["s3:GetObject"],
    "resources": ["arn:aws:s3:::logs/*"],
}
CASES = {
    "remove_membership": {"user": "priya-intern", "group": "support-engineers"},
    "remove_statement": {"policy_address": "aws_iam_role_policy.read", "sid": "Read"},
    "set_statement_resources": {
        "policy_address": "aws_iam_role_policy.read",
        "sid": "Read",
        "resources": ["safe/*"],
    },
    "set_oidc_sub": {"role": "github-deploy", "patterns": ["repo:demo-org/infra:ref:refs/heads/main"]},
    "add_membership": {"user": "priya-intern", "group": "interns"},
    "add_policy": {"principal": "user:priya-intern", "statements": [STATEMENT]},
    "add_role": {
        "name": "intern-onboarding",
        "trust_principals": ["user:priya-intern"],
        "statements": [STATEMENT],
    },
}


def render(files: dict[str, str], ops: list[PatchOp]) -> dict[str, str]:
    return render_files(files, ops, account=ACCOUNT)


def op(operation: str, **args: object) -> PatchOp:
    return PatchOp(provider="aws", op=operation, args=args or deepcopy(CASES[operation]))


def parse_all(files: dict[str, str]) -> None:
    for name, text in files.items():
        if name.endswith(".tf"):
            hcl2.loads(text)


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_op_matches_its_review_snapshot(name: str) -> None:
    files = {"terraform/main.tf": SOURCE}
    result = render(files, [op(name)])
    assert files == {"terraform/main.tf": SOURCE}
    assert result is not files
    changed = {path: text for path, text in result.items() if files.get(path) != text}
    assert len(changed) == 1
    assert next(iter(changed.values())) == (SNAPSHOTS / f"{name}.tf").read_text()
    parse_all(result)
    assert TerraformAdapter({"account": ACCOUNT}).render(files, [op(name)]) == result


def test_no_ops_returns_an_independent_sorted_copy() -> None:
    files = {"terraform/z.tf": "# z\n", "terraform/a.tf": "# a\n"}
    result = render(files, [])
    assert result == files and result is not files
    assert list(result) == sorted(files)


@pytest.mark.parametrize("position", [0, 1, 2])
def test_statement_removal_handles_first_middle_last_and_comments(position: int) -> None:
    statements = [
        '{ Sid = "A" Resource = "a" }',
        '{ Sid = "B" Resource = "b" }',
        '{ Sid = "C" Resource = "c" }',
    ]
    text = (
        'resource "aws_iam_policy" "shared" {\n policy = jsonencode({Statement = ['
        + ", # comma, { }\n".join(statements)
        + "]})\n}\n"
    )
    result = render(
        {"terraform/main.tf": text},
        [op("remove_statement", policy_address="aws_iam_policy.shared", sid="ABC"[position])],
    )
    parse_all(result)
    assert f'Sid = "{"ABC"[position]}"' not in result["terraform/main.tf"]
    for sid in "ABC"[:position] + "ABC"[position + 1 :]:
        assert f'Sid = "{sid}"' in result["terraform/main.tf"]


def test_removal_of_only_group_deletes_the_resource_not_neighbors() -> None:
    text = SOURCE.replace('["support-engineers", "other"]', '["support-engineers"]')
    result = render({"terraform/main.tf": text}, [op("remove_membership")])
    assert 'resource "aws_iam_user_group_membership" "priya"' not in result["terraform/main.tf"]
    assert 'resource "aws_iam_user" "priya"' in result["terraform/main.tf"]
    parse_all(result)


MORE_GROUPS = (
    'resource "aws_iam_group" "ops" { name = "ops" }\nresource "aws_iam_group" "eng" { name = "engineers" }\n'
)
SUPPORT = "aws_iam_group.support.name"
OPS = "aws_iam_group.ops.name"
ENG = "aws_iam_group.eng.name"


def with_groups(groups: str) -> str:
    return SOURCE.replace('["support-engineers", "other"]', groups) + MORE_GROUPS


@pytest.mark.parametrize(
    "before,after",
    [
        (f"[{SUPPORT}, {OPS}, {ENG}]", f"[{OPS}, {ENG}]"),
        (f"[{OPS}, {SUPPORT}, {ENG}]", f"[{OPS}, {ENG}]"),
        (f'[{OPS}, "other", {SUPPORT}]', f'[{OPS}, "other"]'),
        (f'[{OPS}, "support-engineers", {ENG}]', f"[{OPS}, {ENG}]"),
        (f'[{SUPPORT}, "other", "support-engineers"]', '["other"]'),
        (
            f'[\n    {OPS}, # on-call\n    {SUPPORT}, # support\n    # kept on purpose\n    "other",\n  ]',
            f'[\n    {OPS}, # on-call\n    # kept on purpose\n    "other",\n  ]',
        ),
        (f'[\n    "other", # keep\n    {SUPPORT}\n  ]', '[\n    "other", # keep\n  ]'),
    ],
    ids=["first", "middle", "last", "literal", "duplicates", "own-line", "own-line-last"],
)
def test_membership_removal_deletes_only_that_element_as_written(before: str, after: str) -> None:
    result = render({"terraform/main.tf": with_groups(before)}, [op("remove_membership")])
    assert result["terraform/main.tf"] == with_groups(after)
    parse_all(result)


@pytest.mark.parametrize("groups", [f"[{SUPPORT}]", f'[{SUPPORT}, "support-engineers"]'])
def test_membership_removal_deletes_the_resource_when_no_other_group_is_left(groups: str) -> None:
    result = render({"terraform/main.tf": with_groups(groups)}, [op("remove_membership")])
    text = result["terraform/main.tf"]
    assert 'resource "aws_iam_user_group_membership" "priya"' not in text
    assert 'resource "aws_iam_user" "priya"' in text and text.endswith(MORE_GROUPS)
    parse_all(result)


def test_semantics_use_real_sids_not_fake_text_in_comments_or_heredocs() -> None:
    extra = """locals {
  fake = <<EOF
resource "aws_iam_role_policy" "read" { policy = jsonencode({Statement=[{Sid="Read"}]}) }
EOF
}
# { } , resource "aws_iam_role_policy" "read" {}
"""
    result = render({"terraform/main.tf": extra + SOURCE}, [op("set_statement_resources")])
    assert result["terraform/main.tf"].startswith(extra)
    assert 'Resource = ["safe/*"]' in result["terraform/main.tf"]
    parse_all(result)


def test_literal_membership_references_resolve_without_guessing() -> None:
    text = SOURCE.replace('user = "priya-intern"', "user = aws_iam_user.priya.name").replace(
        '["support-engineers", "other"]', '[aws_iam_group.support.name, "other"]'
    )
    result = render({"terraform/main.tf": text}, [op("remove_membership")])
    assert 'groups = ["other"]' in result["terraform/main.tf"]


def test_edits_in_a_local_module_do_not_touch_an_identical_root_resource() -> None:
    files = {
        "terraform/main.tf": SOURCE + '\nmodule "child" { source = "./child" }\n',
        "terraform/child/main.tf": SOURCE,
    }
    result = render(
        files,
        [
            op(
                "set_statement_resources",
                policy_address="module.child.aws_iam_role_policy.read",
                sid="Read",
                resources=["narrow"],
            )
        ],
    )
    assert result["terraform/main.tf"] == files["terraform/main.tf"]
    assert 'Resource = ["narrow"]' in result["terraform/child/main.tf"]


def test_oidc_stringequals_sub_moves_to_stringlike_preserving_audience() -> None:
    text = SOURCE.replace(
        'StringLike = { "token.actions.githubusercontent.com:sub"',
        'StringEquals = { "token.actions.githubusercontent.com:sub"',
    )
    # Use one StringEquals object, not duplicate condition operators.
    text = text.replace('"sts.amazonaws.com" }\n        StringEquals = {', '"sts.amazonaws.com",')
    result = render({"terraform/main.tf": text}, [op("set_oidc_sub")])
    assert '"token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"' in result["terraform/main.tf"]
    assert "StringLike" in result["terraform/main.tf"]
    assert "repo:demo-org/*" not in result["terraform/main.tf"]
    parse_all(result)


def test_generated_blocks_can_be_followed_by_later_ops() -> None:
    result = render(
        {"terraform/main.tf": SOURCE},
        [op("add_role"), op("add_policy", principal="role:intern-onboarding", statements=[STATEMENT])],
    )
    assert "aws_iam_role_policy" in result[GENERATED]
    assert '"arn:aws:iam::111122223333:user/priya-intern"' in result[GENERATED]
    assert "depends_on = [aws_iam_user.priya]" in result[GENERATED]
    parse_all(result)


@pytest.mark.parametrize("account", [None, "", "123", "not-an-account", 111122223333])
def test_role_creation_requires_an_explicit_valid_world_account(account: object) -> None:
    files = {"terraform/main.tf": SOURCE}
    with pytest.raises(PatchError, match="account"):
        render_files(files, [op("add_role")], account=account)
    assert files == {"terraform/main.tf": SOURCE}


def test_role_trust_names_exact_declared_users_and_roles_and_keeps_creation_dependencies() -> None:
    result = render(
        {"terraform/main.tf": SOURCE},
        [
            op(
                "add_role",
                name="new",
                trust_principals=["role:github-deploy", "user:priya-intern"],
                statements=[],
            )
        ],
    )
    text = result[GENERATED]
    assert (
        '"AWS" = ["arn:aws:iam::111122223333:role/github-deploy", '
        '"arn:aws:iam::111122223333:user/priya-intern"]'
    ) in text
    assert "depends_on = [aws_iam_role.deploy, aws_iam_user.priya]" in text
    assert ".arn" not in text
    parse_all(result)


def test_role_address_hashes_the_op_with_sorted_trust_principals() -> None:
    principals = ["user:priya-intern", "role:github-deploy"]
    results = [
        render(
            {"terraform/main.tf": SOURCE},
            [op("add_role", name="new", trust_principals=order, statements=[STATEMENT])],
        )
        for order in (principals, sorted(principals))
    ]
    assert results[0] == results[1]
    # The same label the cloud adapter gives the role on the graph copy: a hash of the sorted op.
    canonical = op("add_role", name="new", trust_principals=sorted(principals), statements=[STATEMENT])
    payload = json.dumps(canonical.model_dump(), sort_keys=True, separators=(",", ":"))
    label = "theseus_add_role_" + hashlib.sha256(payload.encode()).hexdigest()[:12]
    assert f'resource "aws_iam_role" "{label}"' in results[0][GENERATED]


def test_nonroot_principal_paths_are_refused_instead_of_disagreeing_with_engine_arns() -> None:
    text = SOURCE.replace('name = "priya-intern"', 'name = "priya-intern"\n path = "/staff/"', 1)
    with pytest.raises(PatchError, match="path"):
        render({"terraform/main.tf": text}, [op("add_role")])


def test_composition_root_supplies_its_world_account_to_the_renderer(tmp_path: Path) -> None:
    from theseus.cli import adapters_for

    (tmp_path / "theseus.yaml").write_text('account: "444455556666"\nregion: eu-west-1\n')
    result = adapters_for(tmp_path).iac.render({"terraform/main.tf": SOURCE}, [op("add_role")])
    assert '"arn:aws:iam::444455556666:user/priya-intern"' in result[GENERATED]
    assert ACCOUNT not in result[GENERATED]


def test_terraform_templates_in_literal_arguments_are_escaped() -> None:
    result = render(
        {"terraform/main.tf": SOURCE},
        [
            op(
                "set_statement_resources",
                policy_address="aws_iam_role_policy.read",
                sid="Read",
                resources=["literal/${not_code}/%{not_code}"],
            )
        ],
    )
    assert "$${not_code}" in result["terraform/main.tf"] and "%%{not_code}" in result["terraform/main.tf"]
    parse_all(result)


@pytest.mark.parametrize(
    "case",
    [
        PatchOp(provider="other", op="remove_membership", args=CASES["remove_membership"]),
        PatchOp(provider="aws", op="delete_everything"),
        op("remove_statement", policy_address="aws_iam_role_policy.missing", sid="Read"),
        op("remove_statement", policy_address="aws_iam_role_policy.read", sid="Missing"),
        op("remove_statement", policy_address="aws_iam_role_policy.read[0]", sid="Read"),
        op("set_oidc_sub", role="missing", patterns=["narrow"]),
        op("add_role", name="github-deploy", trust_principals=["user:priya-intern"], statements=[STATEMENT]),
        op("add_role", name="new", trust_principals=["user:missing"], statements=[STATEMENT]),
        op("add_policy", principal="user:missing", statements=[STATEMENT]),
        PatchOp(provider="aws", op="remove_membership", args={"user": "priya-intern"}),
        op("set_statement_resources", policy_address="aws_iam_role_policy.read", sid="Read", resources="bad"),
    ],
)
def test_unverifiable_ops_raise_patch_error_and_leave_input_untouched(case: PatchOp) -> None:
    files = {"terraform/main.tf": SOURCE}
    before = deepcopy(files)
    with pytest.raises(PatchError):
        render(files, [case])
    assert files == before


@pytest.mark.parametrize(
    "text",
    [
        SOURCE + SOURCE,
        SOURCE.replace('Sid = "Keep"', 'Sid = "Read"'),
        SOURCE.replace('Resource = "*"', 'Resource = "*" Resource = "other"'),
        SOURCE.replace('resource "aws_iam_user"', 'resource "unterminated'),
    ],
)
def test_ambiguous_or_invalid_source_is_refused(text: str) -> None:
    with pytest.raises(PatchError):
        render({"terraform/main.tf": text}, [op("set_statement_resources")])


def test_a_later_failure_does_not_leak_an_earlier_edit() -> None:
    files = {"terraform/main.tf": SOURCE}
    with pytest.raises(PatchError):
        render(
            files,
            [op("set_statement_resources"), op("remove_statement", policy_address="missing", sid="Read")],
        )
    assert files["terraform/main.tf"] == SOURCE


def test_the_real_b_k_u_handoffs_touch_only_the_intended_files() -> None:
    def sources(path: Path) -> dict[str, str]:
        return {
            p.relative_to(path).as_posix(): p.read_text() for p in sorted((path / "terraform").glob("*.tf"))
        }

    head = sources(ROOT / "fixtures" / "intern" / "head")
    logs = {
        "sid": "ReadLogs",
        "effect": "Allow",
        "actions": ["s3:GetObject", "s3:ListBucket"],
        "resources": ["arn:aws:s3:::demo-app-logs", "arn:aws:s3:::demo-app-logs/*"],
    }
    b = render(head, [op("remove_membership"), op("add_role", **{**CASES["add_role"], "statements": [logs]})])
    assert {p for p in b if b[p] != head.get(p)} == {"terraform/people.tf", GENERATED}
    world = sources(ROOT / "demo-infra")
    k = render(world, [op("set_oidc_sub")])
    assert {p for p in k if k[p] != world.get(p)} == {"terraform/ci.tf"}
    u = render(
        world,
        [op("remove_statement", policy_address="aws_iam_role_policy.support_portal", sid="LegacyDbSecret")],
    )
    assert {p for p in u if u[p] != world.get(p)} == {"terraform/services.tf"}
    for result in (b, k, u):
        parse_all(result)


@pytest.mark.parametrize(
    "statement", ['{ Sid = "Read" Resource = "*" }', '[{ Sid = "Read" Resource = "*" },]']
)
def test_removing_the_only_statement_leaves_an_empty_list(statement: str) -> None:
    text = 'resource "aws_iam_policy" "only" { policy = jsonencode({ Statement = ' + statement + " }) }\n"
    result = render(
        {"terraform/main.tf": text},
        [op("remove_statement", policy_address="aws_iam_policy.only", sid="Read")],
    )
    assert "Statement = []" in result["terraform/main.tf"]
    parse_all(result)


def test_oidc_edits_reject_other_issuers_instead_of_changing_their_trust() -> None:
    text = SOURCE.replace(
        "oidc-provider/token.actions.githubusercontent.com", "oidc-provider/accounts.google.com"
    )
    with pytest.raises(PatchError):
        render({"terraform/main.tf": text}, [op("set_oidc_sub")])


def test_oidc_provider_references_are_verified_from_declared_url() -> None:
    text = SOURCE.replace(
        '"arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"',
        "aws_iam_openid_connect_provider.github.arn",
    )
    text += (
        '\nresource "aws_iam_openid_connect_provider" "github" {\n'
        '  url = "https://token.actions.githubusercontent.com"\n}\n'
    )
    result = render({"terraform/main.tf": text}, [op("set_oidc_sub")])
    assert "repo:demo-org/*" not in result["terraform/main.tf"]
    parse_all(result)


@pytest.mark.parametrize("key", ["(var.subject_key)", '"${var.subject_key}"'])
def test_oidc_dynamic_condition_keys_are_refused_without_reinterpreting_them(key: str) -> None:
    text = SOURCE.replace('"token.actions.githubusercontent.com:sub"', key)
    files = {"terraform/main.tf": text}
    with pytest.raises(PatchError):
        render(files, [op("set_oidc_sub")])
    assert files == {"terraform/main.tf": text}


@pytest.mark.parametrize("operation", ["set_statement_resources", "set_oidc_sub"])
def test_a_parseable_but_unapplied_edit_fails_semantic_verification(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    import importlib

    module = importlib.import_module("theseus.adapters.terraform.render")
    monkeypatch.setattr(module, "_replace", lambda *args: None)
    files = {"terraform/main.tf": SOURCE}
    with pytest.raises(PatchError, match="verification"):
        render(files, [op(operation)])
    assert files["terraform/main.tf"] == SOURCE


def test_generated_blocks_preserve_an_existing_fix_file_and_reject_duplicates() -> None:
    files = {"terraform/main.tf": SOURCE, GENERATED: "# Earlier reviewed fixes stay here.\n"}
    result = render(files, [op("add_role")])
    assert result[GENERATED].startswith(files[GENERATED])
    with pytest.raises(PatchError):
        render(result, [op("add_role")])


def test_public_bucket_narrowing_preserves_principal_and_access_block_settings() -> None:
    root = ROOT / "fixtures" / "public-bucket" / "head"
    files = {p.relative_to(root).as_posix(): p.read_text() for p in (root / "terraform").glob("*.tf")}
    result = render(
        files,
        [
            op(
                "set_statement_resources",
                policy_address="aws_s3_bucket_policy.company_files_public",
                sid="PublicRead",
                resources=["arn:aws:s3:::demo-company-files/public/*"],
            )
        ],
    )
    assert result["terraform/data.tf"] == files["terraform/data.tf"].replace(
        '"arn:aws:s3:::demo-company-files/*"', '["arn:aws:s3:::demo-company-files/public/*"]'
    )
    assert result["terraform/platform.tf"] == files["terraform/platform.tf"]
    parse_all(result)


@pytest.mark.parametrize(
    "condition",
    [
        {"op": "StringEquals", "key": "aws:username", "value": "priya-intern"},
        {"op": "StringLike", "key": "aws:PrincipalArn", "value": ["arn:aws:iam::111122223333:user/*"]},
    ],
)
def test_added_policy_conditions_preserve_the_typed_catalog(condition: dict[str, object]) -> None:
    statement = {**STATEMENT, "condition": condition}
    result = render(
        {"terraform/main.tf": SOURCE},
        [op("add_policy", principal="user:priya-intern", statements=[statement])],
    )
    assert f'"{condition["op"]}"' in result[GENERATED]
    assert f'"{condition["key"]}"' in result[GENERATED]
    parse_all(result)


@pytest.mark.parametrize("path", ["../terraform/main.tf", "/tmp/main.tf", "C:/tmp/main.tf"])
def test_source_paths_cannot_escape_the_world_root(path: str) -> None:
    with pytest.raises(PatchError):
        render({path: SOURCE}, [])


def test_multiple_membership_declarations_are_updated_without_losing_other_groups() -> None:
    text = (
        SOURCE
        + '\nresource "aws_iam_user_group_membership" "second" {\n'
        + '  user = "priya-intern"\n  groups = ["support-engineers"]\n}\n'
    )
    result = render({"terraform/main.tf": text}, [op("remove_membership")])
    assert 'groups = ["other"]' in result["terraform/main.tf"]
    assert '"second"' not in result["terraform/main.tf"]
    parse_all(result)


def test_unresolved_policy_and_counted_declarations_are_refused() -> None:
    for text in [
        SOURCE.replace("policy = jsonencode({", "policy = local.policy\nignored = jsonencode({"),
        SOURCE.replace('  role = "github-deploy"', '  count = 2\n  role = "github-deploy"'),
    ]:
        with pytest.raises(PatchError):
            render({"terraform/main.tf": text}, [op("set_statement_resources")])


def test_dictionary_order_does_not_change_rendered_output() -> None:
    a = {"terraform/main.tf": SOURCE, "terraform/z.tf": "# Keep unchanged\n"}
    assert render(a, [op("add_role")]) == render(dict(reversed(list(a.items()))), [op("add_role")])


@pytest.mark.parametrize("operation", ["add_role", "add_policy", "add_membership"])
def test_generated_resources_do_not_guess_an_aliased_provider(operation: str) -> None:
    text = SOURCE.replace(
        'resource "aws_iam_user" "priya" {', 'resource "aws_iam_user" "priya" { provider = aws.other\n'
    )
    with pytest.raises(PatchError):
        render({"terraform/main.tf": text}, [op(operation)])


def test_removing_the_last_statement_preserves_the_previous_statements_comment() -> None:
    text = """resource "aws_iam_policy" "shared" {
  policy = jsonencode({Statement = [
    {Sid = "Keep" Resource = "safe"}, # Keep this audit note.
    {Sid = "Remove" Resource = "unsafe"}
  ]})
}
"""
    result = render(
        {"terraform/main.tf": text},
        [op("remove_statement", policy_address="aws_iam_policy.shared", sid="Remove")],
    )
    assert "# Keep this audit note." in result["terraform/main.tf"]
    parse_all(result)


def test_quoted_arguments_use_terraform_escapes_for_control_characters() -> None:
    resources = ["control\bone", "control\ftwo", r"literal\backslash", "unicode-😀"]
    result = render(
        {"terraform/main.tf": SOURCE},
        [
            op(
                "set_statement_resources",
                policy_address="aws_iam_role_policy.read",
                sid="Read",
                resources=resources,
            )
        ],
    )
    assert r"\u0008" in result["terraform/main.tf"]
    assert r"\u000c" in result["terraform/main.tf"]
    assert r"literal\\backslash" in result["terraform/main.tf"]
    assert "unicode-😀" in result["terraform/main.tf"]
    parse_all(result)


DEMO_LOGS = {
    "sid": "ReadLogs",
    "effect": "Allow",
    "actions": ["s3:GetObject", "s3:ListBucket"],
    "resources": ["arn:aws:s3:::demo-app-logs", "arn:aws:s3:::demo-app-logs/*"],
}
DEMO_CASES = {
    "remove_membership": {"user": "sam-support", "group": "support-engineers"},
    "remove_statement": {"policy_address": "aws_iam_policy.data_lake_curated_read", "sid": "ReadCurated"},
    "set_statement_resources": {
        "policy_address": "aws_iam_role_policy.prod_support_read",
        "sid": "ReadInvoices",
        "resources": ["arn:aws:s3:::demo-company-files/invoices/2026/*"],
    },
    "set_oidc_sub": CASES["set_oidc_sub"],
    "add_membership": {"user": "priya-intern", "group": "support-engineers"},
    "add_policy": {"principal": "user:priya-intern", "statements": [DEMO_LOGS]},
    "add_role": {
        "name": "intern-onboarding",
        "trust_principals": ["user:priya-intern"],
        "statements": [DEMO_LOGS],
    },
}


@pytest.mark.parametrize("operation", sorted(DEMO_CASES))
def test_every_operation_on_demo_infra_has_a_reviewable_diff_snapshot(operation: str) -> None:
    import difflib

    root = ROOT / "demo-infra"
    files = {p.relative_to(root).as_posix(): p.read_text() for p in sorted((root / "terraform").glob("*.tf"))}
    result = render(files, [op(operation, **deepcopy(DEMO_CASES[operation]))])
    diff = "".join(
        "".join(
            difflib.unified_diff(
                files.get(path, "").splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile=path,
                tofile=path,
            )
        )
        for path, text in result.items()
        if text != files.get(path)
    )
    assert diff == (SNAPSHOTS / f"demo_{operation}.diff").read_text()
    parse_all(result)


def test_the_api_supplies_its_world_account_to_the_renderer() -> None:
    """Fixes render through the API too (A9), so its adapters carry the world's account like the CLI's."""
    from theseus.api.app import adapters_for

    result = adapters_for({"account": "444455556666", "region": "eu-west-1"}).iac.render(
        {"terraform/main.tf": SOURCE}, [op("add_role")]
    )
    assert '"arn:aws:iam::444455556666:user/priya-intern"' in result[GENERATED]
