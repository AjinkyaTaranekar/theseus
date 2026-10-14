# 04. Engine rules

Everything here is deterministic. Given the same inputs, the result is the same, in the same order.

## 1. Inputs

A **world** is one state of the infrastructure. `theseus/importer/world.py: load_world()` assembles it from a
**world root**: `demo-infra/` in the repo, or `base/` and `head/` in a fixture. Both have the layout in `02-demo-world.md`.

| Part | Where it comes from |
| --- | --- |
| Plan JSON | `terraform show -json` output (`base.plan.json` or `head.plan.json`) |
| Terraform source | `terraform/` under the world root at the same commit, used only to find file and line |
| Workflow files | `workflows/<org>/<repo>/<file>` under the world root: the org's workflows, kept as files |
| Service code | `services/<folder>/*.py` under the world root at the same commit |
| Config | `theseus.yaml` at the world root |

**Modeled resource types.** `aws_iam_user`, `aws_iam_group`, `aws_iam_user_group_membership`,
`aws_iam_user_policy`, `aws_iam_group_policy`, `aws_iam_role`, `aws_iam_role_policy`, `aws_iam_policy`,
`aws_iam_user_policy_attachment`, `aws_iam_group_policy_attachment`, `aws_iam_role_policy_attachment`,
`aws_iam_openid_connect_provider`, `aws_s3_bucket`, `aws_s3_bucket_policy`, `aws_secretsmanager_secret`,
`aws_db_instance`, `aws_dynamodb_table`, `aws_lambda_function`, `aws_ecs_task_definition`, `aws_ecs_service`.
Every other type is skipped and counted by type in the result's `coverage`; it never adds a node or an edge.

## 2. Reading the plan (`importer/plan.py`)

- Resources come from `planned_values.root_module.resources`, plus `child_modules` recursively.
  Each becomes `{address, type, name, values}`.
- A field listed as `true` in `resource_changes[].change.after_unknown` is **unknown until apply**. Only fields
  the importer reads count (names, policy documents, trust policies, `role`, `policy_arn`, group lists, tags,
  `environment`, `task_role_arn`, `container_definitions`, `task_definition`, `bucket`); other unknown fields,
  such as a subnet ID, are ignored. Record `{address, field, references}`, taking `references` from `configuration.root_module.resources[].expressions[field].references`.
- When a field is unknown but its reference names another resource's `name` or `id` (for IAM, the name), resolve
  it to that resource's configured name. Otherwise leave it unknown.
- An IAM policy whose `policy` value is unknown is treated as `Allow * on *` with an unsupported condition, so
  every edge it would create has kind `unknown`. It is listed in the result's `unknowns`.

## 3. Evidence lines (`importer/source_index.py`)

Plan JSON has no line numbers. For each resource, find the line matching
`^\s*resource\s+"<type>"\s+"<name>"` in the `.tf` files. When a statement Sid is known, return the line of
`Sid = "<sid>"` inside that block instead. If nothing matches, `file` is `"unknown"` and `line` is null. Never
guess a line. Files are relative to the world root (`terraform/roles.tf`), so fixtures and the repo agree; the
comment renderer adds the world root (`demo-infra/`) when it links to GitHub.

## 4. ARNs

When a value is missing or unknown, the importer builds the canonical ARN:

| Kind | ARN |
| --- | --- |
| user, group, role | `arn:aws:iam::<account>:<kind>/<name>` |
| s3 location | `arn:aws:s3:::<bucket>/<prefix>x`, a representative object key under the prefix |
| secret | `arn:aws:secretsmanager:<region>:<account>:secret:<name>-AbCdEf` (AWS adds a 6-character suffix) |
| db | `arn:aws:rds:<region>:<account>:db:<identifier>` |
| dynamodb table | `arn:aws:dynamodb:<region>:<account>:table/<name>` |
| customer-managed policy | `arn:aws:iam::<account>:policy/<name>` |

## 5. The IAM subset (`importer/iam.py`)

**Supported:** `Allow` and `Deny`; `Action` and `Resource` as a string or list; wildcards (`*` matches any
run of characters including `/` and `:`; `?` matches one; case-insensitive); account-root and explicit-ARN
trust; GitHub OIDC trust on `aud` and `sub` under `StringEquals` and `StringLike`.

**Unsupported, so UNKNOWN:** any other `Condition`; `NotAction`, `NotResource`, `NotPrincipal`; permission
boundaries; SCPs; KMS key policies; resource policies other than S3 bucket policies.

