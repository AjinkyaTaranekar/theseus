<!-- theseus:pr-comment -->
## 🟡 Needs a look

Theseus could not check 1 thing in this change; see **What Theseus could not check** below.

**Says:** rotate the KMS key.\
**Needs:** no new access, it says\
**Do:** read **What Theseus could not check** below before you merge.

<details>
<summary><b>What Theseus could not check</b> (1)</summary>

- aws\_kms\_key.main: key policy conditions are not modeled

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
