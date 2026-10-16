<!-- theseus:pr-comment -->
## 🔴 Merge blocked

**Your PR says: fix a typo. Your code now reads customer-db.**

#### What happened

This PR updates `aws_lambda_function.support_portal`.\
The code of the **support-portal** service now reads the **customer-db** data store (unknown file), and the PR does not mention it.\
The code of the **support-portal** service now reads the **prod-db-credentials** data store (unknown file), and the PR does not mention it.

#### What's at risk

- **customer-db**, a data store: data of unknown sensitivity
- **prod-db-credentials**, a data store: data of unknown sensitivity

#### What the PR said it needs

"stub"\
It says it changes no access.

#### What to do

Ask the author why the change needs this access. If it should have it, an owner adds it to `theseus.yaml`.

Checkov 3.2.255 passed this commit (52 checks).

<details>
<summary><b>Technical details</b></summary>

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
