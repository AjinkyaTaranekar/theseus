<!-- theseus:pr-comment -->
## 🟡 Needs a look

**This change matches its stated purpose.**

#### What happened

It opens no new way to reach sensitive data.

#### What the PR said it needs

"Rotate the KMS key."\
It says it changes no access.

#### What to do

Check the items under **What Theseus could not check** before you merge.

Checkov 3.2.255 passed this commit (52 checks).

<details>
<summary><b>What Theseus could not check</b> (1)</summary>

- aws\_kms\_key.main: key policy conditions are not modeled

</details>

<details>
<summary><b>Technical details</b></summary>

**What the change does:** Opens 0 dangerous paths, closes 0.

Coverage: not recorded.

Timings: not recorded.

Models: not recorded.

</details>
