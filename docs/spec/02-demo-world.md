# 02. The demo world: `demo-infra/`

Everything here is synthetic (rule 6). The world is a small, made-up online store, and it lives in the
`demo-infra/` folder of the Theseus repo itself. There is no GitHub org, no second repo and no AWS account behind
it. Account `111122223333`, region `eu-west-1`. Names such as `demo-org`, `demo-thirdparty` or `demo-orders` are
plain strings inside files; nothing is registered anywhere, so nothing can clash with a real name.

Task F4 writes the modeled Terraform, the workflows, `theseus.yaml` and the fixture generator. Task C1 writes the
service code and the infrastructure Theseus does not model. Task F5 (humans) writes each `expected.json`.

## The company in one paragraph

Customers place orders on the website. **orders-api** (a container on ECS) checks the customer with
**billing-api**, stores the order in the DynamoDB table `demo-orders`, and queues an event. **orders-worker** (ECS)
takes the event and marks the order fulfilled. Every night **billing-job** (Lambda) turns fulfilled orders into
invoice PDFs in `demo-company-files/invoices/` and charges the card with the payment provider's key.
**billing-api** (Lambda) serves invoices and customer records from the Postgres database `customer-db`.
**support-portal** (Lambda) is the support team's internal tool; it asks billing-api and orders-api over HTTP.
Every night **analytics-export** (Lambda) dumps orders into the data lake's `raw/` zone and writes daily aggregates
to `curated/`, which the analysts read. Sam works in support, Alex is an analyst, Jordan runs the platform, and
Priya, an intern, joins support this week.

## Layout

```
demo-infra/
├── README.md                     the company, the map below, and "nothing here is real"     F4
├── theseus.yaml                  account, data locations, environments, requirements         F4
├── terraform/
│   ├── providers.tf              AWS provider with mock credentials and skip flags            F4
│   ├── people.tf                 users, groups, memberships, group policies and attachments   F4
│   ├── roles.tf                  roles people assume: prod-support, analytics-read            F4
│   ├── policies.tf               customer-managed policies shared by several principals       F4
│   ├── ci.tf                     GitHub OIDC provider, github-deploy, terraform-apply          F4
│   ├── data.tf                   buckets, secrets, the database, the orders table              F4
│   ├── services.tf               Lambda functions and their roles                              F4
│   ├── containers.tf             ECS cluster, task definitions, services and task roles        F4
│   ├── queues.tf                 SQS queues and the SNS topic                                  C1
│   ├── logs.tf                   one CloudWatch log group per workload                         C1
│   ├── network.tf                VPC, subnets, security groups (not modeled)                   C1
│   └── platform.tf               KMS, ECR, schedules, DNS, API, bucket settings (not modeled)  C1
├── services/                     one folder per workload, several modules each                 C1
│   ├── orders_api/               app.py, store.py, events.py, billing.py
│   ├── orders_worker/            worker.py, fulfil.py
│   ├── billing_job/              handler.py, invoices.py, payments.py
│   ├── billing_api/              handler.py, db.py, queries.py
│   ├── support_portal/           handler.py, clients.py, views.py
│   └── analytics_export/         handler.py, export.py
└── workflows/demo-org/           the org's workflows, as files; GitHub never runs them         F4
    ├── infra/deploy.yml, infra/ci.yml
    ├── docs-site/preview.yml
    └── website/lint.yml
```

A fixture side (`fixtures/<scenario>/base/`) has exactly this layout, so the importer reads `demo-infra/` and a
fixture the same way.

## Conventions

- **Literal names and ARNs only** in every modeled resource: never `aws_iam_role.x.arn`. Without real state,
  `terraform plan` cannot know computed attributes and would mark the whole policy unknown. The importer still
  handles unknown values (it reports UNKNOWN); the demo world simply avoids them. The skipped files
  (`network.tf`, `platform.tf`) may use Terraform references such as `aws_s3_bucket.app_logs.bucket`: the importer
  never reads their types, and the references let a scanner such as Checkov tie a bucket to its settings.
- **No `data` blocks and no `backend` block.** Data sources call AWS during plan; a backend needs `init`.
  The provider uses mock credentials and skips every AWS call (`skip_credentials_validation`,
  `skip_requesting_account_id`, `skip_metadata_api_check`), so `terraform plan` runs without an account. P1 confirmed
  it for one resource of every type in this file, with Terraform 1.16.6 and AWS provider 6.69.0; pin
  `version = "~> 6.69"` in `providers.tf`.
- **Modeled and not-modeled resources live in different files.** `network.tf` and `platform.tf` hold only types
  Theseus skips, so they grow without moving a line that an `expected.json` cites. `queues.tf` and `logs.tf` hold
  only modeled types; C1 added them as new files, so they moved no existing line either.
- **`theseus_code_path` tag** on every Lambda function and ECS service names its folder under `services/`.
- **Buckets use SSE-S3**, not KMS, so reading them needs no `kms:Decrypt`. KMS key policies are outside the
  supported IAM subset, and the demo stays inside it.
- **Every service reads its own environment variables** at module level in the module that uses them, and creates
  its boto3 clients with `boto3.client("<service>")`. No cross-module constants, no `boto3.resource`. Real code
  varies more; the demo keeps to what the code reader resolves.

## The map

