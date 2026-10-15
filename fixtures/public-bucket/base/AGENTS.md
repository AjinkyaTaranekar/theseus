# demo-infra/AGENTS.md

This folder is a made-up company's AWS account and backend. Nothing here is real, and nothing here is ever applied
to a real account or pushed to a real org. Only tasks F4 and C1 change it; other tasks read it.

- **Spec 02 is the source of truth.** Every address, name, Sid, ARN, environment variable and workflow line must
  match `docs/spec/02-demo-world.md` exactly. If you need something it does not list, ask first.
- **Literal names and ARNs only** in the modeled files (`people.tf` to `containers.tf`). Never
  `aws_iam_role.x.arn`: without real state, plan marks it unknown. No `data` blocks, no `backend` block.
- **Modeled and skipped resources stay in separate files.** `network.tf` and `platform.tf` hold only types the
  importer skips, so adding to them never moves a line in a modeled file.
- **Moving a line in a modeled file breaks every `expected.json` that cites it.** If you must, say so in the PR
  so both humans update the cites, then run `python tools/make_fixture.py all`. Never edit `expected.json`.
- **Services:** read each environment variable at module level in the module that uses it, create clients with
  `boto3.client("<service>")`, no constants imported across modules, no `boto3.resource`. The code reader resolves
  only these forms (`docs/spec/04-engine.md` section 7). No tests in this folder.
- **Workflows in `workflows/demo-org/` are files to read, not to run.** Never copy them into `.github/workflows/`.
- **Check after every change:** `tools/plan.sh demo-infra/terraform /tmp/main.plan.json` succeeds with no AWS
  account, and no modeled field appears in `after_unknown`.
