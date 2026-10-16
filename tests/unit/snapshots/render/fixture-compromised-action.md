<!-- theseus:pr-comment -->
## 🟢 No new access to sensitive data

**stub**

<details>
<summary><b>All 1 fixes Theseus tested</b>, each on a copy of the graph</summary>

| ID | Fix | Dangerous paths | Required access | Code calls | Verdict |
| --- | --- | --- | --- | --- | --- |
| **K** | **Candidate K (rule)** | **all closed** | **kept** | **kept** | **pass** |

Reply `/theseus apply K` to commit a fix.

</details>

<details>
<summary><b>What Theseus checked</b></summary>

Coverage: not recorded.

Timings: not recorded.

Models: not recorded.

</details>

<details>
<summary><b>What is Theseus?</b></summary>

Theseus reviews infrastructure changes as a graph in FalkorDB: who can reach which data, through which groups, roles, secrets and code. It blocks a merge when a change opens a new way to sensitive data, and every step it shows links to the line that causes it.

</details>
