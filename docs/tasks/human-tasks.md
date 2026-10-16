# Human tasks

These tasks have no agent brief: a person does them. P tasks happen before the event and are notes or
throwaway checks only (rule 8). G tasks are the gates: both of us run a beat end to end and record a backup clip.

| ID | Task | Needs first | Done when | Notes |
| --- | --- | --- | --- | --- |
| P1 | Run FalkorDB once and try MaxFlow, betweenness and GRAPH.COPY on a toy graph; run terraform plan with mock credentials on one resource of every type demo-infra uses; then throw both away | nothing | Every check returns a result, and the notes are written | Decide where FalkorDB runs: Docker Desktop or WSL, the Oracle VM over an SSH tunnel, or FalkorDB Cloud. Record the image tag, the exact output of `algo.maxFlow` and `algo.betweenness`, and any resource type plan rejects under mock credentials |
| P3 | Trace each scenario in spec 02 and the six dangerous paths in main on paper, and sketch the intern graph's capacities | nothing | We both agree on every expected path | Spec 02 already holds the outcomes; this is where we make sure we can explain each one |
| P4 | Finalize the video script in docs/plan-of-action.md and choose who does the voice-over | P3 | Read aloud, and its length noted | The script is in docs/plan-of-action.md, under Submission |
| P5 | Check access: Crusoe API key for the LLM, TypeSafe key for Jev, the Oracle VM, and the GitHub account that will own the repo | nothing | Each one tested once | Check the Crusoe credit balance. No GitHub org is needed |
| P6 | Register the team, agree IP ownership in writing, and keep the repo private and the PoC out of public places until we submit | nothing | Registered, and the agreement signed by both of us |  |
| P7 | Rehearse the judge questions in docs/plan-of-action.md | P3 | Each of us answers every question | Each of us must explain capacities, how the cut comes from flows, OIDC matching, and what the demo world leaves out |
| F5 | Write expected.json for each generated fixture from the outcomes in spec 02, reading line numbers from demo-infra/ | F4, P3 | We both sign off every expected.json | An agent may draft the values, from spec 02 and the fixtures' lines; a human reviews every value and saves each file (the agent never writes one), and both of us sign off. `code-pr` follows C1 |
| G1 | Run the intern PR end to end on a fresh demo/ branch and record a backup clip | A5 | The live comment shows three opened paths and says versus grants; the clip is saved | Both of us watch it once before calling the gate |
| G2 | Comment, four tested fixes, /theseus apply B, the commit, the re-run and the green check, on a fresh demo/ branch; record a backup clip | G1, E4, E6, A7, A9 | The check turns green after the apply; the clip is saved | This is the minimum winning demo, together with Beat 3's trace |
| G3 | Finding to containment PR and rotate issue; scan to the U fix; the code PR flagged; record backup clips | G2, FM4, FM6, C3, C4 | All three run live; the clips are saved |  |
| S6 | Final video from the script, built from the gate clips and fresh takes | G3, P4 | Uploaded | About three minutes |
| S7 | Make the repo public, tag the submitted commit, and submit the form naming Track 01 | S5, S6 | Submitted |  |
| S8 | Blog post for the side prize | S6 | Published after submission |  |

Humans also own every `fixtures/*/expected.json` (F5) and `bench/cases/*/expected.json` (S2): an agent may draft the values, but a human reviews and saves each file, and an agent never writes or edits one.
