"""The fix agent (06-agent.md): the LLM designs candidate B with the graph tools, and the engine verifies it.

The model works from structured inputs only, never the PR's text: the resources that grant access, the data
and its sensitivity, the requirements, the opened paths and the minimum cut. It may call five registry tools,
at most MAX_TOOL_CALLS times in all, and finishes by calling `submit_fix`. The engine then simulates the
submitted ops itself; the model's own `simulate_fix` results only inform the model. A fix that fails or is
invalid goes back once with its verdict and reason, and whatever comes back is candidate B. Its rationale may
cite only evidence and nodes that exist (agent/evidence.py): it is asked for once more, then replaced by a
sentence built from the ops. Every step is in the trace.

Evidence keys are long (`file:line:address:part`), so the model sees each as `E<n>`: the keys of the base and
head graphs, sorted and numbered. Every alias maps to evidence that exists, and tool results use the same
aliases.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterable
from typing import Any

from pydantic import Field, ValidationError

from theseus.agent.evidence import check, evidence_refs
from theseus.agent.intent import LlmCaller
from theseus.agent.llm import LlmReply
from theseus.agent.trace import Recorder
from theseus.contracts.engine import CandidateDraft, GraphState
from theseus.contracts.result import (
    Candidate,
    Contract,
    Evidence,
    MinCut,
    PatchOp,
    PathRecord,
    Requirement,
    ToolCall,
)
from theseus.contracts.schema import PRINCIPAL, RESOURCE
from theseus.engine.analyze import step_evidence
from theseus.engine.simulate import candidate_graph
from theseus.errors import ModelError, PatchError
from theseus.importer.build import build_rows
from theseus.mcp.tools import Registry, ToolContext, ToolError, build_registry

log = logging.getLogger(__name__)

PURPOSE = "fix"
CANDIDATE_ID = "B"
TITLE = "The agent's fix"
SUBMIT = "submit_fix"
MAX_TOOL_CALLS = 8
MAX_SENTENCES = 3
# The registry tools the fix agent may call (06-agent.md), in the order it is offered them.
TOOLS = ("explain_path", "shortest_route", "min_cut", "check_requirements", "simulate_fix")
# Edges that say who holds access and who grants it. The resources their evidence cites are the ones a fix
# edits; RUNS_AS cites the compute resource, whose settings decide no access.
ACCESS_EDGES = frozenset({"MEMBER_OF", "CAN", "CAN_ASSUME", "TRUSTS"})

SYSTEM_PROMPT = " ".join(
    [
        "You design the smallest safe fix for an infrastructure pull request that opened dangerous access"
        " paths.",
        "You get the IAM configuration as resources with addresses and statement Sids, the requirements"
        " that must keep working (including what this PR is for), the dangerous paths the PR opened, and the"
        " result of a minimum-cut search.",
        "A deterministic engine applies your ops to a copy of the configuration and checks the result. It"
        " rejects a fix that leaves a dangerous path, opens a new one, breaks a requirement, breaks a code"
        " call, or relies on a condition it cannot evaluate.",
        "When the minimum cut says no permission can be removed without breaking a requirement, design a new,"
        " narrower role that grants exactly what the requirement needs, trusted only by the principal that"
        " needs it, and remove the access that opened the paths. Prefer that over granting permissions"
        " directly to a user.",
        "Use simulate_fix to test your ops before you submit. Use exact ARNs, least privilege, and no"
        " conditions. Do not change anything the requirements depend on. Cite evidence IDs in the rationale.",
    ]
)
INSTRUCTIONS = (
    f"Call the tools one at a time, at most {MAX_TOOL_CALLS} calls in all, then call {SUBMIT}. Pass graph"
    " names from graphs. Evidence IDs such as E3 are listed in evidence; tool results use the same IDs."
)


class AgentFix(Contract):
    """Candidate B as the engine verified it, the rationale that stands, the evidence it cites (`E<n>` to the
    evidence key, and each key's evidence for the result), every step in order, and the LLM's milliseconds."""

    candidate: Candidate
    rationale: str
    cites: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    trace: list[ToolCall] = Field(default_factory=list)
    llm_ms: int = 0


class _Submission(Contract):
    rationale: str
    ops: list[PatchOp] = Field(min_length=1)


# Schemas ----------------------------------------------------------------------------------------------------


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """The schema with every local `$ref` replaced by its definition and `$defs` removed, so each part stands
    alone wherever it is embedded: a reference in an embedded part would resolve against the wrong root."""

    def walk(node: Any, defs: dict[str, Any], depth: int) -> Any:
        if depth > 32:
            raise ValueError("schema nests too deep to inline; is it recursive?")
        if isinstance(node, list):
            return [walk(item, defs, depth + 1) for item in node]
        if not isinstance(node, dict):
            return node
        scope = {**defs, **node.get("$defs", {})}
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            target = walk(scope[ref.removeprefix("#/$defs/")], scope, depth + 1)
            rest = {k: walk(v, scope, depth + 1) for k, v in node.items() if k not in ("$ref", "$defs")}
            return {**target, **rest}
        return {k: walk(v, scope, depth + 1) for k, v in node.items() if k != "$defs"}

    out: dict[str, Any] = walk(schema, {}, 0)
    return out


def _function(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


def submit_tool(op_schema: dict[str, Any]) -> dict[str, Any]:
    """`submit_fix`: a rationale and the ops, each op checked against the cloud adapter's catalog schema."""
    return _function(
        SUBMIT,
        "Submit your fix: the patch operations, and why they work.",
        {
            "type": "object",
            "properties": {
                "rationale": {
                    "type": "string",
                    "description": f"At most {MAX_SENTENCES} sentences, citing evidence IDs such as E3.",
                },
                "ops": {"type": "array", "minItems": 1, "items": inline_refs(op_schema)},
            },
            "required": ["rationale", "ops"],
            "additionalProperties": False,
        },
    )


def tool_specs(registry: Registry, op_schema: dict[str, Any]) -> list[dict[str, Any]]:
    """The tools the model is offered: the five registry tools, then `submit_fix`. `simulate_fix` takes its
    ops in the catalog's schema and no candidate ID: every fix the agent tries is candidate B."""
    specs = []
    for name in TOOLS:
        tool = registry.get(name)
        parameters = inline_refs(tool.input_schema)
        if name == "simulate_fix":
            parameters["properties"].pop("candidate_id", None)
            parameters["required"] = [r for r in parameters.get("required", []) if r != "candidate_id"]
            parameters["properties"]["ops"]["items"] = inline_refs(op_schema)
        specs.append(_function(name, tool.description, parameters))
    return [*specs, submit_tool(op_schema)]


# Context ----------------------------------------------------------------------------------------------------


def evidence_aliases(states: Iterable[GraphState]) -> tuple[dict[str, str], dict[str, Evidence]]:
    """`E1`, `E2`, ... for every piece of evidence in these graphs, numbered in key order (key to alias), and
    each key's evidence."""
    found: dict[str, Evidence] = {}
    for state in states:
        found.update(step_evidence(state.rows))
    keys = sorted(found)
    return {k: f"E{n}" for n, k in enumerate(keys, start=1)}, {k: found[k] for k in keys}


def _plain(value: Any) -> Any:
    """The value without empty parts (None, "", [] and {}), which tell the model nothing."""
    if isinstance(value, dict):
        kept = {k: _plain(v) for k, v in value.items()}
        return {k: v for k, v in kept.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _aliased(value: Any, aliases: dict[str, str]) -> Any:
    """The value with every evidence key replaced by its alias."""
    if isinstance(value, dict):
        return {k: _aliased(v, aliases) for k, v in value.items()}
    if isinstance(value, list):
        return [_aliased(v, aliases) for v in value]
    if isinstance(value, str):
        return aliases.get(value, value)
    return value


def _alias_number(alias: str) -> int:
    return int(alias[1:])


def fix_context(
    head: GraphState,
    base: GraphState,
    opened: list[PathRecord],
    cut: MinCut | None,
    requirements: list[Requirement],
    approved: set[str],
    statuses: dict[str, str],
    aliases: dict[str, str],
    evidence: dict[str, Evidence],
) -> dict[str, Any]:
    """What the fix agent knows, as JSON: the graphs' names; the resources that grant access, with their
    values; every data resource with its sensitivity and who decided it; the principals on the opened paths,
    the cut and the requirements; every requirement with its status and whether it is approved (an
    unapproved one a fix may remove); the opened paths with their steps; the minimum cut; and the evidence
    those cite."""
    nodes = {n.id: n for n in head.rows.nodes}
    cited = {ev.address for e in head.rows.edges if e.type in ACCESS_EDGES for ev in e.evidence}
    named = {nid for p in opened for nid in p.route} | {r.principal for r in requirements}
    if cut is not None:
        named |= {node for edge in cut.cut for node in (edge.src, edge.dst)}
    used: set[str] = set()

    def alias(key: str) -> str:
        if key in aliases:
            used.add(aliases[key])
            return aliases[key]
        return key

    paths = [
        {
            "id": p.id,
            "actor": p.actor,
            "target": p.target,
            "sensitivity": p.sensitivity,
            "unknown": p.unknown,
            "route": p.route,
            "steps": [
                {
                    "from": s.src,
                    "type": s.type,
                    "to": s.dst,
                    "grants": s.grants,
                    "evidence": alias(s.evidence),
                }
                for s in p.steps
            ],
        }
        for p in opened
    ]
    min_cut = None
    if cut is not None:
        min_cut = {
            "sources": cut.sources,
            "sinks": cut.sinks,
            "value": cut.value,
            "cuttable": cut.cuttable,
            "cut": [
                {"src": e.src, "type": e.type, "dst": e.dst, "evidence": alias(e.evidence)} for e in cut.cut
            ],
        }
    by_alias = {a: k for k, a in aliases.items()}
    return {
        "graphs": {"base": base.name, "head": head.name},
        "resources": [
            {"address": r.address, "type": r.type, "values": _plain(r.values)}
            for r in sorted(head.world.resources, key=lambda r: r.address)
            if r.address in cited
        ],
        "data": [
            {
                "id": n.id,
                "category": n.category,
                "sensitivity": n.sensitivity,
                "decided_by": n.sensitivity_source,
                "props": n.props,
            }
            for n in sorted(head.rows.nodes, key=lambda n: n.id)
            if RESOURCE in n.labels
        ],
        "principals": [
            {"id": nid, "props": nodes[nid].props}
            for nid in sorted(named)
            if nid in nodes and PRINCIPAL in nodes[nid].labels
        ],
        "requirements": [
            {
                "id": r.id,
                "principal": r.principal,
                "access": r.access,
                "resource": r.resource,
                "source": r.source,
                "status": statuses.get(r.id, "unknown"),
                "approved": r.id in approved,
            }
            for r in requirements
        ],
        "opened": paths,
        "min_cut": min_cut,
        "evidence": {
            a: evidence[by_alias[a]].model_dump(mode="json", exclude_none=True)
            for a in sorted(used, key=_alias_number)
        },
    }


def messages_for(context: dict[str, Any]) -> list[dict[str, Any]]:
    """The system prompt from 06-agent.md, then the context as JSON and how to use the tools."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Context:\n" + _json(context) + "\n\n" + INSTRUCTIONS},
    ]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# Rationale --------------------------------------------------------------------------------------------------


def plain_rationale(text: str) -> str:
    """One line of at most MAX_SENTENCES sentences."""
    line = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+", line)
    return " ".join(sentences[:MAX_SENTENCES])


def template_rationale(ops: list[PatchOp], verdict: str) -> str:
    """The sentence that stands when the model's rationale keeps citing what does not exist: built from the
    ops and the engine's verdict only."""
    many = len(ops) != 1
    return (
        f"The agent's fix makes {len(ops)} change{'s' if many else ''} ({', '.join(op.op for op in ops)}); "
        f"the engine's verdict is {verdict}."
    )


def _strings(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {s for v in value.values() for s in _strings(v)}
    if isinstance(value, list):
        return {s for v in value for s in _strings(v)}
    return {value} if isinstance(value, str) else set()


# The loop ---------------------------------------------------------------------------------------------------


class _Session:
    """One conversation with the model: its messages, the tool budget left, and the time it took."""

    def __init__(
        self,
        llm: LlmCaller,
        context: ToolContext,
        recorder: Recorder,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        aliases: dict[str, str],
    ) -> None:
        self.llm = llm
        self.context = context
        self.recorder = recorder
        self.messages = messages
        self.tools = tools
        self.aliases = aliases
        self.registry = Registry(recorder.registry.get(name) for name in TOOLS)
        self.calls_left = MAX_TOOL_CALLS
        self.llm_ms = 0
        self.model = ""
        self.simulated = False
        self._ids = 0

    def ask(self, force: bool) -> LlmReply:
        choice: dict[str, Any] | str = {"type": "function", "function": {"name": SUBMIT}} if force else "auto"
        start = time.perf_counter()
        reply = self.llm.call(PURPOSE, self.messages, self.tools, choice)
        self.llm_ms += int((time.perf_counter() - start) * 1000)
        self.model = reply.model
        return reply

    def _call_id(self) -> str:
        self._ids += 1
        return f"call_{self._ids}"

    def _echo(self, reply: LlmReply, name: str, arguments: dict[str, Any]) -> str:
        call_id = self._call_id()
        call = {"id": call_id, "type": "function", "function": {"name": name, "arguments": _json(arguments)}}
        self.messages.append({"role": "assistant", "content": reply.content or None, "tool_calls": [call]})
        return call_id

    def answer(self, call_id: str, content: str) -> None:
        self.messages.append({"role": "tool", "tool_call_id": call_id, "content": content})

    def until_submit(self, force: bool = False) -> tuple[str, dict[str, Any]]:
        """Runs the model's tool calls until it calls submit_fix: that call's ID and its arguments. Once the
        budget is spent, or after an answer with no tool call, submit_fix is forced."""
        while True:
            forced = force or self.calls_left <= 0
            reply = self.ask(forced)
            if reply.tool == SUBMIT:
                return self._echo(reply, SUBMIT, reply.arguments), reply.arguments
            if forced:
                raise ModelError(f"{PURPOSE} ({reply.key}): the model did not call {SUBMIT}")
            if reply.tool is None:
                self.messages.append({"role": "assistant", "content": reply.content})
                self.messages.append({"role": "user", "content": f"Call {SUBMIT} with your fix now."})
                force = True
                continue
            self.calls_left -= 1
            arguments = dict(reply.arguments)
            if reply.tool == "simulate_fix":
                arguments["candidate_id"] = CANDIDATE_ID
            call_id = self._echo(reply, reply.tool, arguments)
            self.answer(call_id, self.run(reply.tool, arguments))

    def run(self, name: str, arguments: dict[str, Any]) -> str:
        """The tool's result as the model reads it, evidence keys aliased; or `error: ...` for the model."""
        try:
            tool = self.registry.get(name)
        except ToolError as e:
            self.recorder.note(name, arguments, f"error: {e}")
            return f"error: {e}"
        try:
            result = tool.handler(self.context, arguments)
        except ToolError as e:
            return f"error: {e}"
        data = result.data
        if name == "simulate_fix":
            self.simulated = True
            # A wall-clock field would make the conversation differ on every run, and replay depends on it.
            data = {k: v for k, v in data.items() if k != "seconds"}
        return _json(_aliased(data, self.aliases))


def _parse(arguments: dict[str, Any]) -> tuple[_Submission | None, str]:
    try:
        return _Submission.model_validate(arguments), ""
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'input'}: {err['msg']}" for err in e.errors()
        )
        return None, f"{SUBMIT}: invalid input: {problems}"


def design_fix(
    llm: LlmCaller,
    context: ToolContext,
    head: GraphState,
    base: GraphState,
    opened: list[PathRecord],
    cut: MinCut | None,
    requirements: list[Requirement],
    statuses: dict[str, str],
    registry: Registry | None = None,
) -> AgentFix:
    """Candidate B, verified by the engine, with its checked rationale and the trace of every step.

    `context` holds the store, both graphs, the approved requirements a fix must keep and the actors whose
    opened paths it must close; `requirements` are all of them (config and intent) and `statuses` their
    status in the head graph. Raises ModelError when the model gives no fix the engine can read."""
    approved = {r.id for r in context.requirements}
    aliases, evidence = evidence_aliases([base, head])
    messages = messages_for(
        fix_context(head, base, opened, cut, requirements, approved, statuses, aliases, evidence)
    )
    actors = context.fix_actors if context.fix_actors is not None else sorted({p.actor for p in opened})
    final_graph = candidate_graph(head.name, CANDIDATE_ID)
    with Recorder(registry or build_registry()) as recorder:
        session = _Session(
            llm,
            context,
            recorder,
            messages,
            tool_specs(recorder.registry, context.adapters.cloud.ops_schema()),
            aliases,
        )

        def verify(submission: _Submission) -> Candidate:
            draft = CandidateDraft(
                id=CANDIDATE_ID, source="llm", proposed_by=session.model, title=TITLE, ops=submission.ops
            )
            start = time.perf_counter()
            candidate = context.engine.simulate(
                context.store, head, draft, actors, context.requirements, context.adapters
            )
            session.simulated = False
            ms = int((time.perf_counter() - start) * 1000)
            recorder.note(
                "verify_fix", {"candidate_id": CANDIDATE_ID}, f"candidate B: {candidate.verdict}", ms
            )
            return candidate

        submission: _Submission | None = None
        candidate: Candidate | None = None
        call_id = ""
        for attempt in (1, 2):
            call_id, arguments = session.until_submit()
            parsed, problem = _parse(arguments)
            if parsed is None:
                recorder.note(SUBMIT, arguments, f"error: {problem}")
                if attempt == 2:
                    break
                session.answer(call_id, f"error: {problem}. Call {SUBMIT} again with ops from the catalog.")
                continue
            submission = parsed.model_copy(update={"rationale": plain_rationale(parsed.rationale)})
            recorder.note(
                SUBMIT,
                {
                    "rationale": submission.rationale,
                    "ops": [op.model_dump(mode="json") for op in submission.ops],
                },
                f"{len(submission.ops)} op(s) submitted",
            )
            candidate = verify(submission)
            if attempt == 2 or candidate.verdict not in ("fail", "invalid"):
                break
            session.answer(
                call_id,
                f"The engine's verdict on your fix: {candidate.verdict}. Reason: {candidate.reason}."
                f" Correct the fix, then call {SUBMIT} again.",
            )
        if submission is None:
            raise ModelError(f"{PURPOSE}: the model never submitted a fix the engine can read")
        if candidate is None or candidate.ops != submission.ops or session.simulated:
            # The last fix that parsed is B; its graph must be the last one written as candidate B.
            candidate = verify(submission)
        rationale = _checked_rationale(session, recorder, call_id, submission, candidate, head, base, aliases)
        context.created[:] = [g for g in context.created if g != final_graph]
        context.cleanup()
        trace = recorder.calls
    by_alias = {a: k for k, a in aliases.items()}
    cites = {a: by_alias[a] for a in sorted(evidence_refs(rationale), key=_alias_number) if a in by_alias}
    return AgentFix(
        candidate=candidate,
        rationale=rationale,
        cites=cites,
        evidence={key: evidence[key] for key in sorted(cites.values())},
        trace=trace,
        llm_ms=session.llm_ms,
    )


def _node_ids(head: GraphState, base: GraphState, ops: list[PatchOp], context: ToolContext) -> set[str]:
    """Every node a rationale may name: the base and head graphs', and the ones the fix adds."""
    ids = {n.id for state in (head, base) for n in state.rows.nodes}
    try:
        patched = head.world.model_copy(deep=True)
        patched.resources = context.adapters.cloud.apply_ops(patched.resources, ops)
    except PatchError:
        return ids
    return ids | {n.id for n in build_rows(patched, {}, context.adapters).nodes}


def _checked_rationale(
    session: _Session,
    recorder: Recorder,
    call_id: str,
    submission: _Submission,
    candidate: Candidate,
    head: GraphState,
    base: GraphState,
    aliases: dict[str, str],
) -> str:
    """The rationale that stands: the model's if every reference in it exists, its second try if that one's
    do, else a sentence built from the ops. Each decision is a `check_evidence` step in the trace."""
    nodes = _node_ids(head, base, submission.ops, session.context)
    quoted = _strings([op.args for op in submission.ops])
    known = set(aliases.values())
    rationale = submission.rationale
    bad = check(rationale, known, nodes, quoted)
    if not bad:
        recorder.note("check_evidence", {"rationale": rationale, "bad": []}, "every reference exists")
        return rationale
    recorder.note(
        "check_evidence", {"rationale": rationale, "bad": bad}, f"unknown: {', '.join(bad)}; asked once more"
    )
    session.answer(
        call_id,
        f"Your rationale names references that do not exist: {', '.join(bad)}. Call {SUBMIT} again with the"
        " same ops and a rationale that cites only evidence IDs from evidence and nodes from the context.",
    )
    _, arguments = session.until_submit(force=True)
    parsed, problem = _parse(arguments)
    if parsed is not None:
        if parsed.ops != submission.ops:
            log.warning("fix: the rationale retry changed the ops; the verified ops stand")
        rationale = plain_rationale(parsed.rationale)
        bad = check(rationale, known, nodes, quoted)
        if not bad:
            recorder.note("check_evidence", {"rationale": rationale, "bad": []}, "every reference exists")
            return rationale
    else:
        bad = [problem]
    rationale = template_rationale(submission.ops, candidate.verdict)
    recorder.note(
        "check_evidence",
        {"rationale": rationale, "bad": bad},
        f"still bad: {', '.join(bad)}; replaced with a sentence built from the ops",
    )
    return rationale