**A principal's statements** are its inline policies (`aws_iam_user_policy`, `aws_iam_group_policy`,
`aws_iam_role_policy`), plus every attached customer-managed policy (a `*_policy_attachment` whose `policy_arn`
names an `aws_iam_policy` in the plan), plus AWS-managed policies listed in `importer/aws_managed.py`. That table
holds `AWSLambdaBasicExecutionRole` and `AmazonECSTaskExecutionRolePolicy`, neither with a modeled action. Any
other AWS-managed ARN, or a customer ARN not in the plan, counts as an unknown policy (section 2). A group's
statements are evaluated on the group; its members reach them through `MEMBER_OF`.

**`evaluate(statements, action, arn)`** returns one of:

| Result | When |
| --- | --- |
| `deny` | An unconditional matching `Deny` exists |
| `allow` | An unconditional matching `Allow` exists, and no conditional `Deny` or unsupported statement could match |
| `unknown` | A matching `Allow` exists only with a condition, or alongside a conditional `Deny` or an unsupported statement |
| `none` | Nothing matches |

It also returns the statements that decided it; those become the edge's evidence.

**Modeled actions and the access they grant:**

| Action | Access | Applies to |
| --- | --- | --- |
| `s3:GetObject` | read | s3 locations |
| `s3:PutObject`, `s3:DeleteObject` | write | s3 locations |
| `secretsmanager:GetSecretValue` | read | secrets |
| `dynamodb:GetItem`, `dynamodb:BatchGetItem`, `dynamodb:Query`, `dynamodb:Scan` | read | DynamoDB tables |
| `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:DeleteItem`, `dynamodb:BatchWriteItem` | write | DynamoDB tables |
| `sts:AssumeRole` | assume | roles |

`s3:ListBucket` is not modeled: listing keys is not reading data. Control-plane actions (`iam:*`,
`dynamodb:CreateTable`, `s3:PutBucket*` and the like) are not modeled either: they change infrastructure, not
data, and privilege escalation through IAM writes is out of scope. A table node's ARN is the table ARN, so a
statement on `table/<name>/index/*` alone does not reach it.

**Trust (`trust_kind`).** For a role's trust policy and a caller ARN, return `explicit` (the caller's ARN is
named), `account` (the account root or account ID is named), `unknown` (it would match but has a condition),
or none. `Principal = "*"` counts as `account` when unconditional.

## 6. Edge derivation (`importer/build.py` and friends)

| Edge | Rule |
| --- | --- |
| `MEMBER_OF` | One per group listed in each `aws_iam_user_group_membership` |
| `CAN_ASSUME` | For every principal P and role R (P not R): `d = evaluate(P's statements, sts:AssumeRole, R.arn)`; `t = trust_kind(R's trust, P.arn)` (for a group, use the account form). No edge if `d` is `deny` or `t` is none, or if `d` is `none` and `t` is not `explicit`. Kind `unknown` if either is unknown |
| `CAN` | For every principal with statements, every resource, every modeled action that applies to that resource kind: `allow` makes a configured edge, `unknown` an unknown one. Grants of the same principal and resource merge into one edge. Evidence for a statement in an attached policy names the `aws_iam_policy` and Sid, with note `attached by <attachment address>` |
| `CAN` from `entry:internet` | From `aws_s3_bucket_policy` statements whose principal is `"*"` or `{"AWS": "*"}`, evaluated like identity statements against the bucket's locations |
| `UNLOCKS` | From a secret to `db:<tag value>` when the secret has tag `db_instance` and that database exists. Grants read and write. Kind inferred |
| `RUNS_AS` | From `workload:<function name>` to the role named by `aws_lambda_function.role` (ARN or name). From `workload:<ECS service name>` to the role named by `task_role_arn` of the `aws_ecs_task_definition` whose `family` the service's `task_definition` names (`family` or `family:revision`). An ECS `execution_role_arn` is never a workload's identity |
| `USES` | One per `uses: owner/repo@version` line in a workflow, to `action:owner/repo` |
| `TRUSTS` | Only for workflows with `id-token: write` (top-level, job-level, or `write-all`). For each OIDC trust statement on each role, test every `sub` the workflow can present. `yes` or `yes-any-repo` makes a configured edge; `unknown` an unknown edge |
| `CALLS`, `REQUESTS`, `HAS_ENV` | From service code, section 7 |
| `FOR`, `NEEDS` | One requirement node per requirement, from `theseus.yaml` and from the PR's intent |

