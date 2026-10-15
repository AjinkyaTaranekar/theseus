<!-- theseus:pr-comment -->
## 🔴 Merge blocked

**Your PR says: fix a typo. Your code now reads customer-db.**

#### What happened

The code of the **billing-api** service now reads the **customer-db** database ([services/billing\_api/app.py:12](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/services/billing_api/app.py#L12)), and the PR does not mention it.

#### What's at risk

- **customer-db**, a database: personal, payment or health data, or a key that opens it

#### What the PR said it needs

"Fix a typo on the support page."\
It says it changes no access.

#### What to do

Ask the author why the change needs this access. If it should have it, an owner adds it to `theseus.yaml`.

Checkov 3.2.255 passed this commit (52 checks).

<details>
<summary><b>Technical details</b></summary>

**What the change does:** Opens 0 dangerous paths, closes 0.

Coverage: not recorded.

Timings: not recorded.

Models: not recorded.

</details>
