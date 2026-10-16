<!-- theseus:pr-comment -->
## 🔴 Merge blocked

The code of **support-portal**, a service, now reads **customer-db**, a data store with data of unknown sensitivity, and the PR does not mention it.

**Says:** stub.\
**Needs:** no new access, it says · **Code now reads:** **customer-db** and **prod-db-credentials**\
**Why:** **support-portal**'s code reads **customer-db** at an unknown line.\
**Do:** ask the author why the change needs this access.

<details>
<summary><b>What's at risk</b></summary>

- **customer-db**, a data store: data of unknown sensitivity
- **prod-db-credentials**, a data store: data of unknown sensitivity

</details>

<details>
<summary><b>What Theseus checked</b></summary>

Checkov 3.2.255 passed this commit (52 checks).

**What the change does:** Updates `aws_lambda_function.support_portal`. Opens 0 dangerous paths, closes 0.

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
