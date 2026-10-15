# The AWS adapter and its catalog

The AWS adapter turns Terraform resources into graph rows: principals and their IAM edges (code in `iam.py`,
`policies.py`, `access.py`), and data resources and workloads, which come from **[`catalog.yaml`](catalog.yaml)**.
Adding an AWS service or a kind of workload is a catalog entry, not code.

## What the catalog models

| Category | Types | Read | Write |
| --- | --- | --- | --- |
| `ObjectStorage` | `aws_s3_bucket` (one node per data location in `theseus.yaml`) | `s3:GetObject(Version)` | `s3:PutObject`, `DeleteObject(Version)` |
| `Secret` | `aws_secretsmanager_secret` | `secretsmanager:GetSecretValue` | not modeled |
| `Secret` | `aws_ssm_parameter` | `ssm:GetParameter(s)`, `GetParametersByPath` (on each ancestor path), `GetParameterHistory` | `ssm:PutParameter` |
| `Database` | `aws_dynamodb_table` | `GetItem`, `BatchGetItem`, `Query`, `Scan` | `PutItem`, `UpdateItem`, `DeleteItem`, `BatchWriteItem` |
| `Database` | `aws_db_instance` | through `UNLOCKS` from its secret | through `UNLOCKS` |
| `Database` | `aws_opensearch_domain` | `es:ESHttpGet` | `es:ESHttpPost`, `Put`, `Delete` |
| `LogStore` | `aws_cloudwatch_log_group` | `logs:FilterLogEvents`, `StartQuery`, `StartLiveTail`, `GetLogEvents` | `logs:PutLogEvents` |
| `MessageQueue` | `aws_sqs_queue` | `sqs:ReceiveMessage` | `sqs:SendMessage`, `DeleteMessage`, `PurgeQueue` |
| `MessageTopic` | `aws_sns_topic` | not modeled | `sns:Publish` |
| `DataStream` | `aws_kinesis_stream` | `kinesis:GetRecords`, `GetShardIterator` | `kinesis:PutRecord(s)` |

Workloads, each `RUNS_AS` the role the catalog says how to find: Lambda (`Function`), ECS services through their
task definition (`ComputeService`), EC2 instances through their instance profile (`ComputeInstance`), App Runner
(`ComputeService`), CodeBuild (`CICDPipeline`), Step Functions, Glue jobs, Bedrock agents and SageMaker notebooks.

