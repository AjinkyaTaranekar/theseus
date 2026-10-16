# 08. Core and adapters

Theseus v1 reads one cloud (AWS), one IaC format (Terraform), one CI system (GitHub Actions) and one
language (Python with boto3). Each of those sits behind an adapter, so a second cloud or format is added
next to the first instead of being threaded through the engine. The demo world and every fixture stay AWS and
Terraform; only the code is shaped for more.

## The rule

- **Core** reasons about a neutral graph: principals, resources with a category, and the edge types in
  `03-graph.md`. It never names a cloud, an IaC format, a CI system or an SDK. Core is `contracts/`,
  `importer/`, `graph/`, `engine/`, `agent/`, `mcp/` and `api/`.
- **Adapters** (`theseus/adapters/<name>/`) are the only code that knows one. Each turns its inputs into
  contract types and back.
- **Imports point one way.** Adapters import `theseus.contracts`, `theseus.errors` and themselves, nothing else.
  Core never imports an adapter. Only the composition roots, `cli.py` and `api/app.py`, pick the adapters, and
  they pass them to core in `Deps.adapters`.
- `tests/unit/test_architecture.py` enforces all of this and keeps vendor names out of `contracts/`. A failure
  there means code is in the wrong place, not that the test is wrong.

## The four axes

| Axis | Protocol (`contracts/adapters.py`) | v1 adapter | What it owns | A second one could be |
| --- | --- | --- | --- | --- |
| IaC format | `IacAdapter` | `adapters/terraform/` | Reading plan output into `IacResource`s and unknown fields; the file and line of an address; writing patch ops back as text edits | CloudFormation, Pulumi, CDK output |
| Cloud | `CloudAdapter` | `adapters/aws/` | Resource kinds and their categories; ARNs; the IAM subset; identity and permission edges; the patch-op catalog and applying ops | GCP IAM, Azure RBAC, Kubernetes RBAC |
| CI | `CiAdapter` | `adapters/github/` | Pipeline files into Workflow and Action nodes, USES edges, and the identity each pipeline presents (issuer and subjects) | GitLab CI, CircleCI |
| Code | `CodeAdapter` | `adapters/python/` | Service code into CALLS, REQUESTS and HAS_ENV edges, for one language and one cloud SDK | TypeScript with the AWS SDK, Python with a GCP SDK |

Which rules belong to which adapter in `04-engine.md`: Terraform owns sections 2, 3 and 19; AWS owns sections 4,
5 and 13 and the IAM rules of section 6; GitHub owns the workflow `sub` values in section 6; Python owns section
7. The rest of `04-engine.md` is core.

## What crosses the boundary

- **Node IDs** follow one grammar: `<kind>:<name>`, or `<scheme>://<path>` for a location inside a store. The
  core kinds (`user`, `group`, `role`, `workload`, `workflow`, `action`, `entry`, `req`, `finding`) are fixed.
  Every other kind is a resource kind that a cloud adapter declares, with its category. AWS keeps the short kinds
  it has (`s3`, `secret`, `db`, `dynamodb`); a second cloud uses its own prefixes (`gcs://`, `gcp-secret:`), so
  IDs never collide.
- **Resource category:** one of `RESOURCE_CATEGORIES`, stored on every Resource node with its `provider`,
  and carried as a label. The names are [Cartography's ontology
  labels](https://github.com/cartography-cncf/cartography/blob/master/cartography/models/ontology/labels.py)
  (`ObjectStorage`, `FileStorage`, `BlockStorage`, `Database`, `Secret`, `EncryptionKey`, `AIModel`), plus
  `LogStore`, `MessageQueue`, `MessageTopic` and `DataStream` for data that ontology does not cover. Users,
  groups, roles and workloads carry Cartography's labels too. Core reasons on the category, never on the kind
  or the IaC type: the rotate list is every reachable `Secret`, and UNLOCKS runs from a `Secret` to a
  `Database`. Matching Cartography means a Cartography graph of a live account can feed Theseus (below).
- **Edge types are core and neutral.** MEMBER_OF is membership, CAN_ASSUME impersonation, TRUSTS federated trust
  from a CI identity, RUNS_AS a workload's identity, CAN a permission on data, UNLOCKS a credential that opens a
  database. An adapter maps its constructs onto these. A new edge type is a contract change.
- **Access** is `read`, `write` or `assume` in every cloud.
- **Evidence** points at the IaC: `address`, `part` (the piece of the resource that decided the edge, such as an
  IAM statement's Sid), `file`, `line`.
- **Patch ops** are an envelope, `{provider, op, args}`. The cloud adapter owns the catalog: it validates `args`,
  applies ops to `IacResource`s, and publishes the JSON schema the LLM's fix tool uses. The IaC adapter writes ops
  back as text. AWS's catalog is `04-engine.md` section 13, typed in `adapters/aws/ops.py`.
- **Changes:** candidate rules decide what to change in graph terms, as a `Change`: remove an edge, narrow a grant
  to some resources, restrict a trust to some subjects, or deny some principals. The cloud adapter turns a
  `Change` into ops, or returns none when it cannot express it. So rules stay in core. Optional `Change.evidence` selects existing `(address, part)` grant evidence for a
  revert, so removing a newly added statement does not delete a pre-existing statement on the same edge.
  `Change.added_only` requires the adapter to check optional `base_resources` for a pre-existing statement;
  newly visible edges alone do not prove the source policy gained a statement.
- **Patch traits:** `CloudAdapter.patch_traits(ops)` validates operations and reports
  `PatchTraits.adds_broad_wildcard`. The simulator computes direct permission losses and unknown graph steps
  from the rebuilt graph; core never reads vendor-specific operation arguments to rank candidates.

## Catalogs: adapters as data

An adapter that maps many vendor types the same way keeps the mapping in a YAML catalog, not code. AWS's is
`adapters/aws/catalog.yaml`, with a `data` section (where data lives, its category, and the actions that
read or write it) and a `workloads` section (what runs code, and how to find the role it runs as). A
contract test checks every action and ARN against AWS's own service reference. Adding an AWS service is a
catalog entry; `adapters/aws/README.md` says how, and `adapters/README.md` how to add a connector.

## A Cartography source

An organization that does not use Terraform can still be analyzed from a
[Cartography](https://github.com/cartography-cncf/cartography) graph of its live accounts. A source in place
of the IaC adapter reads Cartography's raw IAM facts and resources and feeds the same AWS cloud adapter, so
Theseus's own evaluation (with UNKNOWN instead of guesses) decides access, not Cartography's edges. It gives
scan and finding mode on live state. Without a plan there is no PR diff, fixes are rendered as policy JSON
or CLI steps instead of `.tf` edits, and evidence cites ARNs instead of files and lines.

## Adding an adapter

1. Write `adapters/<name>/` against its protocol. Import only `theseus.contracts`, `theseus.errors` and itself.
2. Give it fixtures and golden tests the way AWS and Terraform have them.
3. Wire it in `cli.py` and `api/app.py`.
4. If it needs a contract change, make it additive (a field, a resource category, an op in its own catalog),
   and both humans approve it.

## What v1 does not abstract

- One provider per graph. Kinds and `provider` are per node, so a mixed graph is possible, but nothing tests it.
- The protocols are shaped by one implementation each. The second implementation may add methods; it never
  changes the ones that exist.
- The demo world, the fixtures, the IAM subset and every `expected.json` are AWS and Terraform.
- The fix agent's prompt and context (`06-agent.md`) are written for AWS IAM. A second cloud supplies its own
  prompt context from its adapter; the op schema already comes from `ops_schema()`.
