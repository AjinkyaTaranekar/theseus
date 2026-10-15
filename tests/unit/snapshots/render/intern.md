<!-- theseus:pr-comment -->
## 🔴 Merge blocked

**Your PR says it lets Priya read the app logs. Your change also lets priya-intern reach customer-db.**

#### What happened

This PR adds `aws_iam_user_group_membership.priya_support`.\
Because of that, 3 new ways to reach sensitive data open. The most serious:\
**priya-intern** (a user) is a member of the **support-engineers** group,\
→ which can switch into the **prod-support** role,\
→ which can read the **prod-db-credentials** secret,\
→ which unlocks the **customer-db** database.\
Each of the 3 is under **The path, step by step** below.

#### What's at risk

- **customer-db**, a database: personal, payment or health data, or a key that opens it
- **prod-db-credentials**, a secret: the key that opens **customer-db**
- **demo-company-files/invoices/**, a storage location: business-sensitive data, such as invoices or contracts

#### What the PR said it needs

"Let Priya read the app logs."\
It asks only for: **priya-intern** to read **demo-app-logs/**.

#### What to do

✅ **Reply `/theseus apply B`** to commit fix B: A new support-logs-read role for Priya.\
Theseus tested it on a copy of the graph: it closes all 3 ways in and breaks nothing.\
Or ask the author to change the PR.

Checkov 3.2.255 passed this commit (52 checks). It checks one resource at a time, so it cannot see a path that crosses several.

<details>
<summary><b>The path, step by step</b> (3 ways in, with links to each line)</summary>

| Actor | Target | Hops |
| --- | --- | --- |
| `user:priya-intern` | `db:customer-db` (regulated) | 4 |
| `user:priya-intern` | `secret:prod-db-credentials` (regulated) | 3 |
| `user:priya-intern` | `s3://demo-company-files/invoices/` (confidential) | 3 |

How **priya-intern** reaches **customer-db**

```mermaid
flowchart LR
  n1["user:priya-intern"]
  n2["group:support-engineers"]
  n3["role:prod-support"]
  n4["secret:prod-db-credentials"]
  n5["db:customer-db"]
  n1 -->|MEMBER_OF| n2
  n2 -->|CAN_ASSUME| n3
  n3 -->|CAN| n4
  n4 -->|UNLOCKS| n5
  classDef sensitive fill:#fde2e1,stroke:#c0392b,color:#1f2328
  class n5 sensitive
```

1. `user:priya-intern` → `group:support-engineers` (MEMBER_OF): [terraform/people.tf:20](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L20)
2. `group:support-engineers` → `role:prod-support` (CAN_ASSUME): [terraform/people.tf:30](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L30)
3. `role:prod-support` → `secret:prod-db-credentials` (CAN): [terraform/roles.tf:31](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/roles.tf#L31)
4. `secret:prod-db-credentials` → `db:customer-db` (UNLOCKS): unknown: the secret's db\_instance tag

How **priya-intern** reaches **prod-db-credentials**

```mermaid
flowchart LR
  n1["user:priya-intern"]
  n2["group:support-engineers"]
  n3["role:prod-support"]
  n4["secret:prod-db-credentials"]
  n1 -->|MEMBER_OF| n2
  n2 -->|CAN_ASSUME| n3
  n3 -->|CAN| n4
  classDef sensitive fill:#fde2e1,stroke:#c0392b,color:#1f2328
  class n4 sensitive
```

1. `user:priya-intern` → `group:support-engineers` (MEMBER_OF): [terraform/people.tf:20](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L20)
2. `group:support-engineers` → `role:prod-support` (CAN_ASSUME): [terraform/people.tf:30](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L30)
3. `role:prod-support` → `secret:prod-db-credentials` (CAN): [terraform/roles.tf:31](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/roles.tf#L31)

How **priya-intern** reaches **demo-company-files/invoices/**

```mermaid
flowchart LR
  n1["user:priya-intern"]
  n2["group:support-engineers"]
  n3["role:prod-support"]
  n4["s3://demo-company-files/invoices/"]
  n1 -->|MEMBER_OF| n2
  n2 -->|CAN_ASSUME| n3
  n3 -->|CAN| n4
  classDef sensitive fill:#fde2e1,stroke:#c0392b,color:#1f2328
  class n4 sensitive
```

1. `user:priya-intern` → `group:support-engineers` (MEMBER_OF): [terraform/people.tf:20](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L20)
2. `group:support-engineers` → `role:prod-support` (CAN_ASSUME): [terraform/people.tf:30](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/people.tf#L30)
3. `role:prod-support` → `s3://demo-company-files/invoices/` (CAN): [terraform/roles.tf:24](https://github.com/owner/theseus/blob/0123456789abcdef0123456789abcdef01234567/demo-infra/terraform/roles.tf#L24)

</details>

<details>
<summary><b>All 4 fixes Theseus tested</b>, each on a copy of the graph</summary>

**Smallest change:** No single permission can be removed without breaking required access.

| ID | Fix | Dangerous paths | Required access | Code calls | Verdict |
| --- | --- | --- | --- | --- | --- |
| A | Revert the membership (rule) | all closed | breaks I1 | kept | fail |
| **B** | **A new support-logs-read role for Priya (zai-org/GLM-5.3)** | **all closed** | **kept** | **kept** | **pass** |
| C | Deny Priya on prod-support (rule) | all closed | kept | kept | unknown |
| D | Remove AssumeProdSupport (rule) | 1 left | breaks R2, R3 | kept | fail |

Reply `/theseus apply B` to commit a fix.

</details>

<details>
<summary><b>What Theseus could not check</b> (1)</summary>

- aws\_kms\_key.main: key policy conditions are not modeled

</details>

<details>
<summary><b>Technical details</b></summary>

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
