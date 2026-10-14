# 01. Product

## What Theseus does

Theseus reviews a change to infrastructure-as-code before it merges. It answers one question:

> What dangerous access paths does this change open or close, and what is the smallest change that blocks
> them without removing access people and apps need?

It reads three sources of truth and reports where they disagree:

| Source | Read from | Example gap |
| --- | --- | --- |
| What the PR says | PR title and body, read by Claude | "Your PR says logs. Your change grants the customer database." |
| What Terraform allows | The Terraform plan JSON and `.tf` files | A grant on a path to sensitive data |
| What the code calls | Python service code in the repo | A grant no code ever calls: remove it and nothing breaks |

## Three modes, one engine

| Mode | Trigger | Starting points | Output | Human step |
| --- | --- | --- | --- | --- |
| PR | A pull request changes Terraform or service code | Every actor in the graph | One PR comment, a check run, candidate fixes | A reviewer comments `/theseus apply B` |
| Finding | An advisory or scanner report arrives (`POST /finding`) | The workflows or workloads the finding names, assumed compromised | A containment PR and a list of secrets to rotate | A reviewer merges the containment PR |
| Scan | A push to `main`, or `POST /scan` | Every actor in `main` | A GitHub issue listing dangerous paths already in `main`, with grants the code never calls | A reviewer merges the fix PR |

## The four story beats

The video and the demos follow these beats. Each beat has one fixture in `fixtures/` (see `02-demo-world.md`).

| Beat | Fixture | What the judge sees | What the agent does |
| --- | --- | --- | --- |
| 1. See it | `intern` | Adding `priya-intern` to `support-engineers` passes Checkov but opens 3 paths to sensitive data | Posts a PR comment with the cited path and "says versus grants" |
| 2. Fix it | `intern` | Max flow 1,000,000: no single permission can go. Four candidate fixes tested on graph copies | Commits fix B after `/theseus apply B` |
| 3. Contain it | `compromised-action` | A compromised Action reaches the customer database through the staging docs-site workflow | Opens a containment PR and lists exactly the secrets to rotate |
| 4. Nobody breaks | `unused-grant`, `code-pr` | `support-portal` may read the database secret, but its code never asks for it. A "typo fix" PR starts calling it | Proposes removing the unused grant; flags the code PR |

The `public-bucket` fixture is a preset on the Try-it page, not a video scene.

## Who decides what

| Layer | Decides | Never does |
| --- | --- | --- |
| A person | Which fix ships | Nothing changes without them |
| Claude (System 2) | Proposes structural fixes, reads PR intent, writes explanations | Decide what is reachable; call write tools |
| Jev (System 1) | Fast typed judgments with probabilities: sensitivity, urgency, "could this fix break legitimate use?" | Approve a fix (it can only veto) |
| The engine and FalkorDB | What is reachable, which requirements hold, which fixes pass | Guess: unsupported rules return UNKNOWN |

## Glossary

| Term | Meaning |
| --- | --- |
| Actor | A starting point for paths: a user, a workflow, a workload, or `entry:internet` |
| Principal | Any node that can hold permissions: user, group, role, workload, workflow, entry |
| Resource | A data location: an S3 bucket prefix, a Secrets Manager secret, or a database |
| Sensitive | A resource whose class is `confidential` or `regulated` |
| Path | A chain of edges from an actor to a resource, ending in a grant edge (`CAN` or `UNLOCKS`) |
| Dangerous path | A path from an actor to a sensitive resource that no requirement covers |
| Requirement | Access that must keep working, from `theseus.yaml` or from the PR's stated intent |
| Evidence | The file, line, Terraform address and statement Sid behind an edge |
| Edge kind | `configured` (read from config), `inferred` (derived by a rule), `assumed` (for example "this workflow is compromised"), `unknown` (outside the supported subset) |
| State graph | One FalkorDB graph per state: `main`, `pr42-base`, `pr42-head`, `pr42-fix-B` |
| Candidate | A proposed fix, written as patch ops and tested on its own graph copy |
| Verdict | `pass`, `fail`, `unknown` or `invalid`, decided by the engine for each candidate |
| Minimum cut | The fewest edges whose removal separates an actor from its dangerous targets without cutting required access |
| UNKNOWN | The honest answer when a rule is outside the supported subset |

## Out of scope for the hackathon

- Clouds other than AWS, Kubernetes RBAC, live account reads, Cartography
- IAM features beyond the subset in `04-engine.md`: permission boundaries, SCPs, resource-based
  policies other than S3 bucket policies, KMS key policies
- Service code in languages other than Python
- Phases 4 and 5 of the roadmap (survives the outage, dead stacks and cost, region placement)