```mermaid
flowchart LR
  subgraph People
    sam[sam-support]
    priya[priya-intern]
    alex[alex-analyst]
    jordan[jordan-platform]
  end
  subgraph CI["Workflows in demo-org"]
    deploy[infra/deploy.yml]
    ci[infra/ci.yml]
    preview[docs-site/preview.yml]
    lint[website/lint.yml]
  end
  subgraph Run["Workloads"]
    oapi[orders-api, ECS]
    owrk[orders-worker, ECS]
    bjob[billing-job, Lambda]
    bapi[billing-api, Lambda]
    sp[support-portal, Lambda]
    ax[analytics-export, Lambda]
  end
  subgraph Data
    logs[(demo-app-logs)]
    inv[(invoices/)]
    pub[(public/)]
    raw[(data-lake raw/)]
    cur[(data-lake curated/)]
    state[(terraform-state)]
    dbs[(prod-db-credentials)]
    pay[(payments-api-key)]
    db[(customer-db)]
    ord[(demo-orders)]
  end
  sam --> sup[support-engineers] --> ps[prod-support]
  priya -. intern PR .-> sup
  alex --> ana[data-analysts] --> ar[analytics-read]
  jordan --> plat[platform-engineers]
  plat -- app-logs-read --> logs
  ps --> logs & inv & dbs
  ar -- data-lake-curated-read --> cur
  deploy --> gd[github-deploy]
  deploy -- environment production --> ta[terraform-apply]
  preview -. "loose sub repo:demo-org/*" .-> gd
  preview & lint --> fd{{demo-thirdparty/file-diff@v3}}
  gd --> pub
  gd --> ps
  ta --> state
  dbs -- UNLOCKS --> db
  oapi --> oapir[orders-api-task] -- orders-table-rw --> ord
  owrk --> owr[orders-worker-task] -- orders-table-rw --> ord
  bjob --> bjr[billing-job role] --> inv & pay & ord
  bapi --> bar[billing-api role] --> dbs
  sp --> spr[support-portal role] -. LegacyDbSecret, never called .-> dbs
  ax --> axr[analytics-export role] --> ord & raw & cur
  sp -. HTTP .-> bapi
  sp -. HTTP .-> oapi
  oapi -. HTTP .-> bapi
```

**How each workload relates to the rest.** This is the table to read when a fixture, a code edge or a
requirement looks wrong.

| Workload | Runs on | Code | Role, and how it gets its permissions | Env vars and the nodes they name | Code calls | Requirements | Talks to |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `orders-api` | ECS Fargate | `services/orders_api/` | `orders-api-task`: shared policy `orders-table-rw`; inline `orders-api-events` sends to the queue | `ORDERS_TABLE` → `dynamodb:demo-orders`; `ORDER_EVENTS_QUEUE_URL` → `sqs:order-events` (no code edge: spec 04 section 7); `BILLING_API_URL` → `workload:billing-api` | write and read `demo-orders` | R10 | billing-api |
| `orders-worker` | ECS Fargate | `services/orders_worker/` | `orders-worker-task`: shared policy `orders-table-rw`; inline `orders-worker-events` receives and deletes | `ORDERS_TABLE`; `ORDER_EVENTS_QUEUE_URL` | read and write `demo-orders` | R11 | |
| `billing-job` | Lambda, nightly | `services/billing_job/` | `billing-job`: inline policy | `ORDERS_TABLE`; `INVOICES_BUCKET` → both `demo-company-files` locations; `PAYMENTS_SECRET` → `secret:payments-api-key`; `INVOICE_TOPIC_ARN` → `sns:invoice-created` (no code edge) | read `demo-orders`, write `invoices/`, read `payments-api-key` | R7, R8, R9 | the payment provider (external, ignored) |
| `billing-api` | Lambda, internal API | `services/billing_api/` | `billing-api`: inline policy | `DB_SECRET` → `secret:prod-db-credentials`; `DB_NAME` (no node) | read `prod-db-credentials`, connect to `customer-db` | R6 | |
| `support-portal` | Lambda | `services/support_portal/` | `support-portal`: inline `LegacyDbSecret`, left over from a migration | `BILLING_API_URL`, `ORDERS_API_URL` → the two workloads | none | none | billing-api, orders-api |
| `analytics-export` | Lambda, nightly | `services/analytics_export/` | `analytics-export`: inline policy | `ORDERS_TABLE`; `LAKE_BUCKET` → both `demo-data-lake` locations | read `demo-orders`, write and read `raw/`, write `curated/` | R12, R13, R14 | |

## People and data

| Thing | ID in the graph | Notes |
| --- | --- | --- |
| Intern | `user:priya-intern` | Joins support this week |
| Support engineer | `user:sam-support` | Member of `support-engineers` in `main` |
| Analyst | `user:alex-analyst` | Member of `data-analysts` |
| Platform engineer | `user:jordan-platform` | Member of `platform-engineers` |
| Support group | `group:support-engineers` | May assume `prod-support` |
| Analysts group | `group:data-analysts` | May assume `analytics-read` |
| Platform group | `group:platform-engineers` | Has the managed policy `app-logs-read` attached |
| App logs | `s3://demo-app-logs/` | Expected Jev class `internal` |
| Invoices | `s3://demo-company-files/invoices/` | Expected `confidential` |
| Public files | `s3://demo-company-files/public/` | Expected `public` |
| Raw exports | `s3://demo-data-lake/raw/` | Order exports with customer names and addresses. Override `regulated` in `theseus.yaml`: from the name alone Jev rates it `internal` |
| Curated data | `s3://demo-data-lake/curated/` | Daily aggregates, no personal data. Expected `internal` |
| Terraform state | `s3://demo-terraform-state/` | Override `regulated` in `theseus.yaml`: state files hold every secret value Terraform has seen |
| DB secret | `secret:prod-db-credentials` | Credentials of the app's database user. Tag `db_instance = customer-db`. Expected `regulated` |
| Payments key | `secret:payments-api-key` | The card processor's API key. Expected `regulated` |
| Customer database | `db:customer-db` | Postgres. Expected `regulated` |
| Orders table | `dynamodb:demo-orders` | Orders with customer IDs and addresses. Expected `confidential` |
| Queues, topic, log groups | `sqs:order-events`, `sqs:order-events-dlq`, `sns:invoice-created`, `log-group:/aws/lambda/<function>`, `log-group:/ecs/<service>` | Events and request metadata, never customer data. Override `internal` in `theseus.yaml`, so they open no dangerous path whatever Jev says |
| Internet | `entry:internet` | Anyone; used by S3 bucket policies with `Principal = "*"` |

The PoC rated older names. Task A2 records Jev on these names. If Jev rates a
resource the scenarios need as sensitive (`confidential` or `regulated`) as anything else, add it to
`sensitive_overrides` and say so in the PR; a person's override always beats Jev.

## Terraform that Theseus models

Each row is one resource. "Sid" names a statement inside a `jsonencode` policy. ARNs shorten to their last part
here; write them in full in the files (`arn:aws:iam::111122223333:role/prod-support`).

