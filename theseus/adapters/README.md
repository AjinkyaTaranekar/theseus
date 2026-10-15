# Adapters and connectors

Theseus's core reasons about a neutral graph: principals, resources with a category, and a fixed set of edge
types. It never names a cloud, an IaC format, a CI system or an SDK. Everything that does lives here, one package
per adapter. The rules are in [`docs/spec/08-core-and-adapters.md`](../../docs/spec/08-core-and-adapters.md);
this page is the practical guide.

## What is here

| Package | Protocol (`contracts/adapters.py`) | What it turns into graph rows |
| --- | --- | --- |
| [`terraform/`](terraform/) | `IacAdapter` | Plan JSON into resources; `.tf` lines for evidence; fixes written back as `.tf` edits |
| [`aws/`](aws/) | `CloudAdapter` | Resources into principals, data, workloads, and IAM edges, driven by [`aws/catalog.yaml`](aws/catalog.yaml) |
| [`github/`](github/) | `CiAdapter` | Workflow files into Workflow and Action nodes, `USES` edges, and each workflow's OIDC subjects |
| [`python/`](python/) | `CodeAdapter` | Service code into `CALLS`, `REQUESTS` and `HAS_ENV` edges |

## The shared vocabulary

Every adapter maps its own things onto the same vocabulary, so the engine, the queries and the PR comment never
change when an adapter is added.

- **Node kinds.** Users, groups, roles, workloads, workflows, actions and `entry:internet` are core. Everything
  that holds data is a resource whose kind the adapter declares (`s3`, `secret`, `gcs`, ...).
- **Ontology labels.** A resource's category is one of [Cartography's ontology
  labels](https://github.com/cartography-cncf/cartography/blob/master/cartography/models/ontology/labels.py)
  (`ObjectStorage`, `Database`, `Secret`, `FileStorage`, `EncryptionKey`, `AIModel`, ...) or one of ours for data
  that ontology does not cover (`LogStore`, `MessageQueue`, `MessageTopic`, `DataStream`). The node carries it
  as a label. Users, groups and roles carry `UserAccount`, `UserGroup` and `PermissionRole`; workloads carry
  `Function`, `ComputeService`, `ComputeInstance` or `CICDPipeline` where one fits. The constants are in
  `contracts/schema.py`.
- **Edges.** `MEMBER_OF`, `CAN_ASSUME`, `TRUSTS`, `RUNS_AS`, `CAN` (with grants `read` and `write`),
  `UNLOCKS`, plus `USES`, `CALLS`, `REQUESTS`, `HAS_ENV`. A new edge type is a contract change.
- **Evidence.** Every edge cites where it came from: an address, the part of it that decided the edge (an IAM
  Sid, a binding), a file and a line, or `file: "unknown"` with a note. Never a guessed line.

Using Cartography's labels means a query written for Theseus reads the same on a Cartography graph, and the other
way round.

## Adding to an existing adapter

For AWS, most additions are data, not code: a new data service or a new kind of workload is an entry in
[`aws/catalog.yaml`](aws/catalog.yaml). [`aws/README.md`](aws/README.md) walks through it.

## Adding a connector

A connector is a new adapter. Typical ones:

| Connector | Protocol | Reuses |
| --- | --- | --- |
| Another cloud (GCP, Azure) | `CloudAdapter` with its own catalog | Terraform, GitHub, Python as they are |
| Kubernetes RBAC | `CloudAdapter` (Roles, RoleBindings, ServiceAccounts, Secrets) | A manifests or Helm `IacAdapter` |
| Another IaC format (CloudFormation, Pulumi, CDK output) | `IacAdapter` | The AWS cloud adapter as it is |
| Another CI system (GitLab CI) | `CiAdapter` | The cloud adapters' trust matching, through `CiIdentity` |
| Another language (TypeScript with the AWS SDK) | `CodeAdapter` | Everything else |
| A Cartography graph (live accounts, no Terraform) | A source in place of `IacAdapter` | The AWS cloud adapter and its catalog |

Steps:

1. **Pick the protocol** in `contracts/adapters.py` and read what it must return.
2. **Create `adapters/<name>/`.** Import only `theseus.contracts`, `theseus.errors` and your own package.
   `tests/unit/test_architecture.py` fails on anything else, and fails if a core module imports you.
3. **Map onto the vocabulary above.** Pick the node kinds, and for each resource kind a category from
   `RESOURCE_CATEGORIES`. If nothing fits, propose a category: it is a contract change both humans approve.
4. **Prefer data to code.** If the adapter maps many types the same way, put the mapping in a YAML catalog, as
   AWS does, and validate it against the vendor's own reference where one exists.
5. **Never guess.** Anything you cannot evaluate exactly (a condition, an unsupported field, a value unknown
   until apply) makes the edge `unknown`, with the reason in its evidence note.
6. **Test with fixtures**, the way AWS and Terraform are tested: unit tests per rule, and a golden test on a
   fixture with a hand-written `expected.json`.
7. **Wire it in** the composition roots, `cli.py` and `api/app.py`, which build `Adapters` and pass them in
   `Deps`.

## A Cartography connector

Organizations that do not manage their cloud with Terraform can still be analyzed. Cartography snapshots live
accounts into a graph, with the same ontology labels this repo uses. A Cartography source would:

- read the **raw** IAM facts Cartography collects (principals, policies, statements, trust policies and the
  resources they name), and turn them into the AWS adapter's inputs;
- **not** reuse Cartography's own `CAN_READ`-style edges. Theseus evaluates the statements itself, so conditions
  and permission boundaries give `unknown` instead of a guess;
- give **scan mode** and **finding mode** on the live account: dangerous paths, unused grants, choke points,
  blast radius and the secrets to rotate.

What changes without Terraform: there is no plan to diff, so PR mode needs a proposed change given another way
(patch ops, simulated on a graph copy). Fixes are rendered as IAM policy JSON or CLI steps instead of `.tf`
edits, and evidence cites ARNs and policy names instead of files and lines. Cartography writes to Neo4j today; a
FalkorDB backend for it is on the roadmap in `docs/project-overview.md`.
