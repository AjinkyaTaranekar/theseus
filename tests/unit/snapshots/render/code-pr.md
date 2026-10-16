<!-- theseus:pr-comment -->
## 🔴 Merge blocked

**This PR would make billing-api's code read customer-db**, which holds personal, payment or health data. The PR doesn't mention it.

**The PR says:** fix a typo on the support page.\
**It asked for:** no new access · **Its code would read:** **customer-db**\
**How:** **billing-api**'s code reads **customer-db** at [services/billing\_api/app.py:12](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/services/billing_api/app.py#L12).\
**Fix:** ask the author why the change needs this access.

<details>
<summary><b>What's at risk</b></summary>

- **customer-db**, a database: personal, payment or health data, or a key that opens it

</details>

<details>
<summary><b>Details</b></summary>

Checkov 3.2.255 passed this commit (52 checks).

**What the change does:** Opens 0 dangerous paths, closes 0.

Coverage: not recorded.

Timings: not recorded.

Models: not recorded.

</details>

<details>
<summary><b>About Theseus</b></summary>

Theseus maps who can reach what in your infrastructure, as a graph in FalkorDB. It blocks a PR that opens a new way to sensitive data, and links every step to the line behind it.

</details>
