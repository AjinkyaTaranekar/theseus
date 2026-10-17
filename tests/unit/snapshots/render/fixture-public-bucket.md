<!-- theseus:pr-comment -->
## 🔴 Merge blocked

**This PR would let anyone on the internet read demo-company-files/invoices/**, which holds data of unknown sensitivity.

**The PR says:** stub.\
**It asked for:** read **demo-company-files/public/** · **It would get:** **demo-company-files/invoices/**\
**How:** **anyone on the internet** can read **demo-company-files/invoices/**.\
**Fix:** reply `/theseus apply` to commit the fix (candidate S). Tested on a copy of the graph: closes the only way in, breaks nothing.

```mermaid
flowchart LR
  n1["anyone on the internet<br/>entry point"]
  n2["demo-company-files/invoices/<br/>data store"]
  n1 -->|"can read"| n2
```

<sub>Red arrow: added by this PR · Shaded: sensitive data</sub>

<details>
<summary><b>Step by step</b> (1 way in, each linked to its line)</summary>

**What's at risk**

- **demo-company-files/invoices/**, a data store: data of unknown sensitivity

| Actor | Target | Hops |
| --- | --- | --- |
| `entry:internet` | `s3://demo-company-files/invoices/` | 1 |

How **anyone on the internet** reaches **demo-company-files/invoices/**

1. `entry:internet` → `s3://demo-company-files/invoices/` (CAN): [terraform/data.tf:105](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/data.tf#L105)

</details>

<details>
<summary><b>The fix that passes</b>, tested on a copy of the graph</summary>

**Smallest change:** One change closes every path: `entry:internet CAN s3://demo-company-files/invoices/` (unknown: stub).

| Fix | Dangerous paths | Required access | Code calls | Verdict |
| --- | --- | --- | --- | --- |
| **Candidate S (rule)** | **all closed** | **kept** | **kept** | **pass** |

Theseus also tried 1 other fix that doesn't pass: candidate A (fail).

Reply `/theseus apply` to commit it.

</details>

<details>
<summary><b>Details</b></summary>

Checkov 3.2.255 passed this commit (52 checks). It checks one resource at a time, so it cannot see a path that crosses several.

**What the change does:** Adds `aws_s3_bucket_policy.company_files_public`; updates `aws_s3_bucket_public_access_block.company_files`. Opens 1 dangerous path, closes 0.

**Unchanged paths**

| Actor | Target | Hops |
| --- | --- | --- |
| `user:casey-contractor` | `db:customer-db` | 4 |
| `user:casey-contractor` | `s3://demo-company-files/invoices/` | 3 |
| `user:casey-contractor` | `secret:legacy-reports-password` | 3 |
| `user:casey-contractor` | `secret:payments-api-key` | 3 |
| `user:casey-contractor` | `secret:prod-db-credentials` | 3 |
| `user:casey-contractor` | `secret:smtp-credentials` | 3 |
| `workflow:demo-org/docs-site/preview.yml` | `db:customer-db` | 4 |
| `workflow:demo-org/docs-site/preview.yml` | `s3://demo-company-files/invoices/` | 3 |

and 15 more: every path is on the graph page.

Coverage: not recorded.

Timings: not recorded.

</details>

<details>
<summary><b>About Theseus</b></summary>

Theseus maps who can reach what in your infrastructure, as a graph in FalkorDB. It blocks a PR that opens a new way to sensitive data, and links every step to the line behind it.

</details>
