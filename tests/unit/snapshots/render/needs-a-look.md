<!-- theseus:pr-comment -->
## 🟡 Needs a look

**Theseus couldn't check 1 part of this change.** It's listed below.

**The PR says:** rotate the KMS key.\
**It asked for:** no new access\
**Fix:** check what Theseus couldn't, below, before you merge.

<details>
<summary><b>What Theseus couldn't check</b> (1)</summary>

- aws\_kms\_key.main: key policy conditions are not modeled

</details>

<details>
<summary><b>Details</b></summary>

Checkov 3.2.255 passed this commit (52 checks).

**What the change does:** Opens 0 dangerous paths, closes 0.

Coverage: not recorded.

Timings: not recorded.

</details>

<details>
<summary><b>About Theseus</b></summary>

Theseus maps who can reach what in your infrastructure, as a graph in FalkorDB. It blocks a PR that opens a new way to sensitive data, and links every step to the line behind it.

</details>