**Workflow `sub` values** (`importer/workflows.py`), per job that can request an ID token: a job with
`environment: X` presents only `repo:<org>/<repo>:environment:X`, as GitHub does. Otherwise a `push` trigger
gives `repo:<org>/<repo>:ref:refs/heads/<branch>` per listed branch (default `main`), and `pull_request` or
`pull_request_target` gives `repo:<org>/<repo>:pull_request`. The workflow's `subs` is the sorted union over its
jobs.

**OIDC matching** (`importer/oidc.py`): every condition key must be `token.actions.githubusercontent.com:aud`
or `:sub`, under `StringEquals` (exact) or `StringLike` (wildcards); anything else is `unknown`. `aud` must
accept `sts.amazonaws.com`. Any failing test is `no`. If no `sub` test exists, the result is `yes-any-repo`.

**Duplicate edges.** One edge per (source, target, type); merge grants and evidence. If any part is unknown,
the merged edge is unknown.

## 7. Reading service code (`importer/code.py`)

Parse each `services/<folder>/*.py` with Python's `ast`; never execute it. The workload is the Lambda function
or ECS service whose `theseus_code_path` tag names that folder. A folder no workload claims is skipped with an
entry in `unknowns`. Environment variables come from that workload's Terraform: the Lambda's `environment` block,
or the first container's `environment` in its ECS task definition.

| Pattern | Edge |
| --- | --- |
| `<client>.put_object(Bucket=X, Key=K)` on an `s3` client | `CALLS` `s3:PutObject`, access write, to the s3 location whose bucket is X and whose prefix is the longest literal prefix of K |
| `<client>.get_object(...)` | Same, access read |
| `<client>.get_item`, `.batch_get_item`, `.query`, `.scan` (`TableName=X`) on a `dynamodb` client | `CALLS` with that action, access read, to `dynamodb:X` |
| `<client>.put_item`, `.update_item`, `.delete_item`, `.batch_write_item` (`TableName=X`) on a `dynamodb` client | `CALLS`, access write, to `dynamodb:X` |
| `<client>.get_secret_value(SecretId=X)` on a `secretsmanager` client | `CALLS` `secretsmanager:GetSecretValue`, access read, to `secret:X` |
| `psycopg.connect(...)`, `psycopg2.connect(...)`, `sqlalchemy.create_engine(...)` in a workload that also calls a secret which `UNLOCKS` a database | `CALLS` `db:connect`, access read, to that database |
| `httpx.<method>(URL...)` or `requests.<method>(URL...)` where URL starts with a value whose host's first label is another workload's name | `REQUESTS` to that workload. Any other host makes no edge |
| `os.environ["V"]` or `os.getenv("V")` | Resolve V through the workload's environment; also emit `HAS_ENV` (`var` = V) to the node the value names: a secret, a table, a workload (by URL host), or every location of a bucket |
| A call on a client of a service Theseus does not model (`sqs`, `sns`, `events` and so on) | No edge. Counted in `coverage.code_calls_skipped` |

A client is any name assigned from `boto3.client("<service>")`, in the function or at module level. A value
resolves when it is a string literal; `os.environ["V"]` or `os.getenv("V")`; a module-level name assigned exactly
once in the same file from a value that resolves; or an f-string or `+` concatenation whose first part resolves
(the rest becomes `*`). Names imported from another module do not resolve. A value that cannot be resolved
produces no edge; record it in `unknowns` as `"code: <file>:<line> <call> target unresolved"`.

## 8. Sensitivity and environments

- Jev classifies every `Resource` node as `public`, `internal`, `confidential` or `regulated` (prompt in
  `06-agent.md`). `sensitive_overrides` in `theseus.yaml` always wins. `sensitive` is true for
  `confidential` and `regulated`. With no label, `sensitivity_source` is `unclassified` and `sensitive` is false.
- `env` is `staging` for nodes listed under `environments.staging` in `theseus.yaml`, otherwise `prod`.

## 9. Paths

- **Actors:** users, workflows, workloads and `entry:internet`. In finding mode, only the matched workflows or workloads.
- **A valid path** is a simple path (no node twice) of at most 7 edges: zero or more traversal edges
  (`MEMBER_OF`, `CAN_ASSUME`, `TRUSTS`, `RUNS_AS`), then `CAN` to a resource, optionally followed by `UNLOCKS`
  when that resource is a secret.
