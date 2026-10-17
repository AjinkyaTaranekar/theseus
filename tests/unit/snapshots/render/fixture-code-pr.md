<!-- theseus:pr-comment -->
## 🔴 Merge blocked

**This PR would make support-portal's code read customer-db**, which holds data of unknown sensitivity. The PR doesn't mention it.

**The PR says:** stub.\
**It asked for:** no new access · **Its code would read:** **customer-db** and **prod-db-credentials**\
**How:** **support-portal**'s code reads **customer-db** at an unknown line.\
**Fix:** ask the author why the change needs this access.

<details>
<summary><b>What's at risk</b></summary>

- **customer-db**, a data store: data of unknown sensitivity
- **prod-db-credentials**, a data store: data of unknown sensitivity

</details>

<details>
<summary><b>Details</b></summary>

Checkov 3.2.255 passed this commit (52 checks).

**What the change does:** Updates `aws_lambda_function.support_portal`. Opens 0 dangerous paths, closes 0.

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
| `workflow:demo-org/docs-site/preview.yml` | `secret:prod-db-credentials` | 3 |
| `workflow:demo-org/infra/deploy.yml` | `s3://demo-company-files/invoices/` | 2 |
| `workflow:demo-org/infra/deploy.yml` | `secret:legacy-reports-password` | 2 |
| `workflow:demo-org/infra/deploy.yml` | `secret:payments-api-key` | 2 |
| `workflow:demo-org/infra/deploy.yml` | `secret:smtp-credentials` | 2 |
| `workflow:demo-org/infra/snapshot.yml` | `db:customer-db` | 3 |
| `workflow:demo-org/infra/snapshot.yml` | `s3://demo-company-files/invoices/` | 2 |
| `workflow:demo-org/infra/snapshot.yml` | `secret:legacy-reports-password` | 2 |
| `workflow:demo-org/infra/snapshot.yml` | `secret:payments-api-key` | 2 |
| `workflow:demo-org/infra/snapshot.yml` | `secret:prod-db-credentials` | 2 |
| `workflow:demo-org/infra/snapshot.yml` | `secret:smtp-credentials` | 2 |
| `workload:invoice-mailer` | `secret:payments-api-key` | 2 |
| `workload:receipt-renderer` | `secret:payments-api-key` | 2 |
| `workload:support-portal` | `db:customer-db` | 3 |
| `workload:support-portal` | `secret:prod-db-credentials` | 2 |

Coverage: not recorded.

Timings: not recorded.

Models: not recorded.

</details>

<details>
<summary><b>About Theseus</b></summary>

Theseus maps who can reach what in your infrastructure, as a graph in FalkorDB. It blocks a PR that opens a new way to sensitive data, and links every step to the line behind it.

</details>
