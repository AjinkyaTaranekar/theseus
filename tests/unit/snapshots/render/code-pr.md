<!-- theseus:pr-comment -->
## 🔴 Merge blocked

The code of **billing-api**, a service, now reads **customer-db**, a database with personal, payment or health data, and the PR does not mention it.

**Says:** fix a typo on the support page.\
**Needs:** no new access, it says · **Code now reads:** **customer-db**\
**Why:** **billing-api**'s code reads **customer-db** at [services/billing\_api/app.py:12](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/services/billing_api/app.py#L12).\
**Do:** ask the author why the change needs this access.

<details>
<summary><b>What's at risk</b></summary>

- **customer-db**, a database: personal, payment or health data, or a key that opens it

</details>

<details>
<summary><b>What Theseus checked</b></summary>

Checkov 3.2.255 passed this commit (52 checks).

**What the change does:** Opens 0 dangerous paths, closes 0.

Coverage: not recorded.

Timings: not recorded.

Models: not recorded.

</details>

<details>
<summary><b>What is Theseus?</b></summary>

Theseus reviews infrastructure changes as a graph in FalkorDB: who can reach which data, through which groups, roles, secrets and code. It blocks a merge when a change opens a new way to sensitive data, and every step it shows links to the line that causes it.

</details>