- **Path record:** actor, target, grants (of the last edge), route (node IDs), edge IDs, `unknown` (any edge
  unknown), `inferred` (any edge inferred), and whether the target is sensitive.

## 10. Requirements, coverage and dangerous paths

- **Requirements** come from `theseus.yaml` (`R1`...) and from the PR's intent (`I1`...). Each is (principal, access, resource).
- **Status:** `satisfied` if a path from the principal reaches the resource with that access and no unknown
  edge; `unknown` if only unknown paths do; `missing` otherwise. Access `assume` is satisfied by any traversal
  path that reaches the role.
- **Coverage:** for an actor, a resource is covered if one of its requirements names it, or if it sits on the
  route of a path that satisfies one (a secret on the way to a required database).
- **Dangerous path:** a path whose target is sensitive and not covered. Keyed by (actor, target).

## 11. Diff (PR mode)

Analyze base and head with the same actors and the same requirements (config plus intent). With keys
(actor, target): `opened` = head minus base, `closed` = base minus head, `unchanged` = both.

## 12. Capacities and the minimum cut (`engine/mincut.py`)

| Capacity | Edges |
| --- | --- |
| `BIG` = 1,000,000 | Every edge on a path that satisfies a requirement (config or intent); every `RUNS_AS`, `UNLOCKS` and `USES` edge (not permissions) |
| `USED` = 1,000 | A `CAN` edge from a role to a resource when a workload running as that role has a `CALLS` edge to that resource with an access the edge grants (task C3) |
| 1 | Every other edge |

- **Sources:** the actor (PR and scan modes), or every matched workflow (finding mode).
- **Sinks:** that actor's dangerous targets in the analyzed graph.
- **Value at least `BIG`** means no cut keeps every requirement: `cuttable` is false and the agent must design a
  structural fix.
- **The cut:** after max flow, walk the residual graph from the sources (forward capacity minus flow above zero,
  or flow above zero on a reverse step). The cut is every edge from a reached node to an unreached one. Report
  each with its evidence.
- `algo.maxFlow` returns flows, not the cut; compute the cut from those flows. If the call is unavailable, run
  Edmonds-Karp in Python on the same edges and capacities.

## 13. Patch ops (`engine/patch.py`)

Candidate fixes are lists of ops applied to a copy of the head resources. Rules and Claude use the same catalog.

| Op | Fields | Effect |
| --- | --- | --- |
| `remove_membership` | `user`, `group` | Removes the group from the user's membership resources; drops a membership resource left empty |
| `add_membership` | `user`, `group` | Adds a membership resource |
| `remove_statement` | `policy_address`, `sid` | Removes the statement with that Sid. The address may be an inline policy or an `aws_iam_policy`; editing a shared policy changes every principal it is attached to, and the simulation shows that |
| `set_statement_resources` | `policy_address`, `sid`, `resources` | Replaces that statement's `Resource` list |
| `add_policy` | `principal` (`user:`, `group:`, `role:`), `statements` | Adds an inline policy |
| `add_role` | `name`, `trust_principals` (`user:` or `role:` IDs), `statements` | Adds a role trusting those principals' exact ARNs, with an inline policy |
| `set_oidc_sub` | `role`, `patterns` | Replaces the role's OIDC `sub` condition with `StringLike` on these patterns |

A statement in an op: `{sid, effect, actions, resources, condition}`; `condition` is `{op, key, value}` or null.
An op that cannot apply raises `PatchError`; the candidate's verdict is then `invalid`.

## 14. Simulation and verdicts (`engine/simulate.py`)

1. `GRAPH.COPY` the head graph to the candidate graph (`..-fix-<id>`).
2. Apply the ops to a copy of the head resources and rebuild graph rows in Python.
3. Compute the delta between the head rows and the patched rows (nodes and edges, by ID and by
   (source, target, type)) and apply only that delta to the copy. Never just hide an edge.
4. Re-analyze head and candidate with the same actors and requirements.

| Verdict | When |
| --- | --- |
| `invalid` | An op raised `PatchError` |
| `fail` | A dangerous path of the actor remains, or a new dangerous path appears (certain paths only) |
| `fail` | A requirement becomes `missing` |
| `fail` | A `CALLS` edge loses its access: the code would break. The reason names the file and line |
| `unknown` | A requirement becomes `unknown`, or a remaining path is unknown |
| `pass` | Every dangerous path of the actor closed, every requirement kept, every code call kept |