### `people.tf`

| Address | Name | What it says |
| --- | --- | --- |
| `aws_iam_user.priya` | `priya-intern` | |
| `aws_iam_user.sam` | `sam-support` | |
| `aws_iam_user.alex` | `alex-analyst` | |
| `aws_iam_user.jordan` | `jordan-platform` | |
| `aws_iam_group.support` | `support-engineers` | |
| `aws_iam_group.analysts` | `data-analysts` | |
| `aws_iam_group.platform` | `platform-engineers` | |
| `aws_iam_user_group_membership.sam_support` | | `sam-support` in `support-engineers` |
| `aws_iam_user_group_membership.alex_analysts` | | `alex-analyst` in `data-analysts` |
| `aws_iam_user_group_membership.jordan_platform` | | `jordan-platform` in `platform-engineers` |
| `aws_iam_group_policy.support_assume` | `assume-prod-support` | Sid `AssumeProdSupport`: `sts:AssumeRole` on `role/prod-support` |
| `aws_iam_group_policy.analysts_assume` | `assume-analytics-read` | Sid `AssumeAnalyticsRead`: `sts:AssumeRole` on `role/analytics-read` |
| `aws_iam_group_policy_attachment.platform_logs` | | `platform-engineers` gets `policy/app-logs-read` |

### `roles.tf`

| Address | Name | What it says |
| --- | --- | --- |
| `aws_iam_role.prod_support` | `prod-support` | Trust Sid `TrustAccountPrincipals`: `Principal.AWS = arn:aws:iam::111122223333:root`, `sts:AssumeRole` |
| `aws_iam_role_policy.prod_support_read` | `prod-support-read` | Sid `ReadLogs`: `s3:GetObject`, `s3:ListBucket` on `demo-app-logs` and `demo-app-logs/*`. Sid `ReadInvoices`: `s3:GetObject` on `demo-company-files/invoices/*`. Sid `ReadDbSecret`: `secretsmanager:GetSecretValue` on `secret:prod-db-credentials-*` |
| `aws_iam_role.analytics_read` | `analytics-read` | Trust Sid `TrustAccountPrincipals`, as above |
| `aws_iam_role_policy_attachment.analytics_read_curated` | | `analytics-read` gets `policy/data-lake-curated-read` |

### `policies.tf`

| Address | Name | What it says |
| --- | --- | --- |
| `aws_iam_policy.app_logs_read` | `app-logs-read` | Sid `ReadAppLogs`: `s3:GetObject` on `demo-app-logs/*`; `s3:ListBucket` on `demo-app-logs` |
| `aws_iam_policy.data_lake_curated_read` | `data-lake-curated-read` | Sid `ReadCurated`: `s3:GetObject` on `demo-data-lake/curated/*` |
| `aws_iam_policy.orders_table_rw` | `orders-table-rw` | Sid `OrdersTableReadWrite`: `dynamodb:GetItem`, `dynamodb:Query`, `dynamodb:PutItem`, `dynamodb:UpdateItem` on `table/demo-orders` and `table/demo-orders/index/*`. Attached to two roles, so a fix that edits it changes both |

### `ci.tf`

