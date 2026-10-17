# Theseus architecture

This folder explains how Theseus is built and why. It is written for someone joining the project: an intern
who knows some Python and has heard of Terraform, but has never seen this code. Every claim points at the file
that implements it, so you can check it.

The specs in [`docs/spec/`](../spec/README.md) say what Theseus must do, section by section. These pages say
how the pieces fit together and which choices we made along the way. When the two disagree, the spec wins until
both humans change it ([`AGENTS.md`](../../AGENTS.md)).

## Reading order

| Page | What it covers |
| --- | --- |
| [01. Overview](01-overview.md) | What Theseus does, the one rule it never breaks, the components, and a PR's whole journey |
| [02. FalkorDB](02-falkordb.md) | Why a graph database, one graph per state, how graphs are named, loaded, copied and read back, and the documents graph |
| [03. Cypher](03-cypher.md) | Every Cypher query Theseus runs, copied from the code, with what it answers and who calls it |
| [04. The engine](04-engine.md) | Paths, requirements, the diff, the minimum cut, candidate fixes and their verdicts |
| [05. Models: the LLM and Jev](05-models.md) | Exactly when a model is called, what it may decide, untrusted text, and record and replay |
| [06. Features](06-features.md) | Every feature, one section and one diagram each: PR review, fixes, findings, scan, posture, incidents, the pages, MCP and the CLI |
| [07. GitHub and deployment](07-github-and-deploy.md) | The GitHub App, the two-workflow Action, webhooks, the deploy and the settings |
| [08. Decisions](08-decisions.md) | Architecture decision records: the context, the decision, the consequences and what we turned down |
| [09. Glossary](09-glossary.md) | Every term these pages use, in plain words |

## The short version

Theseus reviews infrastructure pull requests as a graph. A GitHub Action plans the Terraform at the PR's base
and head commits. The backend turns each plan, the workflow files and the service code into a graph of who can
become whom and who can read what, and loads each into its own FalkorDB graph. Cypher finds every route from a
person, a workflow or a service to sensitive data; the diff between the two graphs is what the PR opens.
FalkorDB's `algo.maxFlow` finds the fewest edges that close those routes without breaking access the company
needs. Fixes are tried on copies of the graph made with `GRAPH.COPY`, and the one that passes is offered on the
PR as a GitHub suggestion.

Language models help in two places only: reading what the PR says it is for, and designing one candidate fix.
Neither can make anything true. The engine decides facts; models propose; a person approves.

## How these pages are kept

- They describe the code on `main`. When you change a behaviour they describe, change the page in the same PR.
- Cypher is copied, never paraphrased: [03. Cypher](03-cypher.md) quotes `theseus/graph/queries.py` and
  `theseus/graph/store.py` as written.
- Diagrams are [Mermaid](https://mermaid.js.org/), which GitHub renders in place.