## 15. Candidates and ranking (`engine/candidates.py`)

Candidate IDs are fixed by where they come from:

| ID | Source | Fix |
| --- | --- | --- |
| A | rule | Revert: remove the memberships or statements the PR added on the opened paths |
| B | Claude | A structural fix, such as a new narrower role (`06-agent.md`) |
| C | rule | A `Deny` on the role that grants the data, conditioned on the new principal. Always UNKNOWN by design: we do not model that condition |
| D | rule | Remove the statement that lets a group or role reach the role on the path |
| S | rule | Scope down: set a statement on the path that grants both required and dangerous locations to the required ones only |
| K | rule | Containment: `set_oidc_sub` on the cut role to the `sub` values of the workflows whose requirements need it |
| U | rule | Remove a grant on a dangerous path that no code calls |

Generate only the candidates that apply to the paths in hand; derive names from the graph, never hardcode them.

**Ranking** (fixed code, not model judgment):

1. Verdict `pass` before `unknown` before `fail` before `invalid`.
2. Fewer UNKNOWN steps first.
3. The smallest change: fewer ops, then fewer permissions removed.
4. No broad wildcard in an added statement.
5. Rule candidates before Claude's, then by ID.

The first `pass` is `recommended`. Jev can veto, never approve: if Jev scores "could this fix break legitimate
use?" above 0.5, the candidate is labeled "needs a closer look" and cannot be recommended. If nothing passes,
say so and show the trade-off; never pick the least bad option silently.

## 16. Finding mode (`engine/finding.py`)

1. Match the advisory's `action` and `affected_versions` to `USES` edges. Add a `Finding` node with `AFFECTS`
   to the Action. The matched workflows become actors, labeled as an assumed compromise.
2. **Blast radius:** their valid paths to sensitive resources, grouped by target.
3. **Minimum cut:** all matched workflows as sources, their dangerous targets as sinks.
4. **Containment K** for a cut `TRUSTS` edge, verified like any candidate.
5. **Rotate:** every secret any matched workflow can reach, sorted.
6. **Staging to prod:** flag every path from a staging actor to a sensitive prod resource.
7. **Choke points:** betweenness over the graph; report the top roles.

## 17. Scan mode and code checks (`engine/usage.py`)

- **Scan:** analyze `main` with every actor. For each workload, list unused grants (Q_UNUSED_GRANTS) that lie
  on a dangerous path, and propose candidate U for each, verified like any candidate.
- **Use beyond intent (PR mode):** a `CALLS` edge present in head but not base, by (workload, resource,
  access), whose resource is sensitive (or unlocks a sensitive one) and is not covered by a config or intent
  requirement. Report the workload, resource, access, file and line, and what it unlocks.

## 18. Says versus grants (`engine/intent_effect.py`)

Compare the intent's grants with the head analysis. **Grants beyond intent** are opened dangerous paths, plus
uses beyond intent. The headline:

- `Your PR says <purpose>. Your change grants <the most sensitive opened target>.`
- With no IAM change but a use beyond intent: `Your PR says <purpose>. Your code now reads <resource>.`, naming
  the most sensitive use, and a database before the secret that unlocks it.
- With nothing beyond intent: `This change matches its stated purpose.`

Pick the most sensitive target as `regulated` before `confidential`, then the shortest path, then by ID.

## 19. Writing fixes back to Terraform (`engine/render_tf.py`, task E9)

A chosen candidate becomes text edits on the `.tf` files, so `/theseus apply` can commit it.

| Op | Edit |
| --- | --- |
| `remove_membership` | Delete the whole `resource` block if the group was its only one; otherwise remove the name from `groups = [...]` |
| `remove_statement` | Delete the statement object `{ Sid = "<sid>" ... }` inside `jsonencode`, and its trailing comma |
| `set_statement_resources` | Replace the `Resource = ...` line inside that statement |
| `set_oidc_sub` | Replace the value of the `token.actions.githubusercontent.com:sub` condition line, under `StringLike` |
| `add_policy`, `add_role`, `add_membership` | Append generated blocks to `terraform/theseus_fixes.tf` under the world root (one file, so the diff is easy to review) |

Blocks are found with the same header search as `source_index.py`, and their end by brace counting. After
editing, parse the files with `python-hcl2` (pure Python) and check that the edited block now says what the op
intended. If either check fails, refuse to commit. The Action's re-run after the commit (a fresh plan and a
fresh analysis) is the final check.
