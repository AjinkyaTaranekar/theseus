<!--
PUBLISHING NOTES (delete this comment before you publish)

Placeholders to fill, all written as [[...]]:
  1. [[VIDEO LINK]]       the demo video, once S6 is uploaded
  2. [[YOUR OWN WORDS]]   two or three sentences only you can write (marked in the post)
  3. [[BLOG URL]]         not needed in the post; paste the final URL into the hackathon form

Before you publish:
  - The repo is PRIVATE today. Make it public (task S7) or the repo links below will 404 for judges.
  - Images: the repo is private, so raw GitHub image links do not work yet. Upload these files in the
    editor instead: docs/images/three-sources.png and docs/images/intern-before-after.png.
    (intern-before-after.png names the new role "intern-onboarding"; the real recorded run named it
    "intern-logs-read". The post avoids the name. docs/images/who-decides.png is left out on purpose:
    it says "Claude" for System 2 while the product's default model is GLM 5.3.)
  - Suggested tags (unconfirmed by the organizers): falkordb, hackathon, graphdatabase, security.
-->

# The pull request that changed no policy, and the graph that caught it

*How we reviewed a Terraform change as a graph in FalkorDB, proved the smallest safe fix on copies of that graph,
and left the final decision to a person. Built for FalkorDB Graph Hacks, Track 01.*

**In short:** one new Terraform resource let an intern reach the customer database through three hops of group
membership, role assumption and a secret. No rule was broken and no policy changed. We built **Theseus** to see
that kind of change before merge, to test every candidate fix on its own FalkorDB graph copy, and to cite the
config line behind every claim.

## The pull request that looked fine

Priya is an intern. A pull request adds her to the `support-engineers` group "so she can read prod logs during
onboarding". It adds one resource, a group membership. It touches no IAM policy.

Here is what that group can already do:

- It may assume the `prod-support` role.
- `prod-support` can read the app logs.
- It can also read `invoices/*`.
- And it can read the `prod-db-credentials` secret, which unlocks the customer database.

After the merge, an intern on her first day is three hops from the customer database. A scanner that checks each
resource against rules finds nothing to flag, because no rule is broken. A tool that compares policies finds
nothing to compare, because no policy changed. The risk is not in any one resource. It is in the *path*:

`user:priya-intern` → `group:support-engineers` → `role:prod-support` → `secret:prod-db-credentials` → `db:customer-db`

Paths through connected things are what graph databases are for, so we built the review on one.

## One graph per state, and every edge cites a line

Theseus reads three sources and keeps all three in the same graph:

- **What the PR says.** Its title and description, read by an LLM as untrusted data.
- **What Terraform allows.** The plan JSON, plus the `.tf` files, because a plan has no line numbers.
- **What the code calls.** The Python services, read with `ast` and never run.

![Theseus compares what the PR says, what Terraform allows and what the code does](../images/three-sources.png)

Each *state* of the world is its own FalkorDB graph: `demo-infra__main`, `demo-infra__pr85-base`,
`demo-infra__pr85-head`, and later one per candidate fix. Nodes use readable IDs (`user:priya-intern`,
`s3://demo-company-files/invoices/`). Every edge keeps its evidence, for example:

```json
{"address": "aws_iam_user_group_membership.priya_support", "file": "terraform/people.tf", "line": 83}
```

Nothing in a result is a claim without such a line behind it. If a line cannot be found, the edge says
`file="unknown"` and says why, and we never guess one.

## Step 1: what did this PR open?

One variable-length match finds every route from an actor to a resource:

```cypher
MATCH p = (a:Node {id: $actor})-[:MEMBER_OF|CAN_ASSUME|TRUSTS|RUNS_AS|CAN|UNLOCKS*1..7]->(r:Resource)
RETURN [rel IN relationships(p) | rel.eid] AS eids
```

The engine keeps a route only if every hop is a valid step and it ends on one grant. We run it on the base graph and
the head graph and diff the two lists into *opened*, *closed* and *unchanged* paths. For the intern PR:

| Opened path | Cites |
| --- | --- |
| Priya to `db:customer-db` | `people.tf:83`, `people.tf:56`, `roles.tf:36`, `data.tf:31` |
| Priya to `invoices/` | `people.tf:83`, `people.tf:56`, `roles.tf:30` |
| Priya to `secret:prod-db-credentials` | `people.tf:83`, `people.tf:56`, `roles.tf:36` |

Three paths opened, none closed. The reviewer sees them in a single PR comment, each with the file and line behind it.

## Step 2: is there a cheap fix? Ask the graph for a minimum cut

The obvious fix is to remove the smallest set of permissions that separates Priya from the data. That is a
minimum-cut question, and FalkorDB ships `algo.maxFlow` for it. We give each edge a capacity so the cut cannot
break access the app needs:

- **1,000,000** for an edge that a declared requirement in `theseus.yaml` depends on.
- **1,000** for a grant the code really calls.
- **1** for everything else.

```cypher
CALL algo.maxFlow({sourceNodes: ss, targetNodes: ts, capacityProperty: 'capacity',
                   relationshipTypes: ['FLOW']})
YIELD maxFlow, edges, edgeFlows
RETURN maxFlow, [e IN edges | e.eids] AS eids, edgeFlows
```

For the intern PR the max flow is 1,000,000 or more. That number is the answer: **no single permission can be
cut without breaking something a requirement needs.** The one edge that closes every route is her group
membership, and she needs it to read the logs. A rule can say "remove access". It cannot say "there is no
removal that works".

## Step 3: test every fix on its own copy

Because cutting is impossible, the agent has to design a different shape of fix. Theseus tests four candidates,
each on its own `GRAPH.COPY` of the head graph, then re-runs the full analysis on the copy:

| Candidate | Closes the paths? | Keeps required access? | Verdict |
| --- | --- | --- | --- |
| A: remove her from the group | Yes | No, she can no longer read the app logs | **fail** |
| B: a new, narrower role that reads only the app logs, designed by the LLM | Yes | Yes | **pass** |
| C: a Deny on invoices and the secret, conditioned on her user name | Only if the condition holds | Yes | **unknown** |
| D: stop `support-engineers` assuming `prod-support` | Yes | No, it breaks every support engineer | **fail** |

![Base, PR head and the agent's fix for the intern PR](../images/intern-before-after.png)

We do not "test" a fix by hiding an edge in a query. The engine changes the policy statement on the copy and
re-derives that statement's `CAN` edges, so the result matches what the Terraform patch would really produce.

Candidate C is **unknown** on purpose. We model a documented subset of IAM, and that condition key is outside it.
Returning UNKNOWN, and never defaulting to it, is part of the design. A person has to look.

## Where the models are allowed to help

This is the first rule in our `AGENTS.md`, and the product is built around it:

> **The engine decides facts; models propose; a person approves.**

- **FalkorDB and the engine** decide which paths exist, what the diff is, and whether required access survives.
- **An LLM** (GLM 5.3 through LiteLLM) reads the PR's stated intent and designs one candidate fix. It calls five
  tools from the graph registry (`explain_path`, `shortest_route`, `min_cut`, `check_requirements`,
  `simulate_fix`). It has **no tool that comments or commits**.
- **Its explanation must cite evidence IDs**, and a checker rejects any ID that does not exist in the graph. A
  claim the engine did not return cannot reach the page.
- **Text from outside**, such as PR bodies, advisories and commit messages, reaches a model only inside
  `<untrusted_...>` tags and never counts as evidence.
- **Jev** (TypeSafe's System 1 model) gives fast typed judgments, such as how sensitive a resource is. It can veto a
  fix, never approve one.
- **A person** approves. A reviewer replies `/theseus apply B`, the GitHub App commits the Terraform for the fix that
  passed, and Theseus reviews the new head.

The same ten-tool registry is also an MCP server, so an outside client such as Claude Code can ask the graph
directly. Ask "What does the intern PR open?" and it answers with the three paths above.

## Three things FalkorDB taught us

**1. `algo.maxFlow` wants one relationship type and no parallel edges.** Our graph has six traversal types and
sometimes two edges between the same pair. So before every call the engine writes one `FLOW` edge per
(source, target) pair, with the capacity summed, and runs the algorithm on those. It is a small step, and without
it the call is not usable on a real permissions graph.

**2. `algo.betweenness` is a sampled estimate.** On one of our graphs, the top "choke point" changed from one run to
the next. A ranking that changes between runs is not a fact, and facts are the one thing the engine promises, so the
results use the exact algorithm (Brandes) in Python. FalkorDB's own scores are still available for anyone who wants
them. At our size the exact version takes milliseconds.

**3. A graph per state is cheap to make and easy to leak.** `GRAPH.COPY` made candidate fixes trivial, and then our
shared FalkorDB Cloud instance hit its 100 MB cap because test graphs were never deleted. We now delete a PR's graphs
when the PR closes, and a test fails if it leaves a graph behind.

[[YOUR OWN WORDS: two or three sentences about what surprised you, or what you would do differently. Judges can
tell the difference between a write-up and a story.]]

## What it found, and how long it took

| Scenario | Opened dangerous paths | Max flow | Fix verdicts | Engine time |
| --- | --- | --- | --- | --- |
| `intern` | 3 (`customer-db`, `prod-db-credentials`, `invoices/`) | 1,000,000, not cuttable | A fail, B pass, C unknown, D fail | 1.4 s (first run) |
| `public-bucket` | 1 (`entry:internet` to `invoices/`) | 1 | A fail, S pass | 0.33 s |
| `code-pr` | none; *"Your code now reads customer-db"* | | | 0.11 s |

Measured with FalkorDB in Docker on a laptop. The `code-pr` row is a PR titled as a typo fix whose code starts
reading the customer database, the case where stated intent and effect disagree.

## What it cannot do

We would rather say this than have you find it:

- **A path is a modeled path, not an exploit.** Every step is labeled `configured`, `inferred` or `assumed`.
- **We support a subset of IAM:** Allow and Deny, wildcards, inline and attached policies, assume-role trust, and
  GitHub OIDC trust on `aud` and `sub`. `NotAction`, other condition keys, permission boundaries and SCPs return
  UNKNOWN.
- **The code reader is static.** A name built at runtime produces no edge and is listed as unknown, so a grant
  reached only that way can look unused.
- **The test data is ours.** The demo world is a synthetic online store: 137 planned Terraform resources, eight
  Python services and five GitHub workflows. There is no AWS account behind it.
- **Others got to graphs first.** Cartography and SubImage map what already runs, and Wiz does attack paths. Our
  narrow claim is to judge a change *before* merge and to test each fix against the access the app needs.

## How we used AI

We used Claude Code and Codex to write much of the code from task briefs written beforehand, one task per branch,
and the other teammate reviewed every diff. Humans wrote every `expected.json` answer key, and a hook blocks agents
from writing them. [`AI_USE.md`](https://github.com/AjinkyaTaranekar/theseus/blob/main/AI_USE.md) records which
agent wrote what and what we changed. This post was drafted with Claude Code from our README, specs and test
fixtures, and then checked and edited by us.

## Try it

- **Live:** <https://guest-box.tail27b7c5.ts.net>. Pick a preset and the real engine runs on FalkorDB.
- **A real review:** [demo PR #125](https://github.com/AjinkyaTaranekar/theseus/pull/125), where Theseus comments
  *"This PR would let priya-intern read and change customer-db"*.
- **Code:** <https://github.com/AjinkyaTaranekar/theseus>
- **Demo video:** [[VIDEO LINK]]

The name comes from two Greek stories: the thread through the labyrinth, and the Ship of Theseus, whose planks are
replaced one by one. Every pull request replaces a plank. Theseus checks the ship still floats.
