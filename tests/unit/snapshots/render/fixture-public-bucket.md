<!-- theseus:pr-comment -->
## 🔴 Merge blocked

**Anyone on the internet** could read **demo-company-files/invoices/**, a data store with data of unknown sensitivity.

**Says:** stub.\
**Needs:** read **demo-company-files/public/** · **Grants too:** **demo-company-files/invoices/**\
**Why:** **anyone on the internet** can read **demo-company-files/invoices/**.\
**Do:** reply `/theseus apply S` to commit fix S (Candidate S). Theseus tested it on a copy of the graph: it closes all 1 way in and breaks nothing.

```mermaid
flowchart LR
  n1["anyone on the internet<br/>entry point"]
  n2["demo-company-files/invoices/<br/>data store"]
  n1 -->|"read"| n2
```

<sub>Shaded: sensitive data. Thick red arrow: what this PR adds or changes. Each step links to its line under <b>The path, step by step</b>.</sub>

<details>
<summary><b>The path, step by step</b> (1 way in, with links to each line)</summary>

**What's at risk**

- **demo-company-files/invoices/**, a data store: data of unknown sensitivity

| Actor | Target | Hops |
| --- | --- | --- |
| `entry:internet` | `s3://demo-company-files/invoices/` | 1 |

How **anyone on the internet** reaches **demo-company-files/invoices/**

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
<summary><b>What Theseus checked</b></summary>

Checkov 3.2.255 passed this commit (52 checks). It checks one resource at a time, so it cannot see a path that crosses several.

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

<details>
<summary><b>What is Theseus?</b></summary>

Theseus reviews infrastructure changes as a graph in FalkorDB: who can reach which data, through which groups, roles, secrets and code. It blocks a merge when a change opens a new way to sensitive data, and every step it shows links to the line that causes it.

</details>
