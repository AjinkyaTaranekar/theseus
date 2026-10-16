<!-- theseus:pr-comment -->
## 🔴 Merge blocked

**stub**

#### What happened

This PR adds `aws_s3_bucket_policy.company_files_public`; updates `aws_s3_bucket_public_access_block.company_files`.\
Because of that, a new way to reach sensitive data opens:\
**anyone on the internet** can read the **demo-company-files/invoices/** data store.

#### What's at risk

- **demo-company-files/invoices/**, a data store: data of unknown sensitivity

#### What the PR said it needs

"stub"\
It asks only for: **anyone on the internet** to read **demo-company-files/public/**.

#### What to do

✅ **Reply `/theseus apply S`** to commit fix S: Candidate S.\
Theseus tested it on a copy of the graph: it closes all 1 way in and breaks nothing.\
Or ask the author to change the PR.

Checkov 3.2.255 passed this commit (52 checks). It checks one resource at a time, so it cannot see a path that crosses several.

<details>
<summary><b>The path, step by step</b> (1 way in, with links to each line)</summary>

| Actor | Target | Hops |
| --- | --- | --- |
| `entry:internet` | `s3://demo-company-files/invoices/` | 1 |

How **anyone on the internet** reaches **demo-company-files/invoices/**

```mermaid
flowchart LR
  n1["entry:internet"]
  n2["s3://demo-company-files/invoices/"]
  n1 -->|CAN| n2
```

1. `entry:internet` → `s3://demo-company-files/invoices/` (CAN): [terraform/data.tf:105](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/data.tf#L105)

</details>

<details>
<summary><b>All 2 fixes Theseus tested</b>, each on a copy of the graph</summary>

**Smallest change:** One change closes every path: `entry:internet CAN s3://demo-company-files/invoices/` (unknown: stub).

| ID | Fix | Dangerous paths | Required access | Code calls | Verdict |
| --- | --- | --- | --- | --- | --- |
| A | Candidate A (rule) | all closed | kept | kept | fail |
| **S** | **Candidate S (rule)** | **all closed** | **kept** | **kept** | **pass** |

Reply `/theseus apply S` to commit a fix.

</details>

<details>
<summary><b>Technical details</b></summary>

**What the change does:** Adds `aws_s3_bucket_policy.company_files_public`; updates `aws_s3_bucket_public_access_block.company_files`. Opens 1 dangerous path, closes 0.

**Unchanged paths**

| Actor | Target | Hops |
| --- | --- | --- |
| `workflow:demo-org/docs-site/preview.yml` | `db:customer-db` | 4 |
| `workflow:demo-org/docs-site/preview.yml` | `s3://demo-company-files/invoices/` | 3 |
| `workflow:demo-org/docs-site/preview.yml` | `secret:prod-db-credentials` | 3 |
| `workflow:demo-org/infra/deploy.yml` | `s3://demo-company-files/invoices/` | 3 |
| `workload:support-portal` | `db:customer-db` | 3 |
| `workload:support-portal` | `secret:prod-db-credentials` | 2 |

Coverage: not recorded.

Timings: not recorded.

Models: not recorded.

</details>
