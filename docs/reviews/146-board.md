# Whole-repository audit for #146

Audited **18 October 2026** against GitHub issue/PR records and main
`591d0aaa42ecaee096a39b46d8c227ad2b0deac4`. [Slack design](../tasks/146.md).

## What is actually done

- **64 issues:** 47 closed, 17 open. **93 PRs:** 79 merged, 9 open, 5 closed without merge.
- Every one of the 79 GitHub-reported merge commits is an ancestor of the audited main, verified locally
  with `git merge-base --is-ancestor`. Merged PR status alone was not treated as proof of source presence.
- Finding analysis, optional urgency, K simulation, proposal publication, signed pages, posture persistence,
  ranking/veto, graph hygiene, MCP startup and the UX work are already on main.
- #140, #151, #152, #153, #154, #155, #157 and #158 are now merged through #159; #156 is merged afterward.
  The older #143 audit predates that integration. Do not carry its “#151 is unmerged” conclusion forward.
- Open PRs are committed proposals, not merged capabilities. The six open demo PRs and the containment PR
  are demo artifacts, not seven independent product features waiting for implementation.
- At audit start the user checkout was `scanner-findings` at `9473f96`, with dirty AWS resource/test edits and an
  untracked #143 PR draft. Its committed neutral-finding contract and parser work are not on main. Those
  files were left alone. The scanner session continued independently during this audit (later observed at
  `4169a69`); that activity is not #146 work. #146 uses its own managed worktree and `slack-alert` branch
  from verified main.

### Evidence limits

The connector returned 404 for this private issue; authenticated `gh` read the issue, all issues and all PRs.
`gh project list --owner AjinkyaTaranekar --format json` failed because the token lacks **read:project**.
Thus this is a complete issue/PR/dependency audit, **not a verified snapshot of project columns, custom fields,
draft cards, card ordering or assignments made only on the project**. No board field was guessed or changed.
A browser fallback also showed a logged-out GitHub 404, so it did not reveal the private project. No
authentication scope was changed. No GitHub comment, issue edit, review, push, merge or deployment was made.

Issue closure records human/project status, not fresh verification of every acceptance criterion. Code
presence and local tests do not prove a saved rehearsal clip, public uptime, a submitted form, a rotated secret,
or both humans' approval. Dependencies below come from issue bodies and `tools/tasks.csv`; later tasks'
coordination dependencies are labeled separately. This report is an audit snapshot, not an edited schedule. S5 #41 is closed although its declared G2/G3
dependencies remain open: its documentation merged earlier, but that is not evidence those gates passed.
Keep the issue state and remaining acceptance evidence distinct rather than silently rewriting the schedule.

## Dependency decisions for Slack

| Dependency | Status / evidence | How #146 uses it |
| --- | --- | --- |
| FM3 #32 and O1 #103 | #89/#98/#109 merged | Typed finding results and posture orchestration |
| FM4 #33 / A2 #17 | #92/#53 merged | Optional `urgency = {p, source}`; no invented default |
| FM6 #35 / E5 #25 / E9 #27 / A9 #30 | #113/#77/#76/#102/#115 merged | Existing verified proposal, real links and world-root fence |
| #149 | #151 merged through #159 | Preserve passing-but-vetoed K publication and explicit warning |
| #147 | #156 merged | Use current routes/reviews; do not overwrite graph lifecycle changes |
| #143 | Local work, no merged PR | Future overlap in app/routes/reviews; not a blocker for Action alerts |
| #142 | Open | App startup/pipeline coordination; Slack adds no graph calls and must stay bounded |
| #141 | Open, #140 merged | Relevant only to optional database verification; not an offline implementation blocker |
| #69 / #144 / #148 / S2 | Open | No Slack prerequisite; do not bundle traversal, agent prompts or benchmark results |

