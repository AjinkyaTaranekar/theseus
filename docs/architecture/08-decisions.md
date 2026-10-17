# 08. Decisions

Each record below is one architecture decision: the **context** that forced a choice, the **decision**, its
**consequences** (good and bad), and the **alternatives** we turned down. They are grouped by area. Where a
decision came from a bug found in testing, the record says so.

## Contents

- **Principles:** [1](#1-the-engine-decides-facts-models-propose-a-person-approves),
  [2](#2-every-claim-cites-evidence), [3](#3-unknown-instead-of-a-guess), [4](#4-deterministic-output)
- **The graph and FalkorDB:** [5](#5-a-graph-per-state), [6](#6-falkordb-is-the-only-product-store),
  [7](#7-a-broad-cypher-match-strict-rules-in-python), [8](#8-flow-edges-and-capacities-for-the-cut),
  [9](#9-exact-betweenness-in-python), [10](#10-a-fix-is-tested-on-a-rebuilt-copy),
  [11](#11-results-live-in-a-documents-graph)
- **Code structure:** [12](#12-core-and-adapters)
- **Models:** [13](#13-words-explain-never-approve), [14](#14-untrusted-text-is-fenced-and-the-fix-agent-never-sees-it),
  [15](#15-one-llm-designed-candidate-verified-like-the-rest), [16](#16-jev-for-small-typed-questions-a-veto-never-an-approval),
  [17](#17-record-and-replay)
- **GitHub:** [18](#18-two-workflows-for-one-review), [19](#19-the-app-commits-and-only-under-the-world-root),
  [20](#20-a-review-fails-closed), [21](#21-suggestions-before-apply), [22](#22-only-the-passing-fix-named-by-what-it-does),
  [23](#23-the-webhook-handlers-run-in-a-thread-pool)
- **Pages:** [24](#24-signed-page-links), [25](#25-pages-read-the-graph-live),
  [26](#26-the-dashboard-reads-documents-by-prefix), [27](#27-try-results-are-kept-until-the-next-deploy)
- **Posture and incidents:** [28](#28-single-points-of-failure-from-the-engines-own-routes),
  [29](#29-cost-from-list-prices-only-for-what-the-code-declares),
  [30](#30-the-outage-basis-is-kept-at-posture-time), [31](#31-incident-headlines-are-matched-not-read-by-a-model)
- **Housekeeping:** [32](#32-a-prs-graphs-live-as-long-as-the-pr-is-open)

---

## Principles

### 1. The engine decides facts; models propose; a person approves

- **Context.** Security tools that ask a language model "is this change dangerous?" give answers that change from
  run to run, can be talked out of a finding by text in the PR, and cannot show their work. A reviewer cannot
  trust a verdict they cannot check.
- **Decision.** Every fact (a path exists, a fix passes, a requirement breaks) comes from deterministic code over
  the graph. Models only propose: what a PR says it needs, and one candidate fix. Nothing is committed until a
  person with write access approves ([`AGENTS.md`](../../AGENTS.md), "The one invariant").
- **Consequences.** Verdicts are repeatable and testable against hand-written answer keys
  (`fixtures/*/expected.json`). A model being down degrades the review but cannot change its verdict. The cost
  is that the engine only knows what is modeled; anything outside it is reported as unknown (record 3).
- **Alternatives.** An LLM verdict with the graph as context: rejected, since the graph would become decoration.
  Auto-applying fixes: rejected, because a person must own a change to their infrastructure.

### 2. Every claim cites evidence

- **Context.** "Priya can reach the customer database" is only useful if the reviewer can see why, line by line.
- **Decision.** Every edge carries `Evidence`: the Terraform address, the part (such as a statement's Sid), the
  file and line, or `file: "unknown"` with a reason. A line number is never guessed or typed by hand; the
  Terraform adapter finds it (`adapters/terraform/source_index.py`).
- **Consequences.** Every step in a comment links to the line behind it, and the fix agent's rationale can be
  checked against real evidence IDs (record 15). Loading costs a little more, since evidence is stored as JSON on
  each edge.
- **Alternatives.** Evidence only on the final edge of a path: rejected, as the dangerous hop is often in the
  middle.

### 3. UNKNOWN instead of a guess

- **Context.** IAM has features the engine does not model: most conditions, `NotAction`, permission boundaries,
  SCPs, KMS key policies.
- **Decision.** An edge that depends on one is `unknown`, never assumed open or closed. A requirement satisfied
  only through unknown edges is `unknown`, a fix that leaves one gets the verdict `unknown`, and the check is
  `neutral` ("Needs a look") when that is the only issue.
- **Consequences.** Theseus never claims a fact it cannot prove. Candidate C (a conditioned `Deny`) is always
  `unknown` by design. The engine may over-report one case (a member's own `Deny` against a group's `Allow`),
  never under-report.
- **Alternatives.** Treating unmodeled conditions as allowing access: rejected, as it would hide that we did not
  check.

### 4. Deterministic output

- **Context.** Golden tests compare results with answer keys, and a reviewer comparing two runs must see the
  same thing twice.
- **Decision.** Every list is sorted, IDs are stable (a path's ID hashes its steps, never its `eid`s), there is no
  randomness, and wall-clock values live only in `Timings`.
- **Consequences.** Golden tests compare a projection and never break on order or timing. It rules out FalkorDB's
  sampled betweenness for results (record 9).

## The graph and FalkorDB

### 5. A graph per state

- **Context.** A PR review compares two versions of the world, and each candidate fix is a third. Keeping them in
  one graph with a "version" property would put a filter on every query, and one missed filter mixes states.
- **Decision.** Each state is its own FalkorDB graph: `demo-infra__main`, `demo-infra__pr85-base`,
  `demo-infra__pr85-head`, `demo-infra__pr85-fix-b`, and `fx__<scenario>__<side>` for fixtures.
- **Consequences.** Queries stay simple and cannot leak across states. The review page reads base and head as two
  graphs. A candidate is one `GRAPH.COPY` away. The cost is more graphs in the store; a PR's graphs are deleted when it closes
  ([32](#32-a-prs-graphs-live-as-long-as-the-pr-is-open)).
- **Alternatives.** One graph with versioned edges; computing diffs in Python only. Both rejected for the
  reasons above.

### 6. FalkorDB is the only product store

- **Context.** Hackathon rule 3: the product must run on FalkorDB. Tests must also run offline, without a server.
- **Decision.** `FalkorStore` serves the API, the CLI and the MCP server, and they refuse to start without
  FalkorDB. `MemoryStore` implements the same protocol for offline tests only, and
  `tests/integration/test_store_parity.py` checks the two give the same answers.
- **Consequences.** The default test run needs no network. Production behaviour is checked against the real
  database by `pytest -m falkordb` in CI. The cost is keeping two implementations in step.
- **Alternatives.** Testing only against a FalkorDB container: rejected, since contributors on Windows would need
  Docker for every run.

### 7. A broad Cypher match, strict rules in Python

- **Context.** A valid path has rules a single variable-length match cannot express cleanly: no node twice,
  traversals before the grant, `UNLOCKS` only after a `CAN` to a secret.
- **Decision.** `Q_PATHS` finds every route of path-type edges up to 7 long and returns only `eid`s;
  `_record` in `engine/analyze.py` keeps the valid ones.
- **Consequences.** The query is short and easy to check on FalkorDB, and the rules are unit tested in Python.
  The cost is fetching some routes that are then dropped, which at this graph size is small.

### 8. FLOW edges and capacities for the cut

- **Context.** FalkorDB's `algo.maxFlow` takes one relationship type, no parallel edges, and non-overlapping
  sources and sinks. Our graph has six path types and can have parallel edges.
- **Decision.** Before each call, write one `FLOW` edge per ordered pair of nodes (`Q_SET_FLOW`), with capacities
  summed: 1,000,000 for edges an approved requirement needs and for `RUNS_AS` and `UNLOCKS`, 1,000 for a grant the
  code uses, 1 otherwise. Compute the cut from the residual graph; fall back to Edmonds-Karp in Python if the
  call fails.
- **Consequences.** The cut never removes what must keep working unless nothing else is possible, and then the
  value says so (`cuttable: false`), which is the signal to design a structural fix. `FLOW` edges are working
  state, never shown and never evidence.
- **Alternatives.** Max flow in Python only: rejected, as the database does it natively and that is part of what we
  set out to show. Weighting by edge type alone: rejected, as requirements must outrank everything.

### 9. Exact betweenness in Python

- **Context.** `algo.betweenness` is a sampled estimate. On the `compromised-action` graph its top choke point
  changed between runs.
- **Decision.** Results use Brandes' exact algorithm on the state's rows (`choke_points` in `graph/algos.py`);
  `store.betweenness` still returns FalkorDB's scores for anyone who wants them.
- **Consequences.** Choke points are stable and testable. On very large graphs the exact algorithm would cost more;
  at our size it is milliseconds.

### 10. A fix is tested on a rebuilt copy

- **Context.** A fix could be "tested" by hiding an edge in a query, but that can disagree with what the changed
  Terraform would really produce.
- **Decision.** `GRAPH.COPY` the head, apply the ops to the head's resources with the cloud adapter, rebuild the
  rows, and write only the delta to the copy (`simulate`, `delta`).
- **Consequences.** A fix passes only if the Terraform it would commit really closes the routes. The copy stays in
  the store, so the review page can draw it. Rebuilding costs more than hiding an edge, but stays well under a
  second per candidate.

### 11. Results live in a documents graph

- **Context.** The review page, the dashboard and `/theseus apply` need each review's result after the request
  that made it, across redeploys.
- **Decision.** Keep each result as a `Doc` node `{key, text}` in a graph named `theseus__docs`, next to the
  graphs it describes.
- **Consequences.** No second database to run or back up. Documents are small, so this is enough; querying
  inside them is not needed.
- **Alternatives.** Files on the host: lost on a fresh host. A separate database: one more service.

## Code structure

### 12. Core and adapters

- **Context.** Theseus reads one cloud, one IaC format, one CI system and one language today. Threading AWS and
  Terraform names through the engine would make a second of any of them a rewrite.
- **Decision.** Core (`contracts/`, `importer/`, `graph/`, `engine/`, `agent/`, `mcp/`, `api/`) reasons on a neutral
  graph: principals, resources with a `category`, and fixed edge types. Everything vendor-specific lives in
  `adapters/<name>/` behind a protocol in `contracts/adapters.py`. Only `cli.py` and `api/app.py` pick adapters
  ([spec 08](../spec/08-core-and-adapters.md)).
- **Consequences.** `tests/unit/test_architecture.py` fails if core imports an adapter or a vendor name appears
  in `contracts/`. New features follow the same shape: cost (`monthly_cost`) and outages (`outages`) are methods
  on the cloud adapter, so core never names an AWS service. The cost is a protocol method for each new
  capability, which both humans approve.

## Models

### 13. Words explain, never approve

- **Context.** A PR's description is written by its author. If it could approve access, "this was pre-approved
  by security" would unblock anything.
- **Decision.** Only `theseus.yaml`, which its owners review, can make access to sensitive data acceptable. An
  intent requirement on sensitive data, or from a suspicious PR, is unapproved: it gets a status but no
  protection in the cut and no verdict fails on it.
- **Consequences.** A PR that asks for customer data in its text is still blocked until an owner adds it to
  `theseus.yaml`. The comment says so plainly.

### 14. Untrusted text is fenced, and the fix agent never sees it

- **Context.** Prompt injection: text written to make a model do something else.
- **Decision.** PR text, advisories and code comments reach a model only inside `<untrusted_...>` tags, after
  normalizing and masking secrets (`agent/screen.py`); the PR arrives as a tool result, not a user message. The
  fix agent gets structured context only. Steering can be flagged by three independent checks, any one enough.
- **Consequences.** The step that writes fixes has no injection surface from the PR. A suspicious flag can only
  make a review stricter.

### 15. One LLM-designed candidate, verified like the rest

- **Context.** When the cut is not cuttable (the intern's membership is both the way in and how she reads the
  logs she needs), no rule-based removal can pass. A structural fix, such as a new narrower role, needs design.
- **Decision.** The fix agent designs exactly one candidate, B, with five tools from the tool registry (called
  in process, not over MCP) and at most 8 calls. The engine simulates the submission itself, sends a failure
  back once, and checks every evidence ID and node ID in the rationale. Its title is built from its ops.
- **Consequences.** The LLM's creativity is used where it helps, and its output is held to the same verdict as a
  rule's. A fix that cites evidence that does not exist cannot slip through.
- **Alternatives.** Letting the model rank or choose among fixes: rejected (ranking is fixed code). Several LLM
  candidates: rejected, as one checked candidate is easier to review and cheaper.

### 16. Jev for small typed questions; a veto, never an approval

- **Context.** A review asks the same small questions many times (how sensitive is this store, does this text
  steer the review), where an LLM is slow and its confidence is not calibrated.
- **Decision.** Jev answers them with calibrated probabilities, one request per graph for sensitivity. It can
  mark a passing fix "needs a closer look" (above 0.5) but cannot make a failing one pass. A person's
  `sensitive_overrides` always win, so Jev is not asked about those resources.
- **Consequences.** Classifying the demo world takes about 0.3 seconds. When Jev is down the fast LLM answers,
  marked uncalibrated.

### 17. Record and replay

- **Context.** Tests must not touch the network; demos must not depend on a model being up; recordings must hold
  no secret.
- **Decision.** Every model call goes through one wrapper with three modes, `replay` (the default), `record` and
  `live`, keyed by a hash of the whole request. For the Try page, `ReplayedIntent` and `ReplayedJev` look answers
  up by content (the PR text, the resource ID), so the demo world can grow without re-recording.
- **Consequences.** `pytest -q` runs offline. Changing a prompt or the world's vocabulary needs a new recording,
  made with `THESEUS_MODE=record` and committed with its test.

## GitHub

### 18. Two workflows for one review

- **Context.** Planning a PR runs its own Terraform, which can run code. That run must not see a secret.
- **Decision.** `Theseus` plans with no secrets and uploads an artifact; `Theseus publish`, which GitHub always runs
  from `main`, reads the artifact as data and sends it with the token. The commit comes from the trusted event.
- **Consequences.** A malicious PR can plant code in the plan run but finds nothing to steal and cannot change
  the publish step. Fork PRs are reviewed too. The cost is a second workflow and an artifact hand-off.
- **Alternatives.** One workflow with the token: rejected as unsafe. Planning on the backend: rejected, since it
  would run untrusted Terraform on our server.

### 19. The App commits, and only under the world root

- **Context.** An applied fix must trigger a new review, and must never touch product code.
- **Decision.** The backend commits as the GitHub App (commits made with the Action's token trigger no new run),
  and refuses any commit that changes a file outside `THESEUS_WORLD_ROOT`.
- **Consequences.** Every applied fix is reviewed again automatically. The App could write product code in
  principle; this check is why it never does.

### 20. A review fails closed

- **Context.** A review can fail: a plan error, FalkorDB unreachable, a model error.
- **Decision.** The check shows "in progress" from the moment a PR opens, and a review that cannot finish
  completes the check as `failure` with the reason. The workflow's own failure is reported through
  `POST /review-failed`.
- **Consequences.** A PR is never merged because Theseus silently didn't run. The cost is that an outage of
  Theseus blocks merges until it is back or someone with admin rights overrides the check.

### 21. Suggestions before apply

- **Context.** `/theseus apply` alone means a reviewer must trust a command and read the result afterwards.
- **Decision.** The passing fix is posted as GitHub suggestions on the PR's own lines, which the author can read,
  edit and commit in one click. `/theseus apply` stays for fixes whose edits cannot sit on the diff.
- **Consequences.** The fix is visible before it is committed, in GitHub's own interface. A suggestion can only
  sit on lines of the diff, so some fixes still need `apply`.

### 22. Only the passing fix, named by what it does

- **Context.** Early comments listed four fixes, labelled A to D, when only one passed, and authors could not
  tell which to take.
- **Decision.** The comment and the review page offer only the fix that passes, named by what it does ("scope
  grants to required locations", "remove membership, add role and add policy"). The others are listed in one
  line with why they don't pass. The applied commit says "Apply the fix Theseus suggested", not a letter.
- **Consequences.** One clear action. The letters still exist in the result and for `/theseus apply B`.

### 23. The webhook handlers run in a thread pool

- **Context.** Found in a live test: the webhook route is `async`, but applying a fix calls GitHub synchronously
  for about 10 seconds. That blocked the event loop, GitHub gave up on the next delivery (`ClientDisconnect`),
  and a `/theseus review` on another PR was lost.
- **Decision.** The handlers run in FastAPI's thread pool (`run_in_threadpool`).
- **Consequences.** The next delivery is read while one is handled. Status codes are unchanged.

## Pages

### 24. Signed page links

- **Context.** The review page and the dashboard show a private repo's infrastructure, on a public hostname.
- **Decision.** Each link carries an HMAC-SHA256 of the page's document key with `THESEUS_TOKEN`, cut to 32 hex
  characters. A missing or wrong signature is a 404.
- **Consequences.** Anyone who can read the PR comment (and so already sees the repo) can open the page; the
  hostname alone shows nothing. There are no accounts to manage. A leaked link stays valid until the token is
  rotated.
- **Alternatives.** GitHub sign-in: rejected for the hackathon's time and for judges' convenience.

### 25. Pages read the graph live

- **Context.** A picture of the graph that is a copy can drift from what the engine reasoned on.
- **Decision.** The review page and the Graph view read the graph from FalkorDB when they load (`store.view`).
- **Consequences.** What a reviewer sees is exactly what was analyzed. A deleted graph shows as gone rather than
  stale.

### 26. The dashboard reads documents by prefix

- **Context.** Found in a live test: the dashboard's data took 5.5 seconds. Each kept review and finding cost two
  round trips to FalkorDB Cloud (about 140 ms each), and `main`'s whole graph was read back only to count it.
- **Decision.** `read_docs(prefix)` returns every document under a prefix in one query; the graph's size comes
  from the scan's coverage; the store remembers that the documents graph exists.
- **Consequences.** The data comes back in about 0.9 seconds on the server. The store protocol gained one method.

### 27. Try results are kept until the next deploy

- **Context.** Found in a live test: a Try run took about 40 seconds against FalkorDB Cloud, and visitors queued
  behind each other (one waited 78 seconds).
- **Decision.** Each preset's result is computed when the server starts and kept in memory. The fixtures and
  recordings change only with a deploy, which restarts the server, so a kept result is the one a new run would
  give.
- **Consequences.** A visitor gets an answer in under a second, and the page says the answers were computed on
  the server when it started, never copied from an answer key.

## Posture and incidents

### 28. Single points of failure from the engine's own routes

- **Context.** "Single point of failure" can be computed many ways, and a different definition from the rest of
  the product would confuse.
- **Decision.** A node is a single point of failure for a dependency (a code call or a `theseus.yaml`
  requirement) when it is on every valid route of it, using the same routes the engine uses for paths. A code
  call and a requirement for the same access count as one dependency.
- **Consequences.** Every number on the dashboard means the same as in a PR review. Each service's own role shows
  up as a single point for that service, which is accurate but obvious; the list is ranked by how many different
  actors depend on the node, so shared ones come first.

### 29. Cost from list prices, only for what the code declares

- **Context.** Real costs need billing data Theseus does not have.
- **Decision.** The cloud adapter estimates each resource at on-demand list price from what the Terraform declares
  (instance classes, task sizes, storage); anything billed by use counts as 0 and is marked so. A resource nothing
  reaches and no code calls is a possible saving.
- **Consequences.** The estimate is honest about what it counts and never guesses usage.

### 30. The outage basis is kept at posture time

- **Context.** An incident question ("what if Lambda is down?") needs each dependency's routes, which come from the
  engine's path analysis: seconds of FalkorDB queries.
- **Decision.** The posture run also computes an `OutageBasis`: each adapter's service tags per node, each
  dependency's valid routes, the code-to-code calls and the cost. It is kept in the posture document, and
  `blast` answers from it alone.
- **Consequences.** An incident answers in milliseconds, from the picker, a headline or a status feed, and means
  the same as the posture's single points. The answer reflects `main` as of the last posture run.

### 31. Incident headlines are matched, not read by a model

- **Context.** A headline pasted into the dashboard, or a status feed's title, is untrusted text.
- **Decision.** `read_incident` matches the text against the adapters' service and region names, deterministically;
  the provider breaks ties, and words such as "degraded" or "elevated" make it a degradation. No model reads it.
- **Consequences.** No injection surface and no model cost, and the same headline always gives the same answer. A
  headline that names no known service gets a clear "name a service" reply instead of a guess.

---

## Housekeeping

### 32. A PR's graphs live as long as the PR is open

- **Context.** Every review writes a base graph, a head graph and one graph per candidate fix, 3 to 5 graphs of
  about 0.8 MB each on FalkorDB Cloud, and nothing deleted them. On 2026-10-17 the instance held 116 graphs and
  used 96.3 MB of about 105 MB, 43 of them for 12 PRs, closed ones included. Its policy is `noeviction`, so a full
  instance refuses writes: the live site and every review fail.
- **Decision.** A PR keeps its base, its head and one fix graph for each candidate its newest review lists, and no
  more. A push loads the same names again, which replaces them; a fix an earlier review listed and the newest does
  not is deleted when the review is kept (`reviews.save`). The `closed` webhook, for a closed or a merged PR,
  deletes all of them; reopening reviews again and rebuilds them. A review of a PR that is already closed keeps
  none. The review itself, in the documents graph, is never deleted: the page keeps its text, the dashboard its
  history, and the page says its graphs were removed. `python -m theseus prune` does the same for graphs already
  there. It is a dry run that asks GitHub which PRs are closed or merged and lists their graphs; `--yes` deletes
  exactly the names it listed and prints the memory before and after. It never selects `*__main`, `fx__*`,
  `theseus__docs`, `theseus__benchmark`, the graphs of an open PR, or those of a PR GitHub does not list.
- **Consequences.** An instance holds at most about 5 graphs for each open PR, and a closed PR costs nothing. The
  page of a closed PR loses its graph and fix views. Housekeeping never fails a review: if the store cannot
  delete, the graphs stay for `prune` and the log says so; if the close handler cannot, the delivery fails with a
  502, so it shows in GitHub and can be redelivered. Two limits remain. A review that is still running when its PR
  closes finishes after the delete and leaves its graphs for `prune`. And graph names do not name the repo (spec
  03), so two repos that share a world root and a PR number share graphs: closing one deletes the other's, and
  `prune` keeps a number that is open in any repo.
- **Alternatives.** Delete the candidate graphs once the result is posted, as spec 03 says: the page reads each
  fix's graph live ([25](#25-pages-read-the-graph-live)), so its fix views would break. Delete by age: it would
  take the graphs of a PR that stays open for weeks.