| Address | Name | What it says |
| --- | --- | --- |
| `aws_iam_openid_connect_provider.github` | | URL `https://token.actions.githubusercontent.com`, client `sts.amazonaws.com` |
| `aws_iam_role.github_deploy` | `github-deploy` | Trust Sid `GitHubActionsOIDC`: federated GitHub OIDC, `sts:AssumeRoleWithWebIdentity`, `aud` StringEquals `sts.amazonaws.com`, `sub` StringLike `repo:demo-org/*` (loosened by an earlier PR so docs-site could publish previews) |
| `aws_iam_role_policy.github_deploy` | `github-deploy` | Sid `PublishSite`: `s3:PutObject` on `demo-company-files/public/*`. Sid `AssumeProdSupportForMigrations`: `sts:AssumeRole` on `role/prod-support` |
| `aws_iam_role.terraform_apply` | `terraform-apply` | Trust Sid `GitHubActionsOIDC`: as above, but `sub` StringEquals `repo:demo-org/infra:environment:production`. This is the pinned pattern that containment K copies |
| `aws_iam_role_policy.terraform_apply` | `terraform-apply` | Sid `TerraformState`: `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on `demo-terraform-state/*`; `s3:ListBucket` on `demo-terraform-state`. Sid `ApplyInfra`: control-plane actions only, on `*`: `iam:*`, `lambda:*`, `ecs:*`, `ec2:*`, `rds:*`, `sqs:*`, `sns:*`, `kms:*`, `logs:*`, `events:*`, `ecr:*`, `route53:*`, `apigateway:*`, `dynamodb:CreateTable`, `dynamodb:Describe*`, `dynamodb:UpdateTable`, `dynamodb:TagResource`, `s3:CreateBucket`, `s3:GetBucket*`, `s3:PutBucket*`, `secretsmanager:CreateSecret`, `secretsmanager:DescribeSecret`, `secretsmanager:TagResource` |

Of the `ApplyInfra` actions, only `logs:*`, `sqs:*` and `sns:*` touch modeled data, now that the AWS catalog
models log groups, queues and topics (C1's `queues.tf` and `logs.tf`): `terraform-apply` can read and write every
log group and queue and publish to the topic, besides the state bucket. None of these is a dangerous path:
`theseus.yaml` overrides all nine to `internal`, since they carry events and request metadata, never customer
data. Every Lambda and ECS execution role can also write every log group, through its AWS-managed policy. The
rest of `ApplyInfra` is control-plane.
`iam:*` would let it grant itself anything in a real account; privilege escalation through IAM writes is not
modeled (see "What the world leaves out").

### `data.tf`

| Address | Name | What it says |
| --- | --- | --- |
| `aws_s3_bucket.app_logs` | `demo-app-logs` | |
| `aws_s3_bucket.company_files` | `demo-company-files` | Prefixes `invoices/` and `public/`. C1 blocks public access in `platform.tf`; the public-bucket scenario explicitly relaxes that block |
| `aws_s3_bucket.data_lake` | `demo-data-lake` | Prefixes `raw/` and `curated/` |
| `aws_s3_bucket.terraform_state` | `demo-terraform-state` | Holds this stack's state (the demo itself plans with local state) |
| `aws_secretsmanager_secret.prod_db` | `prod-db-credentials` | Tag `db_instance = "customer-db"`; AWS-managed encryption key; billing rotates the application credential with its database cutover runbook |
| `aws_secretsmanager_secret.payments` | `payments-api-key` | No `db_instance` tag; AWS-managed encryption key; finance rotates the key with the external payment provider |
| `aws_db_instance.customer` | `customer-db` | Postgres 16, `db.t4g.micro`, `manage_master_user_password = true` (the master password never appears in Terraform), `db_subnet_group_name = "demo-db-subnets"`, `storage_encrypted = true`; deletion protection, Multi-AZ, IAM authentication, automatic minor upgrades, snapshot tag copying and Performance Insights enabled; export `postgresql` logs; literal `parameter_group_name = "demo-postgres16"` (C1 configures DDL and slow-query logging) |
| `aws_dynamodb_table.orders` | `demo-orders` | Hash key `order_id`; global secondary index `by_status` (`status`, `created_at`); `PAY_PER_REQUEST`; point-in-time recovery on; AWS-owned encryption key |

### `services.tf`

Every function: runtime `python3.12`, `s3_bucket = "demo-artifacts"`, `s3_key = "<name>/<version>.zip"` (so plan
needs no local zip), handler `handler.handler`, tag `theseus_code_path = "services/<folder>"`, and an attachment
of the AWS-managed `AWSLambdaBasicExecutionRole` to its role (logs only, no modeled action). Every role trusts
the service `lambda.amazonaws.com`.

Functions enable active X-Ray tracing and reserve 10 concurrent executions each. Their VPC config uses the
literal private subnet IDs `subnet-0a1b2c3d4e5f60001` and `subnet-0a1b2c3d4e5f60002`, and
`sg-0a1b2c3d4e5f60001` as the synthetic ID for C1's `aws_security_group.app` (`demo-app`). These literal IDs
represent resources in the fictional existing account; a real new deployment would have computed IDs.
Billing/data owners inspect failed nightly batch logs and rerun the jobs; a separate DLQ and send grant are
deferred. Request-driven functions return synchronous failures to the caller. These are documented Checkov
exceptions, keeping the review's prohibition on IAM changes.

Operational hardening never changes an IAM statement, trust condition,
resource name, environment variable or `theseus_code_path` tag. Exceptions inside each resource explain accepted
checks: names-only Lambda environment values, CI-validated artifacts, synchronous request failures, IAM users
awaiting SSO, account trust constrained by identity policies, the production-only Terraform apply role,
AWS-managed or AWS-owned encryption keys, manual secret rotation, and single-region buckets using SSE-S3 and
central CloudTrail data events. C1 owns the separate bucket settings. Database query logging is configured in
`demo-postgres16`; the literal name requires a Checkov graph-check exception. Performance Insights is used
instead of enhanced monitoring, which would add an IAM role.

| Address | Name | What it says |
| --- | --- | --- |
| `aws_iam_role.billing_job` | `billing-job` | |
| `aws_iam_role_policy.billing_job` | `billing-job` | Sid `WriteInvoices`: `s3:PutObject` on `demo-company-files/invoices/*`. Sid `ReadPaymentsKey`: `secretsmanager:GetSecretValue` on `secret:payments-api-key-*`. Sid `ReadOrders`: `dynamodb:Query` on `table/demo-orders` and `table/demo-orders/index/*`. Sid `AnnounceInvoices`: `sns:Publish` on `sns:invoice-created` |
| `aws_lambda_function.billing_job` | `billing-job` | Env `INVOICES_BUCKET = "demo-company-files"`, `ORDERS_TABLE = "demo-orders"`, `PAYMENTS_SECRET = "payments-api-key"`, `INVOICE_TOPIC_ARN = "arn:aws:sns:eu-west-1:111122223333:invoice-created"` |
| `aws_iam_role.billing_api` | `billing-api` | |
| `aws_iam_role_policy.billing_api` | `billing-api` | Sid `ReadDbSecret`: `secretsmanager:GetSecretValue` on the DB secret |
| `aws_lambda_function.billing_api` | `billing-api` | Env `DB_SECRET = "prod-db-credentials"`, `DB_NAME = "customers"` |
| `aws_iam_role.support_portal` | `support-portal` | |
| `aws_iam_role_policy.support_portal` | `support-portal` | Sid `LegacyDbSecret`: `secretsmanager:GetSecretValue` on the DB secret, left over from a migration |
| `aws_lambda_function.support_portal` | `support-portal` | Env `BILLING_API_URL = "https://billing-api.internal.demo.test"`, `ORDERS_API_URL = "https://orders-api.internal.demo.test"` |
| `aws_iam_role.analytics_export` | `analytics-export` | |
| `aws_iam_role_policy.analytics_export` | `analytics-export` | Sid `ReadOrders`: `dynamodb:Scan` on `table/demo-orders`. Sid `RawZone`: `s3:PutObject`, `s3:GetObject` on `demo-data-lake/raw/*`. Sid `CuratedZone`: `s3:PutObject` on `demo-data-lake/curated/*` |
| `aws_lambda_function.analytics_export` | `analytics-export` | Env `ORDERS_TABLE = "demo-orders"`, `LAKE_BUCKET = "demo-data-lake"` |

The four `aws_iam_role_policy_attachment.<name>_logs` resources sit next to their roles.

### `containers.tf`

| Address | Name | What it says |
| --- | --- | --- |
| `aws_ecs_cluster.apps` | `demo-apps` | Container Insights enabled. Not modeled; skipped and counted |
| `aws_iam_role.ecs_task_execution` | `ecs-task-execution` | Trust: service `ecs-tasks.amazonaws.com`. Pulls images and writes logs; never a workload's identity |
| `aws_iam_role_policy_attachment.ecs_task_execution` | | AWS-managed `AmazonECSTaskExecutionRolePolicy` (no modeled action) |
| `aws_iam_role.orders_api_task` | `orders-api-task` | Trust: service `ecs-tasks.amazonaws.com` |
| `aws_iam_role_policy_attachment.orders_api_table` | | `orders-api-task` gets `policy/orders-table-rw` |
| `aws_iam_role_policy.orders_api_events` | `orders-api-events` | Sid `SendOrderEvents`: `sqs:SendMessage` on `sqs:order-events` |
| `aws_iam_role.orders_worker_task` | `orders-worker-task` | Trust: service `ecs-tasks.amazonaws.com` |
| `aws_iam_role_policy_attachment.orders_worker_table` | | `orders-worker-task` gets `policy/orders-table-rw` |
| `aws_iam_role_policy.orders_worker_events` | `orders-worker-events` | Sid `ConsumeOrderEvents`: `sqs:ReceiveMessage`, `sqs:DeleteMessage` on `sqs:order-events` |
| `aws_ecs_task_definition.orders_api` | family `orders-api` | Fargate, 256 CPU, 512 MB; read-only container root filesystem. `task_role_arn = role/orders-api-task`, `execution_role_arn = role/ecs-task-execution`. One container `orders-api`, image `111122223333.dkr.ecr.eu-west-1.amazonaws.com/orders-api:2.3.1`, env `ORDERS_TABLE = "demo-orders"`, `ORDER_EVENTS_QUEUE_URL = "https://sqs.eu-west-1.amazonaws.com/111122223333/order-events"`, `BILLING_API_URL = "https://billing-api.internal.demo.test"` |
| `aws_ecs_task_definition.orders_worker` | family `orders-worker` | As above with `role/orders-worker-task`, image `orders-worker:2.3.1`, env `ORDERS_TABLE`, `ORDER_EVENTS_QUEUE_URL` |
| `aws_ecs_service.orders_api` | `orders-api` | `cluster = arn:aws:ecs:eu-west-1:111122223333:cluster/demo-apps`, `task_definition = "orders-api"`, Fargate, desired count 2, literal subnet IDs `subnet-0a1b2c3d4e5f60001` and `...60002`, tag `theseus_code_path = "services/orders_api"` |
| `aws_ecs_service.orders_worker` | `orders-worker` | As above, `task_definition = "orders-worker"`, desired count 1, tag `services/orders_worker` |

### `queues.tf`

Both queues are encrypted with `alias/demo-queues`, the KMS key in `platform.tf`, named literally. The key's
policy lets the two orders task roles use it through SQS, so their queue grants in `containers.tf` work; the
topic uses the AWS-managed `alias/aws/sns`, which needs no grant beyond `sns:Publish`. These grants reach only
`internal` nodes, so they open no dangerous path.

| Address | Name | What it says |
| --- | --- | --- |
| `aws_sqs_queue.order_events` | `order-events` | `order.created` from orders-api to orders-worker. Long polling (20 s), visibility 60 s, 4 days' retention; redrive to `order-events-dlq` after 5 receives |
| `aws_sqs_queue.order_events_dlq` | `order-events-dlq` | 14 days' retention; the on-call engineer replays it by hand |
| `aws_sns_topic.invoice_created` | `invoice-created` | One message per invoice billing-job issues; encrypted with `alias/aws/sns` |

### `logs.tf`

One log group per workload, 365 days' retention, CloudWatch's default encryption.

| Address | Name | What it says |
| --- | --- | --- |
| `aws_cloudwatch_log_group.billing_job` | `/aws/lambda/billing-job` | |
| `aws_cloudwatch_log_group.billing_api` | `/aws/lambda/billing-api` | |
| `aws_cloudwatch_log_group.support_portal` | `/aws/lambda/support-portal` | |
| `aws_cloudwatch_log_group.analytics_export` | `/aws/lambda/analytics-export` | |
| `aws_cloudwatch_log_group.orders_api` | `/ecs/orders-api` | |
| `aws_cloudwatch_log_group.orders_worker` | `/ecs/orders-worker` | |

70 modeled resources across `people.tf` to `logs.tf`.

## Terraform that Theseus skips (task C1)

These make the account look real. The importer skips every type it does not model and counts it in the result's
`coverage`; none of them adds a node or an edge. They may name modeled resources by Terraform reference
(`aws_s3_bucket.app_logs.bucket`), since the importer never reads them (see "Conventions").

| File | Resources |
| --- | --- |
| `network.tf` | `aws_vpc.main`; `aws_default_security_group.main` with no rules, so nothing can use it; four `aws_subnet` (two private, two public); `aws_internet_gateway.main`; `aws_route_table.public` and two associations; `aws_security_group.app` and `.db`; `aws_vpc_security_group_egress_rule.app_https` (443 out from the app group); `aws_vpc_security_group_ingress_rule.db_from_app` (5432 from the app group); `aws_db_subnet_group.main` (`demo-db-subnets`); `aws_vpc_endpoint.s3` |
| `platform.tf` | `aws_kms_key.queues` (rotation on; its policy lets the orders task roles use it through SQS) and its alias `alias/demo-queues`; `aws_ecr_repository.orders_api` and `.orders_worker` (immutable tags, scan on push); `aws_cloudwatch_event_rule` and `_target` for billing-job (02:00 UTC) and analytics-export (03:00 UTC) with their `aws_lambda_permission`; for every bucket, `demo-company-files` included: `aws_s3_bucket_versioning`, `aws_s3_bucket_server_side_encryption_configuration` (AES256), `aws_s3_bucket_public_access_block` (all four settings on), `aws_s3_bucket_lifecycle_configuration` and `aws_s3_bucket_notification` (to EventBridge); `aws_db_parameter_group.postgres16` (`demo-postgres16`, logs DDL and slow statements); `aws_route53_zone.internal` (`internal.demo.test`) with records for billing-api and orders-api; `aws_apigatewayv2_api.billing_internal` |

In total the world has 122 resources across 16 AWS services (counting the VPC types as EC2): 70 modeled and 52
skipped.

## Services (task C1)

Real-looking code, a few modules per service, 40 to 150 lines a module. No tests inside `demo-infra/`. The code
reader (task C2) must turn exactly these calls into edges. Line numbers come from the files once C1 merges. A
workload's calls to one resource are one `CALLS` edge whose `grants` hold every access and whose evidence holds
every call's line (spec 04 section 7). On `main` that is 10 `CALLS` and 3 `REQUESTS`; 5 calls are counted as
skipped (the queue's send, receive and delete, the topic's publish, and the payment provider).

| File | Functions and what they call | Edges the code reader makes |
| --- | --- | --- |
| `orders_api/app.py` | FastAPI app. `POST /orders` → `create_order`: `billing.customer_status`, then `store.put_order`, then `events.publish_order_created`. `GET /orders/{order_id}` → `store.get_order`. `GET /health` | none (calls go through the modules below) |
| `orders_api/store.py` | `ORDERS_TABLE = os.environ["ORDERS_TABLE"]`; `_ddb = boto3.client("dynamodb")`; `put_order` → `_ddb.put_item(TableName=ORDERS_TABLE, ...)`; `get_order` → `_ddb.get_item(TableName=ORDERS_TABLE, ...)` | One `CALLS` to `dynamodb:demo-orders`, grants read and write |
| `orders_api/events.py` | `_sqs.send_message(QueueUrl=os.environ["ORDER_EVENTS_QUEUE_URL"], ...)` | none: the queue is a node, but spec 04 section 7 has no `sqs` pattern; counted as skipped |
| `orders_api/billing.py` | `BILLING_API_URL = os.environ["BILLING_API_URL"]`; `customer_status` → `httpx.get(f"{BILLING_API_URL}/customers/{customer_id}/status", timeout=2)` | `REQUESTS` to `workload:billing-api` |
| `orders_worker/worker.py` | `main()`: long-poll `_sqs.receive_message`, call `fulfil.handle`, then `_sqs.delete_message` | none; counted as skipped |
| `orders_worker/fulfil.py` | `handle`: `_ddb.get_item(TableName=ORDERS_TABLE, ...)`, `reserve_stock` (pure), `_ddb.update_item(TableName=ORDERS_TABLE, ...)` to set `status = "fulfilled"` | `CALLS` read and write to `dynamodb:demo-orders` |
| `billing_job/handler.py` | `handler(event, context)`: for each order from `invoices.fulfilled_orders`, `invoices.render`, `invoices.store`, `payments.charge`, then `_sns.publish(TopicArn=os.environ["INVOICE_TOPIC_ARN"], ...)` | none of its own; the `sns` call is counted as skipped, as above |
| `billing_job/invoices.py` | `fulfilled_orders` → `_ddb.query(TableName=ORDERS_TABLE, IndexName="by_status", ...)`; `render` builds the PDF bytes; `store` → `_s3.put_object(Bucket=INVOICES_BUCKET, Key=f"invoices/{order_id}.pdf", Body=pdf)` | `CALLS` read to `dynamodb:demo-orders`; `CALLS` write to `s3://demo-company-files/invoices/` |
| `billing_job/payments.py` | `charge`: `_sm.get_secret_value(SecretId=PAYMENTS_SECRET)`, then `httpx.post("https://api.payments.example/v1/charges", ...)` | `CALLS` read to `secret:payments-api-key`; the external host makes no edge and is counted as skipped |
| `billing_api/handler.py` | `handler(event, context)`: routes `GET /invoices/{id}`, `GET /customers/{id}`, `GET /customers/{id}/status` to `queries` with a connection from `db.connect()` | none of its own |
| `billing_api/db.py` | `DB_SECRET = os.environ["DB_SECRET"]`; `connect`: `_sm.get_secret_value(SecretId=DB_SECRET)`, then `psycopg.connect(host=..., dbname=os.environ["DB_NAME"], user=..., password=...)` | `CALLS` read to `secret:prod-db-credentials`; `CALLS` `db:connect` to `db:customer-db` |
| `billing_api/queries.py` | SQL for invoices, customers and status, run on the connection passed in | none |
| `support_portal/handler.py` | `handler(event, context)`: `GET /tickets/{id}/context` → `views.ticket_context`; `GET /refunds/{id}` → `views.refund_page` | none |
| `support_portal/clients.py` | `BILLING_API_URL`, `ORDERS_API_URL` from the environment; `get_invoice` and `get_customer` → `httpx.get(f"{BILLING_API_URL}/...")`; `get_order` → `httpx.get(f"{ORDERS_API_URL}/orders/{order_id}")` | `REQUESTS` to `workload:billing-api` and `workload:orders-api`. No call to any secret |
| `support_portal/views.py` | `ticket_context`, `refund_page`. The refund confirmation text has the typo "recieved" | none |
| `analytics_export/handler.py` | `handler(event, context)`: `export.dump_orders`, `export.write_raw`, `export.read_raw`, `export.aggregate`, `export.write_curated` | none of its own |
| `analytics_export/export.py` | `_ddb.scan(TableName=ORDERS_TABLE, ...)`; `_s3.put_object(Bucket=LAKE_BUCKET, Key=f"raw/orders/{day}.jsonl")`; `_s3.get_object(...)` on the same key; `_s3.put_object(Bucket=LAKE_BUCKET, Key=f"curated/daily_sales/{day}.csv")` | `CALLS` read to `dynamodb:demo-orders`; write and read to `s3://demo-data-lake/raw/`; write to `s3://demo-data-lake/curated/` |

## Workflows in `demo-infra/workflows/demo-org/`

They describe the fictional org's CI. GitHub runs workflows only from the repo root's `.github/workflows/`, so
these never run, and the fictional `demo-thirdparty/file-diff` Action is never fetched.

| File | Triggers | `id-token` | Jobs and `uses:` | `sub` values it can present |
| --- | --- | --- | --- | --- |
| `infra/deploy.yml` | `push` to `main` | `write` | `apply` (`environment: production`): `actions/checkout@v4`, `aws-actions/configure-aws-credentials@v4` with `role/terraform-apply`, `hashicorp/setup-terraform@v3`, `terraform apply`. `release` (needs `apply`): checkout, configure-aws-credentials with `role/github-deploy`, publish `public/`, run migrations | `repo:demo-org/infra:environment:production` (apply), `repo:demo-org/infra:ref:refs/heads/main` (release) |
| `infra/ci.yml` | `pull_request` | none | `actions/checkout@v4`, `hashicorp/setup-terraform@v3`, `actions/setup-python@v5`; `terraform fmt -check`, `terraform validate`, `ruff check services` | none (no ID token) |
| `docs-site/preview.yml` | `pull_request` | `write` (copied from infra, never used) | `actions/checkout@v4`, `demo-thirdparty/file-diff@v3` to list changed pages, then a build | `repo:demo-org/docs-site:pull_request` |
| `website/lint.yml` | `pull_request` | none | `actions/checkout@v4`, `demo-thirdparty/file-diff@v3` | none |

## `theseus.yaml` (world root)

```yaml
account: "111122223333"
region: eu-west-1
org: demo-org
data_locations:
  - {id: "s3://demo-app-logs/", bucket: demo-app-logs, prefix: ""}
  - {id: "s3://demo-company-files/invoices/", bucket: demo-company-files, prefix: invoices/}
  - {id: "s3://demo-company-files/public/", bucket: demo-company-files, prefix: public/}
  - {id: "s3://demo-data-lake/raw/", bucket: demo-data-lake, prefix: raw/}
  - {id: "s3://demo-data-lake/curated/", bucket: demo-data-lake, prefix: curated/}
  - {id: "s3://demo-terraform-state/", bucket: demo-terraform-state, prefix: ""}
sensitive_overrides:             # node ID -> class; a person's override always beats Jev
  "s3://demo-terraform-state/": regulated
  "s3://demo-data-lake/raw/": regulated   # Jev reads only the name and rates it internal
  # Queues, the topic and the log groups carry events and request metadata, never customer data.
  "sqs:order-events": internal
  "sqs:order-events-dlq": internal
  "sns:invoice-created": internal
  "log-group:/aws/lambda/analytics-export": internal
  "log-group:/aws/lambda/billing-api": internal
  "log-group:/aws/lambda/billing-job": internal
  "log-group:/aws/lambda/support-portal": internal
  "log-group:/ecs/orders-api": internal
  "log-group:/ecs/orders-worker": internal
environments:                    # anything not listed is prod
  staging:
    - workflow:demo-org/docs-site/preview.yml
    - workflow:demo-org/website/lint.yml
requirements:
  - {id: R1, principal: user:sam-support, access: read, resource: "s3://demo-app-logs/"}
  - {id: R2, principal: user:sam-support, access: read, resource: "s3://demo-company-files/invoices/"}
  - {id: R3, principal: user:sam-support, access: read, resource: "db:customer-db"}
  - {id: R4, principal: workflow:demo-org/infra/deploy.yml, access: write, resource: "db:customer-db"}
  - {id: R5, principal: workflow:demo-org/infra/deploy.yml, access: write, resource: "s3://demo-company-files/public/"}
  - {id: R6, principal: workload:billing-api, access: read, resource: "db:customer-db"}
  - {id: R7, principal: workload:billing-job, access: write, resource: "s3://demo-company-files/invoices/"}
  - {id: R8, principal: workload:billing-job, access: read, resource: "dynamodb:demo-orders"}
  - {id: R9, principal: workload:billing-job, access: read, resource: "secret:payments-api-key"}
  - {id: R10, principal: workload:orders-api, access: write, resource: "dynamodb:demo-orders"}
  - {id: R11, principal: workload:orders-worker, access: write, resource: "dynamodb:demo-orders"}
  - {id: R12, principal: workload:analytics-export, access: read, resource: "dynamodb:demo-orders"}
  - {id: R13, principal: workload:analytics-export, access: write, resource: "s3://demo-data-lake/raw/"}
  - {id: R14, principal: workload:analytics-export, access: write, resource: "s3://demo-data-lake/curated/"}
  - {id: R15, principal: user:alex-analyst, access: read, resource: "s3://demo-data-lake/curated/"}
  - {id: R16, principal: user:jordan-platform, access: read, resource: "s3://demo-app-logs/"}
  - {id: R17, principal: workflow:demo-org/infra/deploy.yml, access: write, resource: "s3://demo-terraform-state/"}
```

## What `main` looks like

About 70 nodes. Every requirement R1 to R17 is satisfied. Exactly six dangerous paths exist before any PR; they
appear as "unchanged" in every PR diff and are what scan mode reports.

| Actor | Reaches | Why |
| --- | --- | --- |
| `workflow:demo-org/infra/deploy.yml` | invoices | `github-deploy` may assume `prod-support`, which reads invoices; R4 and R5 do not cover invoices |
| `workflow:demo-org/docs-site/preview.yml` | invoices, the DB secret, the customer database | The loose `sub` `repo:demo-org/*` accepts its `pull_request` token |
| `workload:support-portal` | the DB secret, the customer database | `LegacyDbSecret`, which its code never calls |

Everything else is covered by a requirement or is not sensitive: the analysts reach only `curated/`, the platform
group only the logs, `terraform-apply` only the state (R17), and every workload only what its code calls.
Betweenness over the traversal and grant edges ranks `role:prod-support` first among roles (20 actor-to-data
pairs pass through it, 12 through `github-deploy`).

These outcomes were checked with a throwaway model before the event; it is not part of the repo. F5 confirms
them on the real plans.

## What the world leaves out

Said in the README's limits section, so judges hear it from us first.

- **Privilege escalation through IAM writes.** `terraform-apply` has `iam:*`; in a real account it could grant
  itself anything. Theseus models data access, not who can rewrite IAM.
- **Resource policies other than S3 bucket policies**, KMS key policies, permission boundaries and SCPs. Real
  repos that use them get UNKNOWN edges.
- **Network reachability.** The VPC, security groups and the internal API Gateway are in the plan, but skipped:
  Theseus models who may read or write data, not which network path reaches a service.
- **Modules.** The demo is one root module; the importer reads child modules, but evidence lines point to the
  module's file, not the call site.

## The five scenarios

Each scenario is a folder in `fixtures/` (layout in `05-contracts.md`), generated by `tools/make_fixture.py`
from `demo-infra/` plus the change below. Humans write `expected.json` from these outcomes (task F5).

### `intern` (PR mode; Beats 1 and 2)

- **Change:** adds `aws_iam_user_group_membership.priya_support` to `people.tf` (`priya-intern` in `support-engineers`).
- **PR title:** "Add Priya to support-engineers for prod log access"
- **PR body:** "Priya joins support this week. Adding her to support-engineers so she can read prod logs during onboarding."
- **Intent:** `user:priya-intern` read `s3://demo-app-logs/`. Not suspicious.
- **Opened dangerous paths (3):** `priya-intern` to invoices, to `secret:prod-db-credentials`, and to
  `db:customer-db`. The database route: `priya-intern` MEMBER_OF `support-engineers` CAN_ASSUME
  `prod-support` CAN `prod-db-credentials` UNLOCKS `customer-db`.
- **Requirements:** R1 to R17 and the intent requirement I1 all satisfied in head.
- **Minimum cut for `priya-intern`:** value at least 1,000,000, so not cuttable: every route starts with her
  membership edge, which I1 needs.
- **Candidates:** A (remove her from the group) fails, breaking I1. B (the LLM: a new `intern-onboarding` role that
  reads only app logs and trusts her, plus removing the membership) passes and is recommended. C (a Deny on
  `prod-support` conditioned on her identity) is UNKNOWN. D (remove `AssumeProdSupport`) fails, breaking R1 to R3
  and I1.
- **Check:** failure until B is applied, then success.

### `public-bucket` (PR mode; Try-it preset)

- **Change:** adds `aws_s3_bucket_policy.company_files_public` to `data.tf` with Sid `PublicRead`:
  `Principal = "*"`, `s3:GetObject` on `arn:aws:s3:::demo-company-files/*`. AWS rejects a public policy while
  Block Public Access is on, so it also sets `block_public_policy` and `restrict_public_buckets` to `false` in
  company-files' block in `platform.tf`, in place: no line moves.
- **PR title:** "Make company-files public so marketing can link the pricing PDF"
- **PR body:** "Marketing wants to link public/pricing.pdf from the website."
- **Intent:** `entry:internet` read `s3://demo-company-files/public/`.
- **Opened dangerous path (1):** `entry:internet` to invoices. The comment adds: "likely holds invoices,
  because `billing-job` writes `invoices/*`" (its `CAN` write edge, backed by its `CALLS` edge).
- **Minimum cut:** value 1, cut on the `entry:internet` CAN edge to invoices.
- **Candidates:** A (remove `PublicRead`) fails, breaking the intent requirement. S (scope `PublicRead` to
  `public/*`) passes and is recommended. B (the LLM) is expected to pass with the same shape.

### `compromised-action` (finding mode; Beat 3)

The advisory text reads like a GHSA: summary, critical severity, affected versions v1/v2/v3, patched version
v4, runner-memory and secret disclosure through build logs, and upgrade/rotation guidance. It describes the
fictional Action only. The synthetic disclaimer lives in `scenario.yaml`'s description and the demo README,
not in the advisory text. The existing advisory fields and affected-version matching stay unchanged.

- **Input:** `advisory.json`: ID `GHSA-demo-0001`, action `demo-thirdparty/file-diff`, affected versions
  `v1`, `v2`, `v3`. Modeled on the tj-actions compromise (CVE-2025-30066). Its text is untrusted.
- **Matched workflows:** `docs-site/preview.yml` and `website/lint.yml`, both on `v3`. Only `preview.yml` has
  `id-token: write`, so only it gets a TRUSTS edge. `lint.yml` reaches nothing.
- **Blast radius (assumed compromise):** invoices, the DB secret, the customer database. The database is five
  hops from the Action: Action, `preview.yml`, `github-deploy`, `prod-support`, `prod-db-credentials`, `customer-db`.
  `terraform-apply` and the state bucket stay out of reach, because that role's `sub` is pinned.
- **Minimum cut:** value 1, on `preview.yml` TRUSTS `github-deploy`.
- **Containment (K):** set `github-deploy`'s `sub` to `repo:demo-org/infra:ref:refs/heads/main`, the same
  pinning `terraform-apply` already has. Passes: the preview path closes; R4, R5 and R17 still hold.
- **Rotate:** `secret:prod-db-credentials`.
- **Staging to prod:** `preview.yml` (staging) reaches prod data: flagged.
- **Choke point:** betweenness ranks `role:prod-support` first among roles.

### `unused-grant` (scan mode; Beat 4)

- **Input:** `main` only.
- **Grant never called (1):** `workload:support-portal` may read `secret:prod-db-credentials`
  (`aws_iam_role_policy.support_portal`, Sid `LegacyDbSecret`), and no line of its code calls it. Every other
  workload's grants to sensitive data are backed by a call.
- **Minimum cut for `support-portal`:** value 1, on that CAN edge. Its `RUNS_AS` edge and the `UNLOCKS` edge
  carry the large capacity, so the cut cannot land there.
- **Candidate U:** remove `LegacyDbSecret`. Passes: the path closes, no requirement breaks, and no `CALLS`
  edge loses its access.
- **Not flagged:** `billing-api`'s read of the secret (R6, and its code calls it), `billing-job`'s grants (R7 to
  R9, all called), and the shared `orders-table-rw` policy (R10, R11, both called).

### `code-pr` (PR mode; Beat 4)

- **Change:** `services/support_portal/views.py` fixes "recieved" to "received". A new module
  `services/support_portal/export.py` reads `DB_SECRET = os.environ["DB_SECRET"]` and adds `export_customers()`:
  `get_secret_value(SecretId=DB_SECRET)`, then `psycopg.connect(...)` and a `SELECT` of customer emails. `handler.py` routes `GET /admin/export` to it.
  `services.tf` adds `DB_SECRET = "prod-db-credentials"` to `support-portal`'s environment. No IAM change.
- **PR title:** "Fix a typo on the support page"
- **PR body:** "Fixes a typo in the refund confirmation text."
- **Intent:** no access change.
- **Opened dangerous paths:** none (the IAM grant already existed).
- **Use beyond intent (2):** `support-portal` now calls `secret:prod-db-credentials` and connects to
  `db:customer-db`, each with the file and line of the new call. The PR says it fixes a typo.
- **Check:** failure, with the headline "Your PR says: fix a typo. Your code now reads customer-db."
