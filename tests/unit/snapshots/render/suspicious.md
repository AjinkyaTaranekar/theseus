<!-- theseus:pr-comment -->
## 🔴 Merge blocked

**This PR would let priya-intern read customer-db**, which holds personal, payment or health data.

> ⚠️ Text in this PR tries to steer the review. Theseus ignored it, and nothing the PR asks for counts as approved.

**The PR says:** let Priya read the app logs.\
**It asked for:** no new access · **It would get:** **customer-db**, **prod-db-credentials** and **demo-company-files/invoices/**\
**How:** **priya-intern** is in **support-engineers** ([terraform/people.tf:20](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L20), new) → can become **prod-support** → can read **prod-db-credentials** → opens **customer-db**.\
**Fix:** reply `/theseus apply B` to commit fix B (A new support-logs-read role for Priya). Tested on a copy of the graph: closes all 3 ways in, breaks nothing.

```mermaid
flowchart LR
  n1["priya-intern<br/>user"]
  n2["support-engineers<br/>group"]
  n3["prod-support<br/>role"]
  n4["prod-db-credentials<br/>secret"]
  n5["customer-db<br/>database"]
  n6["demo-company-files/invoices/<br/>storage location"]
  n1 -->|"is in · new"| n2
  n2 -->|"can become"| n3
  n3 -->|"can read"| n4
  n4 -->|"opens"| n5
  n3 -->|"can read"| n6
  classDef sensitive fill:#ffebe9,stroke:#cf222e,color:#1f2328
  class n4,n5,n6 sensitive
  linkStyle 0 stroke:#cf222e,stroke-width:3px
```

<sub>Red arrow: added by this PR · Shaded: sensitive data</sub>

<details>
<summary><b>Step by step</b> (3 ways in, each linked to its line)</summary>

**What's at risk**

- **customer-db**, a database: personal, payment or health data, or a key that opens it
- **prod-db-credentials**, a secret: the key that opens **customer-db**
- **demo-company-files/invoices/**, a storage location: business-sensitive data, such as invoices or contracts

| Actor | Target | Hops |
| --- | --- | --- |
| `user:priya-intern` | `db:customer-db` (regulated) | 4 |
| `user:priya-intern` | `secret:prod-db-credentials` (regulated) | 3 |
| `user:priya-intern` | `s3://demo-company-files/invoices/` (confidential) | 3 |

How **priya-intern** reaches **customer-db**

1. `user:priya-intern` → `group:support-engineers` (MEMBER_OF): [terraform/people.tf:20](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L20)
2. `group:support-engineers` → `role:prod-support` (CAN_ASSUME): [terraform/people.tf:30](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L30)
3. `role:prod-support` → `secret:prod-db-credentials` (CAN): [terraform/roles.tf:31](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/roles.tf#L31)
4. `secret:prod-db-credentials` → `db:customer-db` (UNLOCKS): unknown: the secret's db\_instance tag

How **priya-intern** reaches **prod-db-credentials**

1. `user:priya-intern` → `group:support-engineers` (MEMBER_OF): [terraform/people.tf:20](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L20)
2. `group:support-engineers` → `role:prod-support` (CAN_ASSUME): [terraform/people.tf:30](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L30)
3. `role:prod-support` → `secret:prod-db-credentials` (CAN): [terraform/roles.tf:31](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/roles.tf#L31)

How **priya-intern** reaches **demo-company-files/invoices/**

1. `user:priya-intern` → `group:support-engineers` (MEMBER_OF): [terraform/people.tf:20](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L20)
2. `group:support-engineers` → `role:prod-support` (CAN_ASSUME): [terraform/people.tf:30](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L30)
3. `role:prod-support` → `s3://demo-company-files/invoices/` (CAN): [terraform/roles.tf:24](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/roles.tf#L24)

</details>

<details>
<summary><b>The fix that passes</b>, tested on a copy of the graph</summary>

**Smallest change:** No single permission can be removed without breaking required access.

| ID | Fix | Dangerous paths | Required access | Code calls | Verdict |
| --- | --- | --- | --- | --- | --- |
| **B** | **A new support-logs-read role for Priya (zai-org/GLM-5.3)** | **all closed** | **kept** | **kept** | **pass** |

Theseus also tried A (fail), C (unknown) and D (fail), which don't pass. The review page draws each one.

Reply `/theseus apply B` to commit a fix.

</details>

<details>
<summary><b>What Theseus couldn't check</b> (1)</summary>

- aws\_kms\_key.main: key policy conditions are not modeled

</details>

<details>
<summary><b>Details</b></summary>

Checkov 3.2.255 passed this commit (52 checks). It checks one resource at a time, so it cannot see a path that crosses several.

**What the change does:** Adds `aws_iam_user_group_membership.priya_support`. Opens 3 dangerous paths, closes 0.

**Tool calls**

| # | Tool | Summary | ms |
| --- | --- | --- | --- |
| 1 | `explain_path` | P1: 5 hops to db:customer-db | 12 |
| 2 | `min_cut` | value 1000000, not cuttable | 48 |
| 3 | `simulate_fix` | B passes | 310 |

**Unchanged paths**

| Actor | Target | Hops |
| --- | --- | --- |
| `user:priya-intern` | `s3://demo-app-logs/` (internal) | 2 |

Read 46 resources, modeled 31; skipped 15 of types Theseus does not model, such as `aws_cloudwatch_metric_alarm` (6), `aws_sns_topic` (5) and `aws_kms_alias` (2).

Took 9.6 s: engine 1.2 s, LLM 8.0 s, Jev 0.3 s.

Models: LLM `zai-org/GLM-5.3`, Jev `jev-1.13.0`.

</details>

<details>
<summary><b>About Theseus</b></summary>

Theseus maps who can reach what in your infrastructure, as a graph in FalkorDB. It blocks a PR that opens a new way to sensitive data, and links every step to the line behind it.

</details>
