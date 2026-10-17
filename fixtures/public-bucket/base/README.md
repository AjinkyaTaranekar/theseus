Nothing here is real. This is a synthetic company, account, infrastructure, and workflow inventory.

# Demo store

Customers place orders on the website. **orders-api** (a container on ECS) checks the customer with
**billing-api**, stores the order in the DynamoDB table `demo-orders`, and queues an event. **orders-worker** (ECS)
takes the event and marks the order fulfilled. Every night **billing-job** (Lambda) turns fulfilled orders into
invoice PDFs in `demo-company-files/invoices/` and charges the card with the payment provider's key.
**billing-api** (Lambda) serves invoices and customer records from the Postgres database `customer-db`.
**support-portal** (Lambda) is the support team's internal tool; it asks billing-api and orders-api over HTTP.
Every night **analytics-export** (Lambda) dumps orders into the data lake's `raw/` zone and writes daily aggregates
to `curated/`, which the analysts read. Sam works in support, Alex is an analyst, Jordan runs the platform, and
Priya, an intern, joins support this week.


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

## Generate the fixtures

Use Python 3.12 with the repository installed (`pip install -e ".[dev]"`), Terraform 1.16.6, and AWS provider `~> 6.69`.
Run these commands from the repository root:

```bash
tools/plan.sh demo-infra/terraform /tmp/main.plan.json
python tools/make_fixture.py all
```

Initialization downloads the provider; planning uses literal mock credentials, skips AWS validation and metadata, disables refresh, and runs in a temporary directory with no existing state. Nothing is ever applied. An optional `TF_PLUGIN_CACHE_DIR` can reuse provider downloads. Generated fixture plans omit Terraform's top-level timestamp and use sorted JSON keys.

`intern` adds only Priya's membership; `public-bucket` adds only `PublicRead`. Finding and scan modes (`compromised-action`, `unused-grant`) contain a base world only. The advisory and third-party Action are fictional inputs. Workflows under `workflows/` are archived inputs; GitHub does not execute them here.

C1 adds service implementations and platform/network infrastructure, then adds `code-pr` to the generator.
The merged IAM catalog models queues, topics and log groups; their labels and requirements must be settled
before F5 freezes the C1 outcomes. Until then, the six service folders are empty packages and unused-grant has infrastructure inputs only. The code-based conclusion belongs to C1/C2/C3. F5 is human work: write and review `expected.json` after reviewing the final source lines. The generator never reads or writes that file.

## Operational settings and review handoff

Lambdas reserve 10 concurrent executions each and use the two literal private subnet IDs from spec 02 plus
`sg-0a1b2c3d4e5f60001`, the synthetic ID for C1's `demo-app` security group. Billing/data owners inspect failed
nightly batch logs and rerun the jobs; a separate DLQ and send grant are deferred to preserve the existing IAM
graph. Request-driven functions return failures synchronously. These settings represent the fictional existing
account; the literal IDs are not outputs from a new deployment.

The existing resources enable active Lambda tracing, database deletion protection, Multi-AZ, IAM database
authentication, automatic minor upgrades, snapshot tag copying, Performance Insights and Postgres log exports.
Containers use read-only root filesystems and the cluster enables Container Insights. Each Checkov exception
explains an accepted operational tradeoff inside its resource; IAM statements, trust conditions, resource names,
workload environments and code-path tags retain the access graph defined in spec 02.

C1 (#22, PR #64) supplies the network, `demo-postgres16` query-logging parameter group, and bucket versioning,
SSE-S3 encryption, lifecycle rules, notifications and public-access blocks. Its public-bucket scenario disables
the two policy-blocking flags before adding `PublicRead`. Checkov's acceptance target is zero failures with C1
combined, so those missing bucket settings remain visible on this branch rather than receiving exceptions.

The compromised-action advisory describes a fictional incident and fictional affected/patched versions. Its
text reads as an advisory; `scenario.yaml` and this README retain the synthetic disclaimer. Nothing describes
an actual compromise of an Action or an actual company's infrastructure.

These changes move Terraform and workflow source lines. Regenerate every fixture before F5 writes its cites;
humans must review any existing answer-key citations against the regenerated sources. The separate
`theseus_code_path` tag/mapping decision in #63 still needs both humans' agreement.

## Scope of the model

Theseus models data access in the supported IAM subset. It does not model privilege escalation through IAM writes (including terraform-apply's `iam:*`), network controls, resource policies other than S3 bucket policies, KMS key policies, permission boundaries, or SCPs. Bucket encryption settings and other platform resources belong to C1. The literal references make this world plan without an account; they are not a deployable stack.