No unmerged issue is a mandatory code prerequisite for #146. Its actual blocking choices are notification
policy and the single-process/deduplication limits in the [design](../tasks/146.md#decisions-to-approve-before-implementation).

## Complete issue inventory

“Needs” lists declared task dependencies; the evidence column distinguishes merged code, open commits and
human-only work. PR links can include a closed original branch when integration delivered it later.

| Issue / task | State | Needs | PR evidence and disposition |
| --- | --- | --- | --- |
| [#1](https://github.com/AjinkyaTaranekar/theseus/issues/1) P1: Throwaway checks: FalkorDB and Terraform plan | CLOSED | — | Closed human throwaway checks; do not rerun against a real cloud. |
| [#2](https://github.com/AjinkyaTaranekar/theseus/issues/2) P3: Check the five scenarios on paper | CLOSED | — | [#45](https://github.com/AjinkyaTaranekar/theseus/pull/45) — P3 acceptance recorded; answer keys remain human-owned. |
| [#3](https://github.com/AjinkyaTaranekar/theseus/issues/3) P4: Finalize the video script | OPEN | [#2](https://github.com/AjinkyaTaranekar/theseus/issues/2) P3 | PR #116 committed but unmerged; narrator, timed read and teammate review remain. |
| [#4](https://github.com/AjinkyaTaranekar/theseus/issues/4) P5: Check access and keys | CLOSED | — | Closed access check; keys are not read or printed in this audit. |
| [#5](https://github.com/AjinkyaTaranekar/theseus/issues/5) P6: Register the team and agree IP ownership | CLOSED | — | Closed registration/IP task; legal/team acceptance is human-owned. |
| [#6](https://github.com/AjinkyaTaranekar/theseus/issues/6) P7: Rehearse the judge questions | OPEN | [#2](https://github.com/AjinkyaTaranekar/theseus/issues/2) P3 | Human rehearsal still open; no code prerequisite remains. |
| [#7](https://github.com/AjinkyaTaranekar/theseus/issues/7) F1: Repo, board and CI | CLOSED | [#4](https://github.com/AjinkyaTaranekar/theseus/issues/4) P5 | [#46](https://github.com/AjinkyaTaranekar/theseus/pull/46) — Package/CI skeleton present. |
| [#8](https://github.com/AjinkyaTaranekar/theseus/issues/8) F2: Freeze the contracts | CLOSED | [#7](https://github.com/AjinkyaTaranekar/theseus/issues/7) F1 | [#47](https://github.com/AjinkyaTaranekar/theseus/pull/47) — Frozen contracts present; future changes still require both humans. |
| [#9](https://github.com/AjinkyaTaranekar/theseus/issues/9) F4: Demo world and fixture generator | CLOSED | [#7](https://github.com/AjinkyaTaranekar/theseus/issues/7) F1 | [#59](https://github.com/AjinkyaTaranekar/theseus/pull/59) — World/generator present; regenerate inputs through tools only. |
| [#10](https://github.com/AjinkyaTaranekar/theseus/issues/10) F3: Run it: Compose, API stub and VM deploy | CLOSED | [#8](https://github.com/AjinkyaTaranekar/theseus/issues/8) F2 | [#49](https://github.com/AjinkyaTaranekar/theseus/pull/49) — API/deploy exists; current public uptime was not checked. |
| [#11](https://github.com/AjinkyaTaranekar/theseus/issues/11) F5: Hand-write expected.json | CLOSED | [#9](https://github.com/AjinkyaTaranekar/theseus/issues/9) F4, [#2](https://github.com/AjinkyaTaranekar/theseus/issues/2) P3 | [#70](https://github.com/AjinkyaTaranekar/theseus/pull/70) — Answer keys committed; never change them to fit code. |
| [#12](https://github.com/AjinkyaTaranekar/theseus/issues/12) F7: GitHub Action and App skeleton | CLOSED | [#8](https://github.com/AjinkyaTaranekar/theseus/issues/8) F2, [#10](https://github.com/AjinkyaTaranekar/theseus/issues/10) F3 | [#60](https://github.com/AjinkyaTaranekar/theseus/pull/60) — Action/App code merged; a fresh live gate is separate. |
| [#13](https://github.com/AjinkyaTaranekar/theseus/issues/13) E1: Importer: plan, structure, workloads and coverage | CLOSED | [#8](https://github.com/AjinkyaTaranekar/theseus/issues/8) F2, [#9](https://github.com/AjinkyaTaranekar/theseus/issues/9) F4 | [#61](https://github.com/AjinkyaTaranekar/theseus/pull/61) — Importer present. |
| [#14](https://github.com/AjinkyaTaranekar/theseus/issues/14) E2: IAM: statements, matching, CAN and CAN_ASSUME | CLOSED | [#8](https://github.com/AjinkyaTaranekar/theseus/issues/8) F2 | [#50](https://github.com/AjinkyaTaranekar/theseus/pull/50) — IAM adapter/catalog present. |
| [#15](https://github.com/AjinkyaTaranekar/theseus/issues/15) E3: Graph load, path diff and required access | CLOSED | [#13](https://github.com/AjinkyaTaranekar/theseus/issues/13) E1, [#14](https://github.com/AjinkyaTaranekar/theseus/issues/14) E2, [#10](https://github.com/AjinkyaTaranekar/theseus/issues/10) F3, [#11](https://github.com/AjinkyaTaranekar/theseus/issues/11) F5 | [#72](https://github.com/AjinkyaTaranekar/theseus/pull/72) — Graph loading, path analysis and requirements present. |
| [#16](https://github.com/AjinkyaTaranekar/theseus/issues/16) A1: LLM intent extraction | CLOSED | [#8](https://github.com/AjinkyaTaranekar/theseus/issues/8) F2 | [#51](https://github.com/AjinkyaTaranekar/theseus/pull/51), [#53](https://github.com/AjinkyaTaranekar/theseus/pull/53) — Intent extraction/wrapper merged. |
| [#17](https://github.com/AjinkyaTaranekar/theseus/issues/17) A2: Jev: sensitivity labels and advisory urgency | CLOSED | [#8](https://github.com/AjinkyaTaranekar/theseus/issues/8) F2 | [#53](https://github.com/AjinkyaTaranekar/theseus/pull/53) — Jev sensitivity/urgency wrapper and replay present. |
| [#18](https://github.com/AjinkyaTaranekar/theseus/issues/18) A3: Says versus grants | CLOSED | [#15](https://github.com/AjinkyaTaranekar/theseus/issues/15) E3, [#16](https://github.com/AjinkyaTaranekar/theseus/issues/16) A1 | [#73](https://github.com/AjinkyaTaranekar/theseus/pull/73) — Intent-versus-effect code present. |
| [#19](https://github.com/AjinkyaTaranekar/theseus/issues/19) A4: PR comment: paths, fix table, trace and coverage | CLOSED | [#8](https://github.com/AjinkyaTaranekar/theseus/issues/8) F2 | [#55](https://github.com/AjinkyaTaranekar/theseus/pull/55) — Comment rendering present. |
| [#20](https://github.com/AjinkyaTaranekar/theseus/issues/20) A5: Real analyze behind the Action | CLOSED | [#15](https://github.com/AjinkyaTaranekar/theseus/issues/15) E3, [#18](https://github.com/AjinkyaTaranekar/theseus/issues/18) A3, [#19](https://github.com/AjinkyaTaranekar/theseus/issues/19) A4, [#12](https://github.com/AjinkyaTaranekar/theseus/issues/12) F7 | [#74](https://github.com/AjinkyaTaranekar/theseus/pull/74) — Analyze route composition present. |
| [#21](https://github.com/AjinkyaTaranekar/theseus/issues/21) FM1: CI in the graph: workflows and OIDC trust | CLOSED | [#9](https://github.com/AjinkyaTaranekar/theseus/issues/9) F4, [#14](https://github.com/AjinkyaTaranekar/theseus/issues/14) E2 | [#71](https://github.com/AjinkyaTaranekar/theseus/pull/71) — Workflows/OIDC adapters present. |
| [#22](https://github.com/AjinkyaTaranekar/theseus/issues/22) C1: Demo backend: service code and platform resources | CLOSED | [#9](https://github.com/AjinkyaTaranekar/theseus/issues/9) F4 | [#64](https://github.com/AjinkyaTaranekar/theseus/pull/64) — Backend source is present; do not edit outside approved task. |
| [#23](https://github.com/AjinkyaTaranekar/theseus/issues/23) G1: Gate 1: Beat 1 live | OPEN | [#20](https://github.com/AjinkyaTaranekar/theseus/issues/20) A5 | A5 is merged; fresh live capture and both-human observation still pending. |
| [#24](https://github.com/AjinkyaTaranekar/theseus/issues/24) E4: Minimum cut with MaxFlow | CLOSED | [#15](https://github.com/AjinkyaTaranekar/theseus/issues/15) E3, [#18](https://github.com/AjinkyaTaranekar/theseus/issues/18) A3 | [#78](https://github.com/AjinkyaTaranekar/theseus/pull/78) — Min-cut implementation present. |
| [#25](https://github.com/AjinkyaTaranekar/theseus/issues/25) E5: Simulator on GRAPH.COPY | CLOSED | [#15](https://github.com/AjinkyaTaranekar/theseus/issues/15) E3 | [#77](https://github.com/AjinkyaTaranekar/theseus/pull/77) — Graph-copy simulation present. |
| [#26](https://github.com/AjinkyaTaranekar/theseus/issues/26) E6: Rule-based fixes and ranking | CLOSED | [#25](https://github.com/AjinkyaTaranekar/theseus/issues/25) E5 | [#90](https://github.com/AjinkyaTaranekar/theseus/pull/90) — Rule candidates and ranking present. |
| [#27](https://github.com/AjinkyaTaranekar/theseus/issues/27) E9: Terraform patch renderer | CLOSED | [#8](https://github.com/AjinkyaTaranekar/theseus/issues/8) F2, [#9](https://github.com/AjinkyaTaranekar/theseus/issues/9) F4 | [#76](https://github.com/AjinkyaTaranekar/theseus/pull/76) — Verified Terraform renderer present. |
| [#28](https://github.com/AjinkyaTaranekar/theseus/issues/28) A6: MCP server and tool trace | CLOSED | [#8](https://github.com/AjinkyaTaranekar/theseus/issues/8) F2 | [#93](https://github.com/AjinkyaTaranekar/theseus/pull/93) — Registry/server present; startup fix also merged in #152. |
| [#29](https://github.com/AjinkyaTaranekar/theseus/issues/29) A7: LLM fix agent | CLOSED | [#25](https://github.com/AjinkyaTaranekar/theseus/issues/25) E5, [#28](https://github.com/AjinkyaTaranekar/theseus/issues/28) A6 | [#110](https://github.com/AjinkyaTaranekar/theseus/pull/110) — Fix agent present; visible retry proof remains #144. |
| [#30](https://github.com/AjinkyaTaranekar/theseus/issues/30) A9: /theseus apply command | CLOSED | [#12](https://github.com/AjinkyaTaranekar/theseus/issues/12) F7, [#27](https://github.com/AjinkyaTaranekar/theseus/issues/27) E9 | [#102](https://github.com/AjinkyaTaranekar/theseus/pull/102), [#115](https://github.com/AjinkyaTaranekar/theseus/pull/115) — Apply code present; G2 must still demonstrate it live. |
| [#31](https://github.com/AjinkyaTaranekar/theseus/issues/31) C2: Python code reader | CLOSED | [#8](https://github.com/AjinkyaTaranekar/theseus/issues/8) F2, [#22](https://github.com/AjinkyaTaranekar/theseus/issues/22) C1 | [#65](https://github.com/AjinkyaTaranekar/theseus/pull/65) — Python reader present; broader traversal remains #69. |
| [#32](https://github.com/AjinkyaTaranekar/theseus/issues/32) FM3: Finding mode: blast radius and rotate list | CLOSED | [#21](https://github.com/AjinkyaTaranekar/theseus/issues/21) FM1, [#15](https://github.com/AjinkyaTaranekar/theseus/issues/15) E3 | [#89](https://github.com/AjinkyaTaranekar/theseus/pull/89), [#98](https://github.com/AjinkyaTaranekar/theseus/pull/98) — Finding results and signed pages present. |
| [#33](https://github.com/AjinkyaTaranekar/theseus/issues/33) FM4: Finding extras: choke points, staging to prod, urgency | CLOSED | [#32](https://github.com/AjinkyaTaranekar/theseus/issues/32) FM3, [#24](https://github.com/AjinkyaTaranekar/theseus/issues/24) E4, [#17](https://github.com/AjinkyaTaranekar/theseus/issues/17) A2 | [#92](https://github.com/AjinkyaTaranekar/theseus/pull/92) — Urgency present but optional; no Slack urgency cutoff is specified. |
| [#34](https://github.com/AjinkyaTaranekar/theseus/issues/34) G2: Gate 2: Demo 2 end to end | OPEN | [#23](https://github.com/AjinkyaTaranekar/theseus/issues/23) G1, [#24](https://github.com/AjinkyaTaranekar/theseus/issues/24) E4, [#26](https://github.com/AjinkyaTaranekar/theseus/issues/26) E6, [#29](https://github.com/AjinkyaTaranekar/theseus/issues/29) A7, [#30](https://github.com/AjinkyaTaranekar/theseus/issues/30) A9 | Code prerequisites merged; G1/capture still open. |
| [#35](https://github.com/AjinkyaTaranekar/theseus/issues/35) FM6: Containment PR | CLOSED | [#32](https://github.com/AjinkyaTaranekar/theseus/issues/32) FM3, [#24](https://github.com/AjinkyaTaranekar/theseus/issues/24) E4, [#25](https://github.com/AjinkyaTaranekar/theseus/issues/25) E5, [#27](https://github.com/AjinkyaTaranekar/theseus/issues/27) E9, [#30](https://github.com/AjinkyaTaranekar/theseus/issues/30) A9 | [#113](https://github.com/AjinkyaTaranekar/theseus/pull/113) — Containment proposals and rotate issues present; never equate a PR with a deployed fix. |
| [#36](https://github.com/AjinkyaTaranekar/theseus/issues/36) C3: Unused grants, with usage capacities | CLOSED | [#31](https://github.com/AjinkyaTaranekar/theseus/issues/31) C2, [#24](https://github.com/AjinkyaTaranekar/theseus/issues/24) E4, [#25](https://github.com/AjinkyaTaranekar/theseus/issues/25) E5 | [#91](https://github.com/AjinkyaTaranekar/theseus/pull/91), [#97](https://github.com/AjinkyaTaranekar/theseus/pull/97), [#99](https://github.com/AjinkyaTaranekar/theseus/pull/99) — Original PR #91 is closed; integration commits, not PR state alone, supply C3. |
| [#37](https://github.com/AjinkyaTaranekar/theseus/issues/37) C4: Use beyond intent | CLOSED | [#31](https://github.com/AjinkyaTaranekar/theseus/issues/31) C2, [#18](https://github.com/AjinkyaTaranekar/theseus/issues/18) A3 | [#101](https://github.com/AjinkyaTaranekar/theseus/pull/101) — Use-beyond-intent present. |
| [#38](https://github.com/AjinkyaTaranekar/theseus/issues/38) G3: Gate 3: Contain it and nobody breaks | OPEN | [#34](https://github.com/AjinkyaTaranekar/theseus/issues/34) G2, [#33](https://github.com/AjinkyaTaranekar/theseus/issues/33) FM4, [#35](https://github.com/AjinkyaTaranekar/theseus/issues/35) FM6, [#36](https://github.com/AjinkyaTaranekar/theseus/issues/36) C3, [#37](https://github.com/AjinkyaTaranekar/theseus/issues/37) C4 | Code prerequisites merged; G2/capture still open. |
| [#39](https://github.com/AjinkyaTaranekar/theseus/issues/39) S2: Proof: benchmark against Checkov, and large-graph timings | OPEN | [#24](https://github.com/AjinkyaTaranekar/theseus/issues/24) E4, [#25](https://github.com/AjinkyaTaranekar/theseus/issues/25) E5 | Draft PR #117 committed but unmerged; human keys and measured report still required. |
| [#40](https://github.com/AjinkyaTaranekar/theseus/issues/40) S4: Try-it page | CLOSED | [#20](https://github.com/AjinkyaTaranekar/theseus/issues/20) A5 | [#95](https://github.com/AjinkyaTaranekar/theseus/pull/95), [#108](https://github.com/AjinkyaTaranekar/theseus/pull/108) — Try-it exists; replay visitor actions must not alert Slack. |
| [#41](https://github.com/AjinkyaTaranekar/theseus/issues/41) S5: README | CLOSED | [#34](https://github.com/AjinkyaTaranekar/theseus/issues/34) G2, [#38](https://github.com/AjinkyaTaranekar/theseus/issues/38) G3 | [#133](https://github.com/AjinkyaTaranekar/theseus/pull/133), [#139](https://github.com/AjinkyaTaranekar/theseus/pull/139) — README merged; release numbers/sign-offs still checked on tagged commit. |
| [#42](https://github.com/AjinkyaTaranekar/theseus/issues/42) S6: Final video | OPEN | [#38](https://github.com/AjinkyaTaranekar/theseus/issues/38) G3, [#3](https://github.com/AjinkyaTaranekar/theseus/issues/3) P4 | Waits on G3 and P4; no uploaded video verified. |
| [#43](https://github.com/AjinkyaTaranekar/theseus/issues/43) S7: Tag the release and submit | OPEN | [#41](https://github.com/AjinkyaTaranekar/theseus/issues/41) S5, [#42](https://github.com/AjinkyaTaranekar/theseus/issues/42) S6 | Waits on video; public visibility/tag/submission are human actions. |
| [#44](https://github.com/AjinkyaTaranekar/theseus/issues/44) S8: Blog post | OPEN | [#42](https://github.com/AjinkyaTaranekar/theseus/issues/42) S6 | After video/submission; optional side-prize work. |
| [#57](https://github.com/AjinkyaTaranekar/theseus/issues/57) Reject LLM answers the model cut short | CLOSED | F1/F2 | [#67](https://github.com/AjinkyaTaranekar/theseus/pull/67) — Incomplete model response rejection merged. |
| [#58](https://github.com/AjinkyaTaranekar/theseus/issues/58) Retry LLM API errors with a 5xx status | CLOSED | F1/F2 | [#68](https://github.com/AjinkyaTaranekar/theseus/pull/68) — API retry by status merged. |
| [#63](https://github.com/AjinkyaTaranekar/theseus/issues/63) Make the demo world demo-ready before F5 | CLOSED | F4/C1 before human F5 | [#59](https://github.com/AjinkyaTaranekar/theseus/pull/59), [#64](https://github.com/AjinkyaTaranekar/theseus/pull/64) — Demo/importer and human keys later merged; task closed. |
| [#69](https://github.com/AjinkyaTaranekar/theseus/issues/69) Design: paths through services, exposure, and other languages | OPEN | G3 before expansion; both-human design approval | Design only; traversal/EXPOSES/new-language rules need both humans. |
| [#103](https://github.com/AjinkyaTaranekar/theseus/issues/103) O1: Posture of main, on push, nightly and on demand | CLOSED | Existing E3/C3/FM3 | [#109](https://github.com/AjinkyaTaranekar/theseus/pull/109) — Posture pipeline, scheduled workflow and persistence merged. |
| [#104](https://github.com/AjinkyaTaranekar/theseus/issues/104) O2: Single points of failure and articulation points | CLOSED | #103 | [#109](https://github.com/AjinkyaTaranekar/theseus/pull/109) — Posture single-point/articulation analysis present. |
| [#105](https://github.com/AjinkyaTaranekar/theseus/issues/105) O3: Cost estimate and savings | CLOSED | #103; cloud adapter protocol approval | [#109](https://github.com/AjinkyaTaranekar/theseus/pull/109), [#157](https://github.com/AjinkyaTaranekar/theseus/pull/157) — Cost estimate/proof code merged; estimates are not live bills. |
| [#106](https://github.com/AjinkyaTaranekar/theseus/issues/106) O4: Organisation dashboard | CLOSED | #103–#105 | [#109](https://github.com/AjinkyaTaranekar/theseus/pull/109), [#114](https://github.com/AjinkyaTaranekar/theseus/pull/114), [#158](https://github.com/AjinkyaTaranekar/theseus/pull/158) — Dashboard and UX merged. |
| [#107](https://github.com/AjinkyaTaranekar/theseus/issues/107) O5: Onboarding: connect a repository | CLOSED | #103/#106 | [#109](https://github.com/AjinkyaTaranekar/theseus/pull/109) — Onboarding/allowlisting present. |
| [#112](https://github.com/AjinkyaTaranekar/theseus/issues/112) Rotate these secrets: GHSA-demo-0001 | OPEN | Finding artifact #111; human decision | Open synthetic rotate issue; a task artifact, not an engine dependency. |
| [#141](https://github.com/AjinkyaTaranekar/theseus/issues/141) Clean up and prevent leaked test graphs on the shared FalkorDB Cloud instance | OPEN | PR #140 (merged); human cleanup review | PR #140 prevents new leaks; old-graph cleanup/headroom work remains open. |
| [#142](https://github.com/AjinkyaTaranekar/theseus/issues/142) Cut a live review from ~58 s to under 10 s | OPEN | GraphStore approval; deployment placement decision | Batching, placement and timings unmerged; store protocol needs approval. |
| [#143](https://github.com/AjinkyaTaranekar/theseus/issues/143) Read Trivy and Grype reports as findings | OPEN | Neutral design/fixture approval; #149 merged | Unfinished local scanner commits exist; no merged scanner capability claimed. |
| [#144](https://github.com/AjinkyaTaranekar/theseus/issues/144) Show the agent choosing tools and correcting a fix | OPEN | Existing A7; prompt changes need approval | Live recording/replay proof remains; do not script or fabricate a retry. |
| [#145](https://github.com/AjinkyaTaranekar/theseus/issues/145) Start the MCP server on any machine | CLOSED | Existing A6 | [#152](https://github.com/AjinkyaTaranekar/theseus/pull/152) — Startup/docs merged; do not infer a completed human video capture from closure. |
| [#146](https://github.com/AjinkyaTaranekar/theseus/issues/146) Post findings to a Slack webhook | OPEN | FM3/FM4/FM6/O1; all merged | This local design only; product implementation awaits the explicit policy decisions. |
| [#147](https://github.com/AjinkyaTaranekar/theseus/issues/147) Delete a PR's graphs when it closes | CLOSED | Existing review graph lifecycle; coordinated with #141 | [#156](https://github.com/AjinkyaTaranekar/theseus/pull/156) — Graph lifecycle merged; no shared-instance prune was performed here. |
| [#148](https://github.com/AjinkyaTaranekar/theseus/issues/148) Measure Jev on the whole demo world | OPEN | Human labels; coordinate #39/#117 | Human labels and live measurement required; no new accuracy claim. |
| [#149](https://github.com/AjinkyaTaranekar/theseus/issues/149) Rank the containment fix like the rest | CLOSED | Existing FM3; golden-key approval | [#151](https://github.com/AjinkyaTaranekar/theseus/pull/151) — Ranking/veto behavior merged; vetoed passing K may still open a proposal. |
| [#150](https://github.com/AjinkyaTaranekar/theseus/issues/150) Bring the docs up to date for release | CLOSED | Actual tag-time checks and human sign-offs | [#154](https://github.com/AjinkyaTaranekar/theseus/pull/154) — Release docs merged; unresolved human sign-offs must not be invented. |

## Design and handoff for every open issue

These are proposed next actions within the existing issue scopes. They do not claim new team assignments,
change dependencies in the generated schedule, or authorize live/cloud/publishing actions.

| Open work | Concrete next implementation or human action | Acceptance / handoff |
| --- | --- | --- |
| #3 P4 | Review committed script PR #116 against current UI; select narrator/operator; perform a timed read; record duration in its existing plan document | Both humans review and the script fits the video budget; then merge script normally |
| #6 P7 | Rehearse capacities, residual cut, OIDC, evidence, UNKNOWN, model versus engine and demo limits from the plan | Each teammate explains the implementation without relying on generated prose; no product file ownership needed |
| #23 G1 | Use a fresh demo branch, capture the live intern finding, three opened paths and stated versus effective access | Both humans watch; save a usable clip. Existing PR #125 is context, not proof of a fresh gate |
| #34 G2 | After G1, capture candidate outcomes, approved `/theseus apply B`, resulting commit, rerun and green check | Keep reviewed SHA, requirement/call preservation and clip together; product code is already merged |
| #38 G3 | After G2, capture finding → proposal/rotate issue, unused-grant U verification, and code-PR flag | Three live beats with clips; #111/#112 show artifacts exist but not that the gate was completed |
| #39 S2 / #117 | Continue the existing benchmark branch, not a new harness: generate inputs through tools, obtain human answer keys, prepare real wrapper recordings, run Checkov and measured graph timings | Report catches/misses/unknowns honestly, exact input/code digests, machine/database and latency conditions; draft tooling is not a finished result |
| #42 S6 | Build the final video from approved #3 script and #23/#34/#38 clips, with only measured/implemented claims | Human reviews and uploads; record the usable artifact. A recording plan is not an upload |
| #43 S7 | On the chosen release commit, rerun release checks, reconcile README numbers, finish human AI_USE sign-offs and verify judge access | Humans approve making public, tagging and submitting Track 01; keep tag/form/video consistent |
| #44 S8 | After submission, write the implementation story using actual results, evidence links and disclosed AI use | Optional side-prize publication; do not delay the primary submission |
| #69 | Keep the design split into indirect service paths, exposure edges and new code readers; obtain explicit contract/traversal approval for each | After G3 only; separate inferred paths from IAM verdicts. Never make REQUESTS/CALLS permission paths implicitly |
| #112 | Treat rotation as a human operational/demo action, not an unresolved implementation dependency | Do not call a cloud account or claim this synthetic secret was rotated. Closing/merging artifacts requires a separate human action |
| #141 | Build the scoped dry-run purge and offline name-selection tests, add a measured-headroom guard only for explicit database runs, and document local containers | Reuse #147 memory helpers where appropriate; never select product/docs/fixture graphs; human reviews and performs shared-instance deletion |
| #142 | Approve additive `paths_many`; tests first for output parity; batch queries/listing per run; integrate startup warming and measure host placement | Preserve golden keys; benchmark on the actual host and record placement. Batching alone does not prove the under-10-second goal |
| #143 | Continue existing scanner design/branch: approve neutral shape and image matching; preserve adapter boundaries; finish world integration, honest acceptance fixture, engine simulation, API/feed/page and parity | Humans author/save the answer key. Workload findings use verified supported fixes, not Action-only K. Coordinate new finding-document metadata with #146 |
| #144 | Record a real live fixer run through existing wrappers, with tool diversity and correction visible; add deterministic replay assertions and check the UI trace | No fabricated trace or scripted failure; obtain approval before changing prompts. Optional finding/scan agent is a separate design |
| #146 | Implement the reviewed [Slack design](../tasks/146.md) tests first: safe typed payload, secret-safe transport, persistent receipt and route orchestration | Resolve cutoff/delivery/concurrency rules, verify two full runs, then user reviews before push |
| #148 | Keep Jev work under `bench/jev/`; obtain human labels; call the existing live wrapper and fallback; compute confusion, Brier and latency metrics from saved answers | Independent of #146; no fabricated accuracy, no live calls here. Coordinate README with S2 and tag-time docs |

### How to work together without file conflicts

| Area | Current owner work | Integration rule |
| --- | --- | --- |
| `api/routes.py`, `api/reviews.py` | #146 notification lifecycle; #143 future finding ingestion | Land small receipt/preservation changes against current main; then merge into scanner work; do not replace whole functions from an old branch |
| `api/app.py` | #142 startup warming; #143 parsers; #146 notifier lifecycle | Keep construction in app, injectable dependencies in routes, and client shutdown in lifespan; explicitly review the combined startup diff |
| `engine/pipeline.py`, graph protocols | #142 latency and #143 image analysis | #146 has no reason to edit engine/contracts. Approval for #143's contract is not approval for #142's protocol |
| `bench/` and README | #39/#117 benchmark; #148 Jev measurement; release checks | Keep Jev artifacts in its subfolder, retain human key ownership, and publish only measured tables |
| Deploy docs and AI_USE | Every relevant task; #150 already merged | Append truthful task-specific changes; preserve previous sign-offs and sanitized placeholders |
| Demo inputs and expected files | Human/fixture ownership | Generate source/plans only through tools; humans save answer keys. Slack requires no Terraform change |

Do not expand the original CSV schedule in this audit. If the team changes declared task dependencies,
update `tools/tasks.csv`, the corresponding briefs and `docs/plan-of-action.md` together, then regenerate
`docs/tasks/dependencies.md` with `tools/dep_graph.py`; never hand-edit that generated file.

### Suggested completion order

1. Finish P4/P7 and the G1 → G2 → G3 captures using the already merged product. Continue S2 acceptance alongside
   those human activities. Keep those as the hackathon critical path.
2. Finish S6, tag-time validation/sign-offs, judge access and S7. S8 follows submission.
3. Take optional product work only when it helps those demonstrations: #142 responsiveness, #144 visible
   agent correction, approved #143 scanner expansion, and optional #146 alerting. They are separate PRs.
4. #141 operational cleanup proceeds with human review; #148 produces measured evidence independently.
   Neither authorizes touching a shared cloud resource from this Slack design review.

## Complete PR inventory and commit presence

Every row was read from GitHub. “In main” means its reported merge commit is an ancestor of the audited
baseline; open/closed PRs have no merge commit. Head SHAs show committed branch state, not working-tree edits.
This audit does not certify every historical CI run or human sign-off.

| PR / title | State | Branch | Head | Merge commit | In main |
| --- | --- | --- | --- | --- | --- |
| [#45](https://github.com/AjinkyaTaranekar/theseus/pull/45) docs: Record scenario review notes | MERGED | `p3-check-the-five-scenarios-on-paper` | `eee2fd1b` | `b7d43ad0` | yes |
| [#46](https://github.com/AjinkyaTaranekar/theseus/pull/46) chore: Add the package skeleton and CI | MERGED | `f1-repo-skeleton` | `31659318` | `0115c400` | yes |
| [#47](https://github.com/AjinkyaTaranekar/theseus/pull/47) feat: Freeze vendor-neutral contracts | MERGED | `f2-contracts` | `487e3f9b` | `8d37f456` | yes |
| [#49](https://github.com/AjinkyaTaranekar/theseus/pull/49) feat: Run the API on FalkorDB Cloud | MERGED | `f3-run-it` | `1c0fe4a3` | `936d343e` | yes |
| [#50](https://github.com/AjinkyaTaranekar/theseus/pull/50) feat: Add the IAM evaluator and AWS catalog | MERGED | `e2-iam` | `34ec3e6e` | `20f00ba6` | yes |
| [#51](https://github.com/AjinkyaTaranekar/theseus/pull/51) feat: Extract PR intent through the LLM wrapper | MERGED | `a1-intent` | `d58c552f` | `c27cb8a0` | yes |
| [#52](https://github.com/AjinkyaTaranekar/theseus/pull/52) docs: Let PR words explain, never approve | MERGED | `intent-never-approves` | `018a3f08` | `635c8479` | yes |
| [#53](https://github.com/AjinkyaTaranekar/theseus/pull/53) feat: Add Jev for sensitivity, urgency, steering | MERGED | `a2-jev` | `90cf4d84` | `c27cb8a0` | yes |
| [#55](https://github.com/AjinkyaTaranekar/theseus/pull/55) feat: Render the PR comment from a result | MERGED | `a4-pr-comment` | `0bf28ead` | `c27cb8a0` | yes |
| [#56](https://github.com/AjinkyaTaranekar/theseus/pull/56) docs: Say when Theseus reviews and blocks merges | MERGED | `merge-gate` | `683f9204` | `3efb9b12` | yes |
| [#59](https://github.com/AjinkyaTaranekar/theseus/pull/59) feat: Add the demo world and fixtures | MERGED | `f4-demo-world` | `49d009bc` | `2d1b4aa5` | yes |
| [#60](https://github.com/AjinkyaTaranekar/theseus/pull/60) feat: Review PRs through the Action and the App | MERGED | `f7-action-app` | `05584cac` | `0a1b4abe` | yes |
| [#61](https://github.com/AjinkyaTaranekar/theseus/pull/61) feat: Build graphs from infrastructure inputs | MERGED | `e1-importer` | `46077b9c` | `1dc26414` | yes |
| [#62](https://github.com/AjinkyaTaranekar/theseus/pull/62) docs: Note the quarterly support access review | CLOSED | `demo/trial-1` | `05193f48` | `—` | no |
| [#64](https://github.com/AjinkyaTaranekar/theseus/pull/64) feat: Add the demo backend and platform resources | MERGED | `c1-demo-backend` | `43c111d9` | `6873d124` | yes |
| [#65](https://github.com/AjinkyaTaranekar/theseus/pull/65) feat: Read service code into CALLS edges | MERGED | `c2-code-reader` | `4fa0d363` | `db3b64e7` | yes |
| [#66](https://github.com/AjinkyaTaranekar/theseus/pull/66) docs: Merge main into branches instead of rebasing | MERGED | `docs-merge-not-rebase` | `558af2e3` | `6f6c06ff` | yes |
| [#67](https://github.com/AjinkyaTaranekar/theseus/pull/67) fix: Reject incomplete model answers | MERGED | `codex/57-reject-incomplete-llm` | `6af6935f` | `892548de` | yes |
| [#68](https://github.com/AjinkyaTaranekar/theseus/pull/68) fix: Retry model API errors by status | MERGED | `codex/58-retry-llm-api-errors` | `dcd778fa` | `02e55413` | yes |
| [#70](https://github.com/AjinkyaTaranekar/theseus/pull/70) docs: Add the answer keys for every fixture | MERGED | `f5-hand-write-expected-json` | `44bb69c6` | `4ab51c89` | yes |
| [#71](https://github.com/AjinkyaTaranekar/theseus/pull/71) feat: Read workflows and their OIDC trust | MERGED | `fm1-ci-graph` | `d122e71c` | `b8d855f5` | yes |
| [#72](https://github.com/AjinkyaTaranekar/theseus/pull/72) feat: Find the paths a PR opens in FalkorDB | MERGED | `e3-analyze` | `3e9f6137` | `92da0aef` | yes |
| [#73](https://github.com/AjinkyaTaranekar/theseus/pull/73) feat: Say what a PR grants against what it says | MERGED | `a3-says-vs-grants` | `b284e1e4` | `07eeab3b` | yes |
| [#74](https://github.com/AjinkyaTaranekar/theseus/pull/74) feat: Review a PR for real behind the Action | MERGED | `a5-real-analyze` | `b9eab094` | `d16856e1` | yes |
| [#75](https://github.com/AjinkyaTaranekar/theseus/pull/75) Add Priya to support-engineers for prod log access | CLOSED | `demo/intern-1` | `9f5f0d3c` | `—` | no |
| [#76](https://github.com/AjinkyaTaranekar/theseus/pull/76) feat: Render verified Terraform fixes | MERGED | `e9-render-tf` | `ec0a347b` | `093f95ab` | yes |
| [#77](https://github.com/AjinkyaTaranekar/theseus/pull/77) feat: Verify fixes on graph copies | MERGED | `e5-simulate` | `706f07a6` | `ea3df006` | yes |
| [#78](https://github.com/AjinkyaTaranekar/theseus/pull/78) feat: Derive minimum cuts from graph flows | MERGED | `e4-min-cut` | `34f7462e` | `a9a3e636` | yes |
| [#79](https://github.com/AjinkyaTaranekar/theseus/pull/79) fix: Measure intent on the vocabulary it sees live | MERGED | `intent-live-vocabulary` | `97817781` | `b60df8a2` | yes |
| [#80](https://github.com/AjinkyaTaranekar/theseus/pull/80) chore: Skip CI on demo PRs | MERGED | `ci-skip-demo-prs` | `73fd7085` | `0dcc64f7` | yes |
| [#81](https://github.com/AjinkyaTaranekar/theseus/pull/81) feat: Show a review while it runs | MERGED | `ux-review-progress` | `c63d65bd` | `57c9fc6f` | yes |
| [#82](https://github.com/AjinkyaTaranekar/theseus/pull/82) feat: Lead the comment with a five-line card | MERGED | `ux-card` | `d91d7cd6` | `53ebfc95` | yes |
| [#83](https://github.com/AjinkyaTaranekar/theseus/pull/83) feat: Label PRs with what the review found | MERGED | `ux-labels` | `afcd08e4` | `a8e85b0b` | yes |
| [#84](https://github.com/AjinkyaTaranekar/theseus/pull/84) feat: Read each commit's world in one query | MERGED | `ux-fast-reads` | `7f200503` | `b900fa64` | yes |
| [#85](https://github.com/AjinkyaTaranekar/theseus/pull/85) Add Priya to support-engineers for prod log access | CLOSED | `demo/intern-2` | `01ae50f1` | `—` | no |
| [#86](https://github.com/AjinkyaTaranekar/theseus/pull/86) fix: Load the LLM client before serving | MERGED | `load-llm-first` | `f6d89c27` | `efaa12ad` | yes |
| [#87](https://github.com/AjinkyaTaranekar/theseus/pull/87) feat: Draw the connections under the card | MERGED | `ux-card-diagram` | `cfd6733f` | `69fb496d` | yes |
| [#88](https://github.com/AjinkyaTaranekar/theseus/pull/88) feat: Link each review to its graph | MERGED | `ux-review-page` | `2483c8fd` | `0b27fbe3` | yes |
| [#89](https://github.com/AjinkyaTaranekar/theseus/pull/89) feat: Map what a compromised Action can reach | MERGED | `fm3-finding` | `9d30b7cf` | `56be50e2` | yes |
| [#90](https://github.com/AjinkyaTaranekar/theseus/pull/90) feat: Verify and rank rule-based fixes | MERGED | `e6-candidates` | `4189112e` | `fb57ea77` | yes |
| [#91](https://github.com/AjinkyaTaranekar/theseus/pull/91) feat: Scan main for grants the code never calls | CLOSED | `c3-unused-grants` | `e3e14096` | `—` | no |
| [#92](https://github.com/AjinkyaTaranekar/theseus/pull/92) feat: Add choke points, staging flags, urgency | MERGED | `fm4-finding-extras` | `c7139a86` | `2215490b` | yes |
| [#93](https://github.com/AjinkyaTaranekar/theseus/pull/93) feat: Serve the tool registry over MCP | MERGED | `a6-mcp` | `b4a0ef86` | `a0818be6` | yes |
| [#94](https://github.com/AjinkyaTaranekar/theseus/pull/94) fix: Keep FLOW edges off the review page | MERGED | `review-page-no-flow` | `adb12184` | `a1fd141e` | yes |
| [#95](https://github.com/AjinkyaTaranekar/theseus/pull/95) feat: Add the Try-it page | MERGED | `s4-try-it` | `117f35c7` | `76d8abc4` | yes |
| [#96](https://github.com/AjinkyaTaranekar/theseus/pull/96) feat: Tell the review page's story at a glance | MERGED | `review-page-redesign` | `99cffe69` | `927d250c` | yes |
| [#97](https://github.com/AjinkyaTaranekar/theseus/pull/97) chore: Integrate the reviewed PRs | MERGED | `integrate-wave-1` | `a0818be6` | `c64c002a` | yes |
| [#98](https://github.com/AjinkyaTaranekar/theseus/pull/98) feat: Give each finding a page | MERGED | `finding-page` | `f97ec1f0` | `d96899b5` | yes |
| [#99](https://github.com/AjinkyaTaranekar/theseus/pull/99) chore: Integrate the second wave of PRs | MERGED | `integrate-wave-2` | `a39022c2` | `01a34897` | yes |
| [#100](https://github.com/AjinkyaTaranekar/theseus/pull/100) fix: Stop tracking a .venv symlink | MERGED | `fix-venv-symlink` | `abeaa28c` | `934f8cff` | yes |
| [#101](https://github.com/AjinkyaTaranekar/theseus/pull/101) feat: Flag code that reads data beyond intent | MERGED | `c4-beyond-intent` | `cd8a646c` | `fe54bd92` | yes |
| [#102](https://github.com/AjinkyaTaranekar/theseus/pull/102) feat: Apply a passing fix with /theseus apply | MERGED | `a9-apply` | `77ab5457` | `4ad3d482` | yes |
| [#108](https://github.com/AjinkyaTaranekar/theseus/pull/108) chore: Integrate fixer, apply, beyond intent, Try-it | MERGED | `integrate-wave-3` | `ed3cb223` | `7b411276` | yes |
| [#109](https://github.com/AjinkyaTaranekar/theseus/pull/109) feat: Add the posture of main and a dashboard | MERGED | `posture-dashboard` | `4b8d8f2e` | `ed3cb223` | yes |
| [#110](https://github.com/AjinkyaTaranekar/theseus/pull/110) feat: Let the LLM design candidate B | MERGED | `a7-fixer` | `656bc5d3` | `c0cdfa02` | yes |
| [#111](https://github.com/AjinkyaTaranekar/theseus/pull/111) fix: Contain GHSA-demo-0001 | OPEN | `theseus/contain-GHSA-demo-0001` | `13c9305e` | `—` | no |
| [#113](https://github.com/AjinkyaTaranekar/theseus/pull/113) feat: Open a containment PR for each finding | MERGED | `fm6-containment` | `8a642a4f` | `4b8d8f2e` | yes |
| [#114](https://github.com/AjinkyaTaranekar/theseus/pull/114) feat: Redesign the dashboard for any size of org | MERGED | `dashboard-redesign` | `ac52ffde` | `8a642a4f` | yes |
| [#115](https://github.com/AjinkyaTaranekar/theseus/pull/115) test: Merge the last commit of the apply PR | MERGED | `merge-a9-followup` | `4ad3d482` | `9e98a0ee` | yes |
| [#116](https://github.com/AjinkyaTaranekar/theseus/pull/116) docs: Finalize the demo video script | OPEN | `p4-finalize-the-video-script` | `64e90153` | `—` | no |
| [#117](https://github.com/AjinkyaTaranekar/theseus/pull/117) feat: Add reproducible benchmark tooling | OPEN | `s2-proof` | `b2d158cf` | `—` | no |
| [#118](https://github.com/AjinkyaTaranekar/theseus/pull/118) feat: Draw each fix's graph on the review page | MERGED | `fix-graph-view` | `eaf16897` | `3f395023` | yes |
| [#119](https://github.com/AjinkyaTaranekar/theseus/pull/119) feat: Suggest the passing fix on the PR's lines | MERGED | `fix-suggestions` | `fc877f1d` | `dc5bc426` | yes |
| [#120](https://github.com/AjinkyaTaranekar/theseus/pull/120) fix: Replay a reply that calls several tools | MERGED | `demo-forgotten-db` | `29ac1e50` | `421bfd6b` | yes |
| [#121](https://github.com/AjinkyaTaranekar/theseus/pull/121) feat: Plant gaps in the demo world for main | MERGED | `world-gaps` | `1356ee7a` | `040e1584` | yes |
| [#122](https://github.com/AjinkyaTaranekar/theseus/pull/122) feat: Show an outage's blast radius on main | MERGED | `incident` | `1f847b38` | `dcbdafec` | yes |
| [#123](https://github.com/AjinkyaTaranekar/theseus/pull/123) test: Refresh the render snapshots for main | MERGED | `fix-render-snapshots` | `6f5bc282` | `e67e965e` | yes |
| [#124](https://github.com/AjinkyaTaranekar/theseus/pull/124) Fix a typo on the support page | OPEN | `demo/code-pr-e2e` | `0ce1d964` | `—` | no |
| [#125](https://github.com/AjinkyaTaranekar/theseus/pull/125) Add Priya to support-engineers for prod log access | OPEN | `demo/intern-e2e` | `29fb960a` | `—` | no |
| [#126](https://github.com/AjinkyaTaranekar/theseus/pull/126) Remove casey-contractor from contractors | OPEN | `demo/offboard-e2e` | `07efe2d9` | `—` | no |
| [#127](https://github.com/AjinkyaTaranekar/theseus/pull/127) Make company-files public so marketing can link the pricing PDF | CLOSED | `demo/public-bucket-e2e` | `8db0caa5` | `—` | no |
| [#128](https://github.com/AjinkyaTaranekar/theseus/pull/128) Keep orders-api logs for 90 days | OPEN | `demo/safe-e2e` | `a57f74e8` | `—` | no |
| [#129](https://github.com/AjinkyaTaranekar/theseus/pull/129) Add Priya to support-engineers for prod log access | OPEN | `demo/steering-e2e` | `c48fa197` | `—` | no |
| [#130](https://github.com/AjinkyaTaranekar/theseus/pull/130) fix: Answer the roast of the comment and dashboard | MERGED | `roast-fixes` | `54b17ad7` | `69d9b31b` | yes |
| [#131](https://github.com/AjinkyaTaranekar/theseus/pull/131) feat: Make the review page load faster | MERGED | `review-page-smooth` | `33a8417a` | `444ecb4b` | yes |
| [#132](https://github.com/AjinkyaTaranekar/theseus/pull/132) fix: Run the CLI on the recordings in replay | MERGED | `cli-replay` | `37413cf6` | `65001886` | yes |
| [#133](https://github.com/AjinkyaTaranekar/theseus/pull/133) docs: Rewrite the README for submission | MERGED | `s5-readme` | `6ce293f6` | `6ce293f6` | yes |
| [#134](https://github.com/AjinkyaTaranekar/theseus/pull/134) chore: Bring the review page speedup up to date | MERGED | `review-page-smooth-merge` | `0752882e` | `40e10949` | yes |
| [#135](https://github.com/AjinkyaTaranekar/theseus/pull/135) docs: Describe the architecture and its decisions | MERGED | `docs-architecture` | `55549ceb` | `d6657ecc` | yes |
| [#136](https://github.com/AjinkyaTaranekar/theseus/pull/136) fix: Answer the rest of the roast | MERGED | `roast-fixes-2` | `92def6a5` | `2fe13b7f` | yes |
| [#137](https://github.com/AjinkyaTaranekar/theseus/pull/137) Make company-files public so marketing can link the pricing PDF | OPEN | `demo/public-bucket-2` | `cff4ab1a` | `—` | no |
| [#138](https://github.com/AjinkyaTaranekar/theseus/pull/138) fix: Keep Theseus's notes out of a PR's intent | MERGED | `containment-notes` | `e1e373d9` | `3a557657` | yes |
| [#139](https://github.com/AjinkyaTaranekar/theseus/pull/139) docs: Bring the README up to date with the demo | MERGED | `readme-followup` | `6b7e5b87` | `b05a22c7` | yes |
| [#140](https://github.com/AjinkyaTaranekar/theseus/pull/140) test: Stop falkordb tests leaking graphs | MERGED | `fix-falkordb-test-leaks` | `a49160d7` | `2cfbfb6b` | yes |
| [#151](https://github.com/AjinkyaTaranekar/theseus/pull/151) fix: Rank the containment fix like the rest | MERGED | `rank-containment` | `2600d49f` | `df64f20e` | yes |
| [#152](https://github.com/AjinkyaTaranekar/theseus/pull/152) fix: Start the MCP server on any machine | MERGED | `mcp-any-machine` | `34121a26` | `6f3fa228` | yes |
| [#153](https://github.com/AjinkyaTaranekar/theseus/pull/153) fix: Start the hooks on a machine with no python | MERGED | `hooks-any-python` | `1a67b01f` | `2cb4abe3` | yes |
| [#154](https://github.com/AjinkyaTaranekar/theseus/pull/154) docs: Bring the docs up to date for release | MERGED | `docs-release` | `71c22f1e` | `469c5714` | yes |
| [#155](https://github.com/AjinkyaTaranekar/theseus/pull/155) feat: Show where every change lands | MERGED | `change-impact` | `dc10aa21` | `d2112381` | yes |
| [#156](https://github.com/AjinkyaTaranekar/theseus/pull/156) fix: Delete a PR's graphs when it closes | MERGED | `graph-hygiene` | `9c81da3a` | `591d0aaa` | yes |
| [#157](https://github.com/AjinkyaTaranekar/theseus/pull/157) feat: Prove each saving and link official prices | MERGED | `cost-proof` | `b818d5d9` | `d2112381` | yes |
| [#158](https://github.com/AjinkyaTaranekar/theseus/pull/158) feat: Make every page explain itself | MERGED | `ux-revamp` | `eb747523` | `8e822ad9` | yes |
| [#159](https://github.com/AjinkyaTaranekar/theseus/pull/159) chore: Merge the open PRs together | MERGED | `merge-all` | `8e822ad9` | `4cea77d7` | yes |

## Local validation and remaining checks

- Verified the remote main SHA through `gh api repos/AjinkyaTaranekar/theseus/commits/main`; it matches
  the isolated worktree baseline. Verified all 79 merged PR commits locally.
- Full offline baseline: **2,190 passed, 38 skipped**, 109.94 seconds. Database tests were explicitly kept
  offline by removing `FALKORDB_HOST`/`THESEUS_LIVE` from the test process environment; no developer `.env` was
  copied. No test was edited, skipped manually, weakened or marked xfail.
- Ruff lint and format checks passed; **277 Python files** already formatted.
- Offline persistence and HTTPX logging probes are recorded in the design; no real webhook was invoked.
- Markdown relative links, inventory counts, changed-file scope and `git diff --check` are checked before
  delivery of this design. Product acceptance tests above are a specification, not implemented tests.
- Project columns/custom fields remain unverified because `read:project` is unavailable.
- No live Slack, Jev/LLM, FalkorDB, Terraform/cloud, deployment, public-site rehearsal, Windows CI, recording,
  human sign-off or release action was performed. These are not results that a documentation audit can supply.
- No shared Cloud cleanup, prune, secret rotation, issue closure or board mutation was attempted.
