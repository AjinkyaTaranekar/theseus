# S2 benchmark workbench — local review draft

This contains the local implementation and design notes for
[issue #39](https://github.com/AjinkyaTaranekar/theseus/issues/39). The runner, twenty-case generator,
Checkov wrapper and scaling harness are implemented. Human answer keys, full replay evaluation and VM
measurements are still required; no accuracy or scaling result is claimed.

The audit was made on 17 October 2026 against `main` at
`9e98a0eeded2f397d6600e8cab03e98a150ee6fd`. The local branch is `s2-proof`.
The original `s5-readme` checkout and its unpublished README commit are preserved.

## Operating the implementation

Run from the repository root with its normal Python environment. Terraform 1.16.6 and Checkov 3.3.29
are external tools already used by this repository; no runtime dependency has been added. Set the normal
FalkorDB settings through the environment or `.env`, never command-line credentials.

```bash
python -m bench.run generate         # tools/plan.sh makes both plans; never writes expected.json
python -m bench.run validate         # requires every case and its nonempty human-owned key
python -m bench.run run              # exact Llm/Jev replay, real FalkorDB, Checkov base/head
python -m bench.scale --vm --environment "CPU/RAM; DB placement; transport; thread settings"
```

`--case <id>` selects a diagnostic subset; the generated report says how many of the twenty cases ran.
`--cases`, `--recordings` and `--report` accept explicit paths. `generate` accepts `--source` for the pinned
synthetic source world. The runner validates all keys before connecting to FalkorDB. Missing keys, missing
recordings, tool failures and projection differences produce a nonzero exit status.

After humans save the answer keys, an operator can explicitly prepare matching recordings with
`python -m bench.run record --confirm-model-calls --case <id>`. That command makes real calls through the
configured wrappers and uses the same stable graph names as replay. It never writes answer keys. The
explicit flag is required; neither `run` nor `validate` can silently enable live model calls. Review and
commit new recordings with their replay tests before using the results. No recording command was executed
as part of this local implementation.

Each run retains `observed.json` in its case directory: input/recording digests, code revision and source
digest (including uncommitted code), the actual result, differences, raw Checkov output and errors.
`bench/report.md` shows human-key counts beside certain/unknown paths and code-use observations, not an
invented accuracy percentage. Replayed `AnalysisResult.timings` can include recorded model durations;
they are not the VM scaling measurements.

The scaling command requires explicit VM attestation and an environment description. It writes five raw
samples and medians to `bench/scale-results.json`, then replaces its scaling section in `bench/report.md`.
Run the case comparison before scaling: rerunning the comparison regenerates its report and removes older
scaling results, so they must be measured/appended again. The default worlds have exactly 1,000 and 10,000
non-FLOW edges, a single actor reaching every data location, and two-edge fan-out paths. Adapter setup,
source loading and copy-destination reservation stay outside the isolated measurement spans.

The shared `theseus__benchmark` coordination graph holds an atomic mutex during a run and remains empty
after release. It uses graph-query permissions, not Redis `SET`. A crashed run deliberately leaves a lock;
inspect the abandoned run and its owned graphs before manually clearing that lock. Existing product graphs
and review documents are never overwritten by the harness.

Generated case copies are excluded from Ruff like `demo-infra/` and `fixtures/`; the benchmark implementation
and its tests remain linted. Their copied HCL and Python syntax is checked by the benchmark unit tests.
The benchmark adds `tests/unit/test_bench.py` and `tests/integration/test_bench_on_falkordb.py`; those paths,
the Ruff fixture exclusion and disclosure in `AI_USE.md` extend the brief's file list and are disclosed in
the local PR description.

The implementation has offline tests for scanner failures, full-key comparison, uncertainty, missing
recordings, source generation, preservation/recovery, graph ownership, timing boundaries and medians.
The tiny-world FalkorDB test exercises actual database max flow, isolated copy mutation, simulation,
concurrent-run rejection and cleanup. It is a correctness check, not a published laptop scaling run.

## 1. What this task should deliver

Twenty reproducible PR cases derived from the synthetic demo world, a comparison of Theseus and Checkov
on each case, and five measured repetitions of four operations on 1,000-edge and 10,000-edge worlds.
Publish misses, uncertainty, errors and exclusions alongside catches. The report should let a judge follow
a number back to a case, a human answer key and raw tool output.

Keep three questions separate:

1. **Detection:** did a PR introduce the sensitive access or code use identified by the human answer key?
2. **Correctness:** did the result's projection match every field the humans chose to compare, including
   evidence, requirements, cuts and candidate verdicts?
3. **Performance:** how long did the specified operations take, on which machine and graph topology?

A detected problem with a wrong route is a detection hit and a correctness failure. A blocked review with
only uncertain paths is not proof of effective access. A Checkov failure on an unrelated baseline resource
does not establish that it caught this PR's risk.

Source requirements: [task brief](../../docs/tasks/S2.md),
[demo world](../../docs/spec/02-demo-world.md), [graph](../../docs/spec/03-graph.md),
[fixture projection](../../docs/spec/05-contracts.md#fixture-folders-and-expectedjson), and
[core and adapters](../../docs/spec/08-core-and-adapters.md).

## 2. Board audit and dependency decisions

GitHub returned **54 issues: 42 closed and 12 open**. Issue states and PR merge history were read through
the authenticated local CLI. The GitHub connector could not access this repository. Reading project columns
failed because the CLI token lacks `read:project`; therefore no claim is made about project status columns.
No issue, project item, assignee, label, PR or remote branch was changed.

### Direct dependencies and the code now available

| Dependency | Verified evidence | Consequence for S2 |
| --- | --- | --- |
| E4, #24 | Closed; [PR #78](https://github.com/AjinkyaTaranekar/theseus/pull/78) merged; merge `a9a3e63` is an ancestor of the audited base | Reuse capacities, residual cut and fallback; do not implement another cut algorithm |
| E5, #25 | Closed; [PR #77](https://github.com/AjinkyaTaranekar/theseus/pull/77) merged; merge `ea3df00` is an ancestor | Time the real `simulate()` and graph copy, with preservation checks |
| E3, #15 | Closed; [PR #72](https://github.com/AjinkyaTaranekar/theseus/pull/72) merged | Reuse world loading, graph stores, path analysis, `project()` and `compare()` |
| F4/F5, #9/#11 | Closed; PRs #59/#70 merged | Existing demo inputs and human fixture keys are reference material, not twenty independent observations |
| A1/A2/A3, #16–#18 | Closed; PRs #51/#53/#73 merged | Intent and sensitivity influence results; freeze their inputs and record replay provenance |
| E6/A7, #26/#29 | Closed; PRs #90/#110 merged | Exercise existing rule fixes and the model candidate; account for missing fix recordings |
| C2/C3/C4, #31/#36/#37 | Closed; code reader and use analysis present | Include the code-only PR; existing scan/finding fixtures can be auxiliary regression checks |
| A5/A6/A9/E9, #20/#28/#30/#27 | Closed; PRs #74/#93/#102/#76 merged | Reuse established entry points; benchmark execution needs no apply command, GitHub write or deployment |
| S4, #40 | Closed; PR #95 merged | Existing replay helpers are useful references, but their matching rules need scrutiny |

The formal S2 prerequisites E4 and E5 are satisfied. S2 can be implemented without waiting for another
feature branch. The brief's instruction to start cases after E3 also has been satisfied.

### Every closed issue and its place in this work

Closed means the board records completion; it does not replace rerunning checks at the selected commit.
These rows account for all 42 closed issues.

| Issues | Work | S2 relationship |
| --- | --- | --- |
| #1 P1; #2 P3 | FalkorDB/Terraform feasibility; paper review | Use algorithm constraints and scenario reasoning; do not reuse throwaway PoC code |
| #4 P5; #5 P6 | Access/keys; team/IP setup | Already recorded as done; no credentials or administrative changes belong in S2 |
| #7 F1; #8 F2 | Package/CI; frozen contracts | Use existing tools and contracts; avoid schema/protocol changes |
| #9 F4; #11 F5; #63 | Demo generator, human keys, demo hardening | Preserve source and answer-key ownership; regenerate rather than edit plans |
| #10 F3; #12 F7 | Runtime/deploy; Action/App | Use FalkorDB and existing Checkov version; VM access is an execution requirement |
| #13 E1; #14 E2; #15 E3 | Import, IAM, graph/path analysis | These decide the facts; benchmark code must not duplicate their policy logic |
| #16 A1; #17 A2; #18 A3 | Intent, sensitivity, intent/effect | Freeze model inputs; state that synthetic replay measures engine behavior, not live-model accuracy |
| #19 A4; #20 A5 | Comment renderer; real analyze | Record the product verdict separately from risk detection and projection correctness |
| #21 FM1; #22 C1 | OIDC/workflows; service backend | Use realistic OIDC and code changes from this world |
| #24 E4; #25 E5; #26 E6; #27 E9 | Cut, simulation, ranking, rendering | Measure/reuse them; do not repair unrelated product behavior in the benchmark branch |
| #28 A6; #29 A7; #30 A9 | MCP, fixer, apply | Preserve trace/replay behavior; no publication side effects are needed |
| #31 C2; #32 FM3; #33 FM4 | Code reader; finding mode/extras | Retain scan/finding checks as a separately labelled supplement |
| #35 FM6; #36 C3; #37 C4 | Containment, unused grants, code use | Available for regressions; do not call containment publication from the benchmark |
| #40 S4 | Try-it | Existing demo surface; not a benchmark runner or source of ground truth |
| #57; #58 | Incomplete-response validation; retries | Use the standard model wrapper; avoid bypassing its validation in a new replay shim |
| #103 O1; #104 O2; #105 O3; #106 O4; #107 O5 | Main posture, failure points, cost, dashboard, onboarding | Integrated via PRs #109/#108; outside the four requested S2 timing operations |

Important history detail: PR #91 for C3 was **closed without merge**. Its feature is nevertheless present
on `main` through integration commit `f6caaed` (`feat: Scan main for grants the code never calls`). That
commit is an ancestor of the audited base. Do not infer missing functionality from PR #91's status alone.
Likewise, PRs #65, #109, #113 and #114 first merged into other feature branches; follow their integration
into `main` rather than treating a feature-branch merge as sufficient evidence on its own.

### All 12 open issues and the remaining human work

| Issue | Status observed / dependency | Recommended next step; relationship to S2 |
| --- | --- | --- |
| #3 P4 | Open; needs P3 | Humans finalize/read the video script and choose narration; independent of S2 implementation |
| #6 P7 | Open; needs P3 | Humans rehearse graph, capacity and scope explanations; use S2's eventual limitations and raw evidence |
| #23 G1 | Open; A5 code merged | Humans run the intern demo live and save the clip; do not mark complete from unit tests |
| #34 G2 | Open; G1 plus E4/E6/A7/A9 | Humans demonstrate B, apply, rerun and green check; model candidate replay availability matters here too |
| #38 G3 | Open; G2 plus FM4/FM6/C3/C4 | Humans demonstrate containment, U and code-only detection; preserve the clips |
| #39 S2 | Open; E4/E5 merged | Implement this design after review, human keys, replay preparation and VM measurement |
| #41 S5 | Open; needs G2/G3 | Local commit `6b96567` on `s5-readme` already drafts the README; hand S2 numbers to that work without overwriting it |
| #42 S6 | Open; needs G3/P4 | Humans assemble/upload video; use S2 report only once measurements exist |
| #43 S7 | Open; needs S5/S6 | Humans review final state, make public, tag and submit; no publication is authorized by S2 |
| #44 S8 | Open; needs S6 | Blog after submission; reuse the published methodology and limits |
| #69 | Open design; requires both humans for new edges/traversal | Defer service-path/exposure/language extensions; none is necessary for S2 |
| #112 | Open synthetic rotation checklist | Track demo follow-through; not a benchmark dependency or evidence of real secret rotation |

The only open PRs returned by the inventory were demo PR #85 (intern) and #111 (containment). They are
scenario demonstrations, not product dependencies to merge into S2. PR #115 supplies the last apply tests
on the audited `main`; the local README commit is not part of that base.

G1–G3 are **demo acceptance gates**, not missing code prerequisites for S2. Completing S2 does not close them.
The dependency CSV does not make S2 a formal prerequisite of S5/S6, but the benchmark paragraph and video's
proof segment need S2's measured artifacts before they can claim benchmark numbers.

## 3. Proposed twenty-case corpus

All rows below are **test designs**, not measured outcomes or saved answer keys. Both humans should approve
the intended effects before inspecting Theseus/Checkov output. Checkov outcomes remain unassigned until run.
Use independent changes from a pinned base for each row; do not build one case on another's head.

Proposed balance: ten dangerous-access/use changes, six changes with no new sensitive access, and four
unsupported-IAM controls. The IDs are generated folder names under `cases/`; the strata remain proposals
for human review, not saved truth labels or measured results.

| ID | Source edit in that case's head | Target assertion for human review |
| --- | --- | --- |
| 01-intern-membership | Add Priya's membership in `support-engineers`, as the `intern` fixture does | The three spec-defined paths open; the stated logs need does not authorize the database |
| 02-public-invoices | Add `PublicRead` for company-files `*`; disable its two policy-block settings, as `public-bucket` does | Internet reaches invoices; public pricing access remains the stated need |
| 03-analyst-raw | Broaden `ReadCurated` in `data-lake-curated-read` from `curated/*` to `*` | `alex-analyst` gains raw-zone access beyond R15; also enumerate other affected actors |
| 04-public-raw | Add public read of the data lake and disable the corresponding policy-block settings | Internet reaches regulated `raw/`; do not infer effective public access while leaving the block on |
| 05-secret-wildcard | Add a Priya user policy allowing `secretsmanager:GetSecretValue` on `*` | Enumerate newly reachable sensitive secrets and the database unlocked by the DB secret |
| 06-shared-policy-wildcard | Broaden the existing `app-logs-read` policy's resource to `*` for its existing S3 read actions | Shared attachment exposes sensitive locations to additional actors such as Jordan; enumerate exact pairs |
| 07-oidc-no-sub | Remove only the `sub` restriction from `terraform-apply`, preserving issuer/audience | Eligible preview workflow can newly reach Terraform state; workflows without ID-token permission stay excluded |
| 08-oidc-wide-sub | Replace `terraform-apply`'s pinned subject with `repo:demo-org/*` | Same sensitive target through a wildcard subject; contrast with the pinned base, not the already-wide deploy role |
| 09-code-export | Use the `code-pr` change: export module, handler route, environment value and typo fix; IAM unchanged | No opened IAM pair, but new secret/database code use beyond intent; code lines must exist |
| 10-support-raw-grant | Add raw-zone read to `prod-support`'s policy | Additional sensitive actor/target pairs appear through existing support/deploy role chains |
| 11-public-prefix-only | Add public read only for company-files `public/*`, with realistic policy-block changes | No new sensitive target, despite Checkov potentially flagging a public policy |
| 12-intern-logs-only | Add Priya's exact app-logs read policy, without support membership | Stated internal logs access works without reaching invoices, secret or database |
| 13-equivalent-curated | Rewrite `ReadCurated`'s action/resource scalars as one-element arrays | Semantic equivalence; no opened/closed sensitive pairs or requirement regression |
| 14-remove-unused-secret | Remove only support-portal's `LegacyDbSecret` statement | Its dangerous access closes; legitimate config requirements and existing code access are preserved |
| 15-pin-deploy-trust | Narrow `github-deploy` to the infra release workflow's actual main-branch subject | Preview loses access while R4/R5/R17 remain satisfied; derive the subject from workflow jobs, not memory |
| 16-unconditional-deny | Give Priya a matching invoice Allow and an unconditional matching Deny in the same case | Deny wins; no invoice path or database access is introduced |
| 17-conditional-secret | Give Priya a secret Allow with an unsupported condition | Potential access is marked unknown, with a reason; never count it as a proven grant or a clean result |
| 18-notaction | Add an otherwise matching Priya policy using `NotAction` | Unsupported subset is reported; inspect raw edge/path uncertainty as well as projected fields |
| 19-notresource | Add an otherwise matching Priya policy using `NotResource` | Same uncertainty obligation for this distinct unsupported construct |
| 20-permission-boundary | Add a permission boundary to Priya together with a secret grant | Boundary makes affected access unknown; do not pretend the boundary has been evaluated |

For every case, humans enumerate the **full** relevant pair sets, not just the illustrative target named in
the table. Wildcard changes can affect more than one actor or resource. Existing dangerous paths in the
base belong in `unchanged`, not in the PR's new-risk count. A negative case is about the change, not a
claim that the entire demo base has no pre-existing problems.

Keep `compromised-action` finding mode and `unused-grant` scan mode as separately reported fixture regressions.
Do not count them as extra PRs or claim twenty independent real-world incidents. The new corpus is
self-authored, synthetic, related to one world and not held out from development.

### Generation and human answer keys

Use the fixture layout from spec 05 unchanged: `scenario.yaml`, `base/`, `head/`, both plans, `pr.md` and the
human-written `expected.json`. No new field in a shared contract or in the golden projection is needed.

The generator should copy a pinned demo source into each case, apply exact edits that each match once,
and call `tools/plan.sh` for plans. It must never write, replace, delete or infer `expected.json`, including
on regeneration. Validate output paths and reject an output rooted in the source demo or existing fixtures.
Source evidence is calculated by the existing source index after generation; no hand-authored line numbers.
Retain existing documented Checkov skip comments in both sides; do not add skips to obtain favorable results.

`tools/make_fixture.py` enumerates the five product fixtures. Benchmark generation is a subcommand of
`bench/run.py`, reusing its source edits, plan tool and atomic publisher without changing the product
generator. The twenty cases' source inputs and both plans have been generated; no answer key was written.
The current inputs were generated with Terraform 1.16.6 and AWS provider 6.69.1 under the source's existing
provider constraint. Retained plan bytes and their content digests identify the actual benchmark inputs.

Before running tools, humans save/review each key using the existing projected shape. Include explicit
empty `opened` and `use_beyond_intent` lists for negative cases; otherwise omitted fields are not compared.
For unsupported cases, include the expected unknown reasons. Missing or empty answer keys mean **unscored**,
not passing. Never generate truth by copying the engine output, and never use `--update-expected` behavior.

The twenty-case table supplies the proposed scoring strata. If machine-readable strata, relevant Checkov
IDs or per-case recording manifests are desired, agree their storage and schema before implementation;
do not quietly add them to `expected.json` or `scenario.yaml`.

## 4. Runner and integration design

| File | Proposed responsibility | Existing code to reuse |
| --- | --- | --- |
| `bench/run.py` | Validate cases; generate inputs when explicitly requested; orchestrate runs; compare projections; generate report | `cli.adapters_for`, `load_world`, `Deps`, `pipeline.run_pr`, `project`, `compare` |
| `bench/checkov.py` | Run pinned Checkov on base and head; validate JSON; retain findings and errors | Workflow's existing `checkov==3.3.29` baseline and Terraform framework |
| `bench/scale.py` | Deterministic synthetic worlds; operation timing; correctness checks; measured samples/medians | `build_rows`, `load_graph`, `analyze`, `capacities`, store methods and `simulate` |
| `bench/report.md` | Generated comparison table, denominators, limitations, provenance and timing medians | Raw run records; never hardcoded outcome cells |
| `bench/cases/<id>/` | Generated inputs and human-owned keys | Spec 05 fixture format |

Use the existing composition root to obtain adapters; do not introduce adapter imports into core or a
benchmark-specific IAM evaluator. Use Pydantic models local to the benchmark for data crossing its modules.
No production contracts, dependencies, IAM semantics, demo source or golden comparison keys should change.

### Execution sequence

1. Validate the complete corpus and keys before any database writes. Fix the case order by ID. Compute
   source, plan, key and recording digests. Use explicit absolute paths for subprocesses and recordings.
2. Create settings through `config.py`, force replay for model clients, and connect to real FalkorDB. Stop
   with a clear run error if unavailable. Offline tests inject a store; published measurements do not.
3. Load each world's files and plans through the existing adapters. Run the existing PR pipeline. Preserve
   raw `AnalysisResult`, its projection, comparison differences and the product verdict separately.
4. Run Checkov on both base and head with identical options/version; retain their complete reports.
5. Score only cases with valid human keys and successfully completed required tool runs. A tool error stays
   an error row. Continue other cases, but fail the command when any case errors or any key comparison fails.
6. Clean up only the exact graph names created by this run, including candidate graphs. Generate a stable,
   sorted report that links to retained artifacts. An incomplete run must say how many rows were unscored.

### Graph naming needs deliberate isolation

`pipeline.graph_name()` recognizes `fixtures/<scenario>/<side>` and `<world>/pr<N>/<side>`. A plain
`bench/cases/<id>/head` falls through to `head__head`, while `scenario_of()` returns `None`.
Cases would collide with each other if the runner used those roots unmodified.

Proposed fix within S2: stage each generated case under a deterministic benchmark-owned world root such as
`s2-01-intern-membership/pr1/{base,head}` before loading. Existing graph naming then provides distinct
`s2-01-intern-membership__pr1-base` and `...-head`, and existing simulation naming produces scoped fix graphs.
The benchmark record owns the case ID. The implementation annotates only `scenario` from the validated
directory/metadata name so the standard fixture key can compare it. This is harness metadata; it does not
change an engine-derived fact or weaken an existing fixture key.

Reject concurrent runs using the same reserved roots, and refuse to overwrite pre-existing graphs. Keep an
exact ownership ledger for graphs and remove only owned names in `finally`; never delete all `fx__*` or
`demo-infra__*` graphs. Failed setup and failed cleanup must be visible errors.

### Replay is a preparation dependency

The standard `Llm` hashes the full request, including vocabulary and tool context. Novel case text and graph
names need matching recordings. Existing `agent/replayed.py` looks up the final message rather than the
full request and returns a reply directly; do not silently assume it is an exact replay of a new case.

Default proposal: use the standard `Llm` and `Jev` in replay mode. Prepare each new recording through their
existing wrappers with `THESEUS_MODE=record`, in a separately authorized recording session, commit it with
its test, and record model/prompt/request digests. No real model calls occur during benchmark execution or
the default test run. Missing sensitivity/intent replay is an error, not a fabricated answer.

The PR pipeline catches a fixer `ModelError` and continues without candidate B. Therefore a successful
pipeline return alone does not establish complete fixer replay. Track missing fix recordings explicitly;
retain detection results but mark fix evaluation unavailable. Never count an absent B as a verified fix.
Existing recordings may be reused only where their request context actually matches.

An engine-only run with fixed human intent/classification is a possible separately named diagnostic mode,
but must not be presented as a complete replay benchmark. Approve that mode and its disclosure before coding
it. PR text, advisory text and comments still use the established untrusted-input boundary.

## 5. Scoring and Checkov fairness

The generated table should have: case, human stratum, Theseus observation, projection match/differences,
product verdict, Checkov total failures at base/head, new Checkov findings, relevant risk catch, and errors.
Use words such as `unscored`, `error` and `unknown`; never fill an unavailable result with `0` or `pass`.

**Theseus detection:** a certain new dangerous pair or new sensitive code use matching the human-labelled
risk is a hit. Store extra/missing pairs separately. An unrelated alert is not a hit. Preserve raw
`PathRecord.unknown` and source evidence: `project()` intentionally does not include that flag, so a separate
benchmark assertion must inspect it without changing `project()`, `compare()` or the golden keys.

**Product verdict:** reuse `agent.render.verdict()`. At this base it blocks for any opened path before
checking `unknowns`. Thus an unsupported case may show a blocked UI while containing only unknown paths.
Report both observations. Do not change this product behavior from S2 or assert that every unknown control
must render the yellow verdict. An unknown path cannot become a certain-access benchmark hit.

**Checkov execution:** use `checkov==3.3.29`, `--framework terraform`, and JSON output, matching the existing
Action. Keep it an external executable in an isolated environment; do not add its dependency tree to the
runtime package. Any dependency-install workflow still needs the repository's required approval. Disable
external module downloads and platform integrations for a reproducible local Terraform scan. Bound runtime,
use an argument array rather than a shell, and capture stdout/stderr without exposing credentials.

Handle Checkov's single-report/list-report JSON forms, validate summaries and findings, and distinguish an
ordinary policy-failure exit from crash, timeout, invalid/empty JSON and parsing errors. A nonzero exit by
itself is neither a catch nor a tool crash. Preserve skipped checks and parse errors in the report.

Compare failure identities by check ID and resource address, not file line (edits move lines). Retain the
full base/head totals and the set difference. Humans review whether a new finding is relevant to the planted
risk. A pre-existing broad-policy alert can be contextually relevant even if no new Checkov finding appears;
show that separately rather than claiming the PR was flagged. The Terraform scan does not inspect the Python
export, which limits what the comparison says about code-only changes.

On the ten positive and six negative cases, report hit/miss/false-alarm counts with denominators and counts
of abstentions/errors. If precision/recall are shown, define their treatment of abstentions first and show
coverage alongside them; do not exclude hard cases silently or divide by zero. On the four unsupported
controls report uncertainty preserved, false certainty, and clean-result mistakes separately. Do not combine
these controls into a headline binary accuracy percentage.

## 6. Scaling method

The brief specifies **1,000 and 10,000 edges**, not those numbers of nodes. Report actual node count,
non-internal edge count, traversal/grant edge count, FLOW-pair count, actors, sinks, returned routes, depth
and fan-out. This makes a result interpretable and prevents a large disconnected graph masquerading as a
large path workload.

Generate repeatable sparse worlds from supported resource and graph kinds, with stable IDs and no random
seed or new edge types. Keep `World.resources`, source files and `GraphRows` consistent so a simulation can
really rebuild the world. Every synthetic edge cites generated source or `file="unknown"` with an explicit
synthetic-source reason; no invented file lines. A graph made only by multiplying `GraphRows` is inadequate
for timing `simulate()`, which reconstructs rows through adapters.

Proposed topology: repeated short access chains with bounded fan-out, known sensitive sinks, at least one
preserved requirement and a removable grant. Stay within the seven-edge path limit. Generate to exact
non-FLOW edge budgets, or fail validation rather than relabel a different size. Add a separately labelled
fan-out stress variant only after the required sparse worlds work; its timeouts remain published outcomes.
Do not claim conclusions about dense graphs from the sparse results.

| Operation | Timed boundary | Validation outside the measured span |
| --- | --- | --- |
| Path query | `FalkorStore.paths(graph, actor)` through returned/decoded rows | Expected reachable targets, route validity and route count; report one actor separately from all-actor engine work |
| `GRAPH.COPY` | `store.copy(source, fresh_destination)` with destination absent | Source/copy rows equal; later mutation does not change source; remove destination outside timing |
| Database max flow | `store.max_flow(graph, sources, sinks, caps)` | Expected value, capacities and feasible flows; label this boundary as FLOW setup plus database algorithm |
| One simulation | `simulate(store, head, draft, actors, requirements, adapters)` | Expected verdict, closed risk, preserved requirement/code access, unchanged source, scoped copy |

Measure database max flow directly to avoid silently timing `algos.max_flow()`'s Python fallback. If the
database algorithm fails, publish that failure. An optional engine/fallback measurement must be labelled
separately, with its backend and reason. Likewise `min_cut()` includes capacity construction, max flow and
residual processing; it is not interchangeable with database-only algorithm time.

For each size/operation: warm once, then take **five** measured samples on the VM. Use a monotonic clock
such as `perf_counter_ns`, keep raw samples, and report the median in milliseconds. Reset mutable state
between samples; copy cleanup, loading, world generation, capacity preparation, imports, model replay and
validation stay outside isolated operation spans. A simulation's internal copy/rebuild/checks remain inside
its span. Do not add these overlapping measurements together as total review time.

Use existing `Timings` for time-bearing result records; keep detailed timing samples in a benchmark-local
Pydantic measurement model using that type rather than expanding the shared contract. Stable report content
uses sorted IDs; performance values are the explicitly variable measurement data, not facts to golden-test.

Record source commit, Python/client/server/Checkov/Terraform versions, VM CPU/RAM/OS, database placement,
transport/TLS, thread settings, warmup count and sample count. The repo uses FalkorDB Cloud; if the VM calls
Cloud, client round trips are part of the measurement. Never label that database CPU time or claim that
FalkorDB runs on the VM. Hardware identifiers and credentials need not be printed. Use existing configured
query timeouts plus bounded subprocess/run budgets, with failures retained rather than replaced by medians.

No scaling numbers are supplied by this design. Laptop test times are not substitutes for the requested VM
measurements. Exact Brandes and Tarjan are Python implementations in the current product; they are outside
the four operations and should not be described as FalkorDB procedures if discussed in the README.

## 7. Validation and remaining acceptance work

The new tests were written first and failed because the benchmark modules did not exist.
`tests/unit/test_bench.py` now covers full-key comparison, uncertainty, missing replay, scanner JSON/error
handling, stable report ordering and escaping, source generation, key preservation and rollback recovery,
graph ownership and cleanup, exact graph size, feasible flow, simulation preservation and timing medians.
Default tests mock external processes and use the offline store; they make no network calls.

`tests/integration/test_bench_on_falkordb.py` runs the tiny generated world on the configured database.
It checks actual database max flow, copy isolation through a mutation, the passing narrowing simulation,
concurrent-lock rejection and cleanup. The same world is also exercised with the offline store.

Real-tool checks generated all forty base/head plans with the existing mock-only plan script and imported
them through the actual adapters. The Checkov wrapper was checked against the existing public-bucket
fixture: zero base failures, four head failures. That is a wrapper regression check, not the twenty-case
comparison. Checkov's `--quiet` omits passed/skipped JSON records in 3.3.29, so the wrapper requests the full
JSON report and preserves those records instead of loosening report validation.

Run `pytest -q`, `ruff check .` and `ruff format --check .` for local regression checks. Explicitly select
the FalkorDB test for database verification. Missing model recordings, human keys or VM access remain
preparation blockers, not reasons to weaken tests or substitute fabricated results.

## 8. Remaining review decisions and handoff

1. Humans review the twenty source changes and proposed 10/6/4 strata, then save each `expected.json`.
   The implementation reports raw observations and complete projection differences; it does not invent
   binary truth labels, Checkov relevance annotations or accuracy percentages.
2. Prepare matching recordings through the standard wrappers. The runner forces exact replay and reports
   missing optional-fixer recordings even when the product pipeline continues without B. No new model
   recordings or live model calls have been made in this work.
3. Identify the VM environment and measurement owner. Execute the documented twenty-case comparison and
   five-sample scaling protocol there. The tiny laptop/database integration test is not a VM measurement.
4. Generate the final report and hand the numbers and limitations to S5 for README integration, preserving
   that branch's existing unpublished work. Both humans review the diff before publication or merge.

[AGENTS.md](../../AGENTS.md) explicitly says “Never write or edit ... bench/cases/*/expected.json” and
“Humans write the answer key.” Those files remain absent for humans to author. Shared result contracts,
adapter protocols and golden comparison keys have not changed. Any future schema/rule expansion still
follows its Ask first rule.

Handoff to S5: generated case table, full denominator/error accounting, provenance, five raw timing samples
and median per operation/size, environment description, and the synthetic/self-authored disclaimer. S5 owns
the README prose; the video owner consumes the same report. Re-run at the final submission commit if relevant
engine, adapter, prompt, recording or case inputs change.

S2 is done only after human keys exist, the comparison actually ran, VM timings were measured, the report
was generated from retained outputs, README numbers were integrated, and required checks passed. This design
does not close #39, any gate, or any publication task.
