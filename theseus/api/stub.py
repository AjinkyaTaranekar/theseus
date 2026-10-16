"""A valid AnalysisResult built from an expected.json, so the comment, the Action and the Try-it page can be
built before the engine exists (task F3). Real analysis replaces it in E3 and A5."""

from __future__ import annotations

from typing import Any

from theseus.contracts.result import (
    AnalysisResult,
    BeyondIntent,
    Candidate,
    CandidateSource,
    CutEdge,
    EdgeType,
    Evidence,
    Grant,
    Intent,
    MinCut,
    PathRecord,
    PathStep,
    RequirementStatus,
    ResourceChange,
    StagingToProd,
    UnusedGrant,
)
from theseus.contracts.schema import CORE_KINDS, parse_id

STUB = "stub"


class _Evidence:
    """Hands out evidence IDs, one per distinct cite, in the order they are first seen."""

    def __init__(self) -> None:
        self.by_cite: dict[str, str] = {}
        self.items: dict[str, Evidence] = {}

    def id_for(self, cite: str) -> str:
        if cite not in self.by_cite:
            eid = f"E{len(self.by_cite) + 1}"
            self.by_cite[cite] = eid
            file, _, line = cite.rpartition(":")
            if file and line.isdigit():
                self.items[eid] = Evidence(address=STUB, file=file, line=int(line))
            else:
                self.items[eid] = Evidence(address=STUB, file=cite or "unknown")
        return self.by_cite[cite]


def _edge_type(src: str, dst: str) -> EdgeType:
    """The edge a stub path most likely took, from the two node kinds alone."""
    a, b = parse_id(src)[0], parse_id(dst)[0]
    if b == "group":
        return "MEMBER_OF"
    if b == "role":
        return {"workflow": "TRUSTS", "workload": "RUNS_AS"}.get(a, "CAN_ASSUME")
    if a not in CORE_KINDS and b not in CORE_KINDS:
        return "UNLOCKS"
    return "CAN"


def _path(n: int, item: dict[str, Any], ev: _Evidence) -> PathRecord:
    route = item.get("route") or [item["actor"], item["target"]]
    cites = item.get("cites") or []
    steps = [
        PathStep(
            src=src,
            type=_edge_type(src, dst),
            dst=dst,
            evidence=ev.id_for(cites[i] if i < len(cites) else "unknown"),
        )
        for i, (src, dst) in enumerate(zip(route, route[1:], strict=False))
    ]
    return PathRecord(id=f"P{n}", actor=item["actor"], target=item["target"], grants=["read"], steps=steps)


def _source(candidate: str) -> tuple[CandidateSource, str]:
    if candidate == "B":
        return "llm", STUB
    if candidate.startswith("H"):
        return "human", STUB
    return "rule", "theseus"


def result_from_expected(expected: dict[str, Any]) -> AnalysisResult:
    """A valid result whose projection matches `expected`; its headline, or "stub" when it names none. Fields
    it lacks stay empty."""
    ev = _Evidence()
    n = 0

    def paths(key: str) -> list[PathRecord]:
        nonlocal n
        out = []
        for item in expected.get(key) or []:
            n += 1
            out.append(_path(n, item, ev))
        return out

    opened, closed, unchanged = paths("opened"), paths("closed"), paths("unchanged")

    intent = None
    if expected.get("intent") is not None:
        raw = expected["intent"]
        intent = Intent(
            purpose=raw.get("purpose", STUB),
            grants=[Grant(principal=p, access=a, resource=r) for p, a, r in raw.get("grants", [])],
            suspicious=raw.get("suspicious", False),
            stated=raw.get("stated", True),
        )

    min_cut = None
    if expected.get("min_cut") is not None:
        raw = expected["min_cut"]
        cut_ev = ev.id_for("unknown")
        min_cut = MinCut(
            sources=sorted({p.actor for p in opened}),
            sinks=sorted({p.target for p in opened}),
            value=raw.get("value", raw.get("value_at_least", 0)),
            cuttable=raw.get("cuttable", False),
            cut=[
                CutEdge(eid=f"c{i}", src=s, type=t, dst=d, evidence=cut_ev)
                for i, (s, t, d) in enumerate(raw.get("cut", []), start=1)
            ],
        )

    recommended = expected.get("recommended")
    candidates = []
    for cid, verdict in sorted((expected.get("candidates") or {}).items()):
        source, proposed_by = _source(cid)
        candidates.append(
            Candidate(
                id=cid,
                source=source,
                proposed_by=proposed_by,
                title=f"Candidate {cid}",
                verdict=verdict,
                reason=STUB,
                recommended=cid == recommended,
            )
        )

    stub_ev = ev.id_for("unknown")
    return AnalysisResult(
        scenario=expected.get("scenario"),
        mode=expected["mode"],
        headline=expected.get("headline") or STUB,
        intent=intent,
        changes=[
            ResourceChange(address=address, type=address.split(".")[0], action=action)
            for action, address in expected.get("changes") or []
        ],
        opened=opened,
        closed=closed,
        unchanged=unchanged,
        requirements=[
            RequirementStatus(id=k, status=v) for k, v in sorted((expected.get("requirements") or {}).items())
        ],
        unknowns=sorted(expected.get("unknowns") or []),
        min_cut=min_cut,
        candidates=candidates,
        rotate=sorted(expected.get("rotate") or []),
        unused_grants=[
            UnusedGrant(workload=w, resource=r, access=a, eid=STUB, evidence=stub_ev)
            for w, r, a in expected.get("unused_grants") or []
        ],
        use_beyond_intent=[
            BeyondIntent(workload=w, resource=r, access=a, file="unknown", line=0)
            for w, r, a in expected.get("use_beyond_intent") or []
        ],
        staging_to_prod=[
            StagingToProd(actor=a, target=t, path_id=STUB) for a, t in expected.get("staging_to_prod") or []
        ],
        evidence=ev.items,
    )
