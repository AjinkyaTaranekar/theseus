"""Resource and statement citations from source at the same revision as the plan."""

from __future__ import annotations

import json
import logging
import posixpath
from functools import lru_cache

import hcl2
from lark import Token, Tree
from lark.exceptions import UnexpectedInput
from pydantic import Field

from theseus.adapters.terraform.plan import unindexed
from theseus.contracts.result import Contract, Evidence
from theseus.errors import IngestError

log = logging.getLogger(__name__)


class _Declaration(Contract):
    kind: str
    label: str
    name: str | None = None
    line: int
    source: str | None = None
    sids: dict[str, list[int]] = Field(default_factory=dict)


def _children(tree: Tree, kind: str) -> list[Tree]:
    return [c for c in tree.children if isinstance(c, Tree) and c.data == kind]


def _text(tree: Tree | Token, source: str) -> str:
    return source[tree.meta.start_pos : tree.meta.end_pos].strip() if isinstance(tree, Tree) else str(tree)


def _literal(tree: Tree | Token, source: str) -> str | None:
    raw = _text(tree, source)
    if "${" in raw or "%{" in raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, str) else None


def _key(tree: Tree, source: str) -> str:
    raw = _text(tree.children[0], source)
    return _literal(tree.children[0], source) or raw


def _value(tree: Tree) -> Tree:
    return next(c for c in reversed(tree.children) if isinstance(c, Tree))


def _unwrap(tree: Tree) -> Tree:
    while tree.data == "expr_term" and len(tree.children) == 1 and isinstance(tree.children[0], Tree):
        tree = tree.children[0]
    return tree


def _statement_lines(expression: Tree, source: str) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    document = _unwrap(expression)
    if document.data == "function_call":
        identifiers = _children(document, "identifier")
        arguments = _children(document, "arguments")
        if not identifiers or _text(identifiers[0], source) != "jsonencode" or len(arguments) != 1:
            return found
        values = [c for c in arguments[0].children if isinstance(c, Tree)]
        if len(values) != 1:
            return found
        document = _unwrap(values[0])
    if document.data != "object":
        return found
    for element in _children(document, "object_elem"):
        if _key(element, source) != "Statement":
            continue
        value = _unwrap(_value(element))
        statements = (
            [_unwrap(c) for c in value.children if isinstance(c, Tree)] if value.data == "tuple" else [value]
        )
        for statement in statements:
            if statement.data != "object":
                continue
            for field in _children(statement, "object_elem"):
                if _key(field, source) == "Sid":
                    sid = _literal(_value(field), source)
                    if sid is not None:
                        found.setdefault(sid, []).append(field.meta.line)
    return found


@lru_cache(maxsize=128)
def _declarations(text: str) -> tuple[_Declaration, ...] | None:
    try:
        # Version 5 exposes a raw tree through parses; newer versions name it parses_to_tree.
        tree = getattr(hcl2, "parses_to_tree", hcl2.parses)(text + "\n")
    except UnexpectedInput:
        log.info("source cannot be parsed; its evidence remains unknown")
        return None
    if not isinstance(tree, Tree):
        raise IngestError("HCL parser did not return a syntax tree")
    bodies = _children(tree, "body")
    if len(bodies) != 1:
        return ()
    declarations = []
    for block in _children(bodies[0], "block"):
        identifiers = _children(block, "identifier")
        if not identifiers:
            continue
        kind = _text(identifiers[0], text)
        labels = [
            _literal(c, text)
            for c in block.children
            if (isinstance(c, Tree) and c.data == "string")
            or (isinstance(c, Token) and c.type == "STRING_LIT")
        ]
        if kind not in {"resource", "module"} or len(labels) != (2 if kind == "resource" else 1):
            continue
        if any(label is None for label in labels):
            continue
        body = _children(block, "body")[0]
        sources = []
        sids: dict[str, list[int]] = {}
        for attribute in _children(body, "attribute"):
            key = _key(attribute, text)
            if kind == "module" and key == "source":
                sources.append(_literal(_value(attribute), text))
            elif kind == "resource" and key in {"policy", "assume_role_policy"}:
                for sid, lines in _statement_lines(_value(attribute), text).items():
                    sids.setdefault(sid, []).extend(lines)
        declarations.append(
            _Declaration(
                kind=kind,
                label=labels[0],
                name=labels[1] if kind == "resource" else None,
                line=block.meta.line,
                source=sources[0] if len(sources) == 1 else None,
                sids=sids,
            )
        )
    return tuple(declarations)


def locate(files: dict[str, str], address: str, part: str | None = None) -> Evidence:
    """The unique declaration or literal statement Sid, or unknown evidence with the reason."""

    def missing(reason: str) -> Evidence:
        return Evidence(address=address, part=part, file="unknown", note=reason)

    def scope(directory: str) -> list[tuple[str, _Declaration]] | None:
        result = []
        for path, text in sorted(files.items()):
            if path.endswith(".tf") and posixpath.dirname(path) == directory:
                declarations = _declarations(text)
                if declarations is None:
                    return None
                result.extend((path, declaration) for declaration in declarations)
        return result

    pieces = unindexed(address).split(".")
    directory = "terraform" if any(p.startswith("terraform/") for p in files) else ""
    while len(pieces) > 2 and pieces[0] == "module":
        declarations = scope(directory)
        if declarations is None:
            return missing("module source syntax could not be parsed")
        modules = [d for _, d in declarations if d.kind == "module" and d.label == pieces[1]]
        if len(modules) != 1 or not modules[0].source or not modules[0].source.startswith(("./", "../")):
            return missing(f"module {pieces[1]} has no unique local source")
        directory = posixpath.normpath(posixpath.join(directory, modules[0].source))
        if directory == ".." or directory.startswith("../"):
            return missing("module source is outside the world root")
        pieces = pieces[2:]
    if len(pieces) != 2:
        return missing("address is not a managed resource address")
    declarations = scope(directory)
    if declarations is None:
        return missing("resource source syntax could not be parsed")
    found = [
        (path, d) for path, d in declarations if d.kind == "resource" and (d.label, d.name) == tuple(pieces)
    ]
    if len(found) != 1:
        return missing("resource declaration is missing or ambiguous")
    path, declaration = found[0]
    if part is None:
        line = declaration.line
    else:
        lines = declaration.sids.get(part, [])
        if len(lines) != 1:
            return missing("literal statement Sid is missing or ambiguous")
        line = lines[0]
    return Evidence(address=address, part=part, file=path, line=line)
