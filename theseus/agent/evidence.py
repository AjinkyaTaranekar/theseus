"""The evidence checker (06-agent.md): a fix's rationale may cite only evidence and nodes that exist.

The fix agent writes its rationale in free text. Before anyone reads it, every evidence ID it cites (`E3`)
must be one the agent was shown, and every node it names must be in the graph or the fix. A model's sentence
never adds a fact; this keeps it from pointing at one that is not there.
"""

from __future__ import annotations

import re
from collections.abc import Collection

# An evidence ID as the fix agent sees it: E and a number, as a whole word.
_EVIDENCE = re.compile(r"(?<![A-Za-z0-9_])E\d+(?![A-Za-z0-9_])")
# Around a word, but never part of a node ID: quotes, brackets, and sentence punctuation at the end.
_WRAP = "`'\"()[]{}<>*"
_TRAIL = ".,;:!?"
_POSSESSIVE = re.compile(r"['’]s$")


def evidence_refs(text: str) -> list[str]:
    """Every evidence ID the text cites, sorted and unique."""
    return sorted(set(_EVIDENCE.findall(text)))


def _word(token: str) -> str:
    word = token.strip(_WRAP)
    word = _POSSESSIVE.sub("", word).strip(_WRAP)
    return word.rstrip(_TRAIL).strip(_WRAP)


def node_refs(text: str, node_ids: Collection[str]) -> list[str]:
    """Every word of the text that claims to be a node, sorted and unique: one of the graph's `<scheme>://`
    prefixes, or a `<kind>:` prefix the graph's nodes use. A word of another kind (an action such as
    `s3:GetObject`, an ARN, a link) claims no node."""
    schemes = {i.split("://", 1)[0] for i in node_ids if "://" in i}
    kinds = {i.split(":", 1)[0] for i in node_ids if ":" in i and "://" not in i}
    found: set[str] = set()
    for token in text.split():
        word = _word(token)
        if "://" in word:
            if word.split("://", 1)[0] in schemes:
                found.add(word)
        elif ":" in word:
            kind, _, name = word.partition(":")
            if kind in kinds and name:
                found.add(word)
    return sorted(found)


def check(
    rationale: str, evidence_ids: Collection[str], node_ids: Collection[str], quoted: Collection[str] = ()
) -> list[str]:
    """The references in `rationale` that do not exist, sorted: evidence IDs not in `evidence_ids`, then node
    mentions not in `node_ids`. Words in `quoted` (the fix's own strings, such as its actions) are quotes of
    the fix, not claims about the graph, so they are never bad. An empty list means the rationale stands."""
    bad_evidence = [e for e in evidence_refs(rationale) if e not in evidence_ids]
    known = set(node_ids) | set(quoted)
    bad_nodes = [n for n in node_refs(rationale, node_ids) if n not in known]
    return [*bad_evidence, *bad_nodes]