The categories and labels are [Cartography's ontology
labels](https://github.com/cartography-cncf/cartography/blob/master/cartography/models/ontology/labels.py), plus
`LogStore`, `MessageQueue`, `MessageTopic` and `DataStream`, which that ontology does not cover. Cartography also
files DynamoDB and OpenSearch under `Database`.

## How the catalog is built

**Actions are chosen by hand**, the way Cartography's [permission
mapping](https://github.com/cartography-cncf/cartography/blob/master/cartography/data/permission_relationships.yaml)
does, because AWS's own access levels do not say whether an action touches data:

- AWS files metadata reads such as `s3:GetObjectAcl` and `s3:GetBucketPolicy` as reads, though they expose no
  data. Taking every read would invent paths.
- AWS files some data access as writes: `sns:Subscribe` (how a topic is read), `kms:Decrypt`, `rds-db:connect`.
  Those need a decision, not a lookup.

**Every choice is checked against AWS.** AWS publishes [machine-readable service
reference](https://docs.aws.amazon.com/service-authorization/latest/reference/service-reference.html) for every
service. `tools/aws_service_reference.py` fetches what the catalog uses into
`tests/data/aws_service_reference.json`, and `tests/contract/test_aws_catalog.py` checks, offline, that:

- every action exists;
- a read action is read-level (not a write, list, permissions or tagging action) and a write action is
  write-level;
- the action applies to the resource type the entry says;
- every ARN we build fits one of the formats AWS publishes for that resource type.

**One ARN per node, tested the way AWS tests it.** Each node has a representative ARN (`arn_pattern`): for an S3
location, `arn:aws:s3:::<bucket>/<prefix>x`, a key under the prefix. An action can name other forms with `{arn}`,
such as a log stream (`{arn}:log-stream:x`) or an OpenSearch path (`{arn}/x`). When AWS may check more than one
form, as with log groups (`log-group:NAME` and `log-group:NAME:*`), a policy that matches one form and not the
other gives `unknown`.

**An action AWS checks on a path** is marked `by_path`. `ssm:GetParametersByPath` is authorized on the path the
caller asks for, and access to `/prod` returns `/prod/db-password` even when a `Deny` names that parameter, as
the [API reference](https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_GetParametersByPath.html)
says. So it is tested on each ancestor path (`parameter/prod`, then the root `parameter/`), and whichever allows
reveals the node. AWS's ARN format has no form for the root path; the catalog test skips it, and it is kept so a
parameter at the top level is not missed.

## Fields

`data` entries:

| Field | Meaning |
| --- | --- |
| `type` | The Terraform resource type |
| `kind` | The node ID prefix: `<kind>:<name>`, or `<kind>://<path>` for an S3 location |
| `category` | One of `RESOURCE_CATEGORIES` in `contracts/schema.py` |
| `service`, `resource_type` | As in AWS's service reference; every action must belong to `service` |
| `per` | `resource` (one node per resource) or `location` (one per data location in `theseus.yaml`) |
| `name` | The value that names the node (default `name`) |
| `arn` | The ARN template: `{partition}`, `{region}`, `{account}`, `{name}`, `{name_path}` (without a leading slash), `{bucket}`, `{prefix}` |
| `read`, `write` | Actions. An entry is an action, or `{action, resource_type, arns, by_path}`; `arns` may use only `{arn}`; `by_path: true` tests the action on each ancestor path instead, and takes no `arns` |

`workloads` entries:

| Field | Meaning |
| --- | --- |
| `type`, `name` | The Terraform type and the value that names the workload (a dotted path such as `tags.Name` works) |
| `runtime` | A short lowercase word shown on the node (`lambda`, `ecs`, ...) |
| `label` | Cartography's label for it, if one fits: `Function`, `ComputeService`, `ComputeInstance`, `CICDPipeline` |
| `role.field` | The value that names the role, as an ARN or a name |
| `role.via`, `join`, `match` | When the role sits on another resource: the type (`via`), the workload's value naming it (`join`), and that resource's value it must equal (`match`). A trailing `:revision` is ignored |

## Adding a data service

1. Find the service's prefix and resource type in the [service
   reference](https://docs.aws.amazon.com/service-authorization/latest/reference/reference_policies_actions-resources-contextkeys.html),
   and its ARN format.
2. Add a `data` entry. Choose the actions that read or write **data**, not configuration or metadata. Pick the
   category from `RESOURCE_CATEGORIES`; a new one is a contract change both humans approve.
3. Run `.venv/bin/python tools/aws_service_reference.py` (Windows: `.venv\Scripts\python`). It fails if an
   action does not exist; commit the refreshed snapshot.
4. Add a case to `tests/unit/adapters/aws/test_access.py`: a role that should reach the new resource, and one
   that should not.
5. Run `pytest -q`. The catalog test checks levels and ARN formats for you.

Adding a workload type is the same, without steps 3 and 4: name its role field (or the resource it is found
through) and add a case to the catalog test.

## What is not modeled yet, and why

| Gap | Why | What it would take |
| --- | --- | --- |
| EFS, KMS keys, Bedrock knowledge bases | Their ARNs use an ID AWS generates at apply time, so a new one has no ARN at plan | Nodes named by the Terraform address, and edges to them `unknown` until the ID is known |
| `rds-db:connect` (IAM database login) | Its ARN names the instance's resource ID, unknown at plan; AWS files it as a write | The same as above, as read and write |
| SNS subscriptions as reads | Subscribing starts a delivery the endpoint must confirm | A decision on how a subscription reads a topic |
| Glue tables, Athena | `glue:GetTable` returns a schema, not data; the data is in S3, already modeled | Nothing, unless table-level grants matter |
| KMS key policies, SCPs, other resource policies | Outside the IAM subset; their types are skipped and counted | Each is a new evaluation rule |
| Network exposure (load balancers, API Gateway, CloudFront, DNS) | It is a different kind of path: internet to service, not identity to data | A `data`-like `exposure` section and a new edge type |
| Privilege escalation (`iam:PassRole`, `lambda:UpdateFunctionCode`, `ssm:SendCommand`) | Becoming another role through compute changes the path model | New traversal edges, after v1 |
