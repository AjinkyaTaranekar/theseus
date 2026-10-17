<!-- theseus:pr-comment -->
## 🟢 No new access to sensitive data

**Theseus traced every path to sensitive data in this commit: none of them is new.**

**The PR says:** let Priya read the app logs.\
**It asked for:** **priya-intern** to read **demo-app-logs/**\
**Fix:** nothing to fix.

<details>
<summary><b>Details</b></summary>

Checkov 3.2.255 passed this commit (52 checks).

**What the change does:** Adds `aws_iam_user_group_membership.priya_support`. Opens 0 dangerous paths, closes 0.

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
