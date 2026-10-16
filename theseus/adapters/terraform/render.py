"""Verified, source-preserving Terraform edits for the patch catalog in spec 04 sections 13 and 19."""

from __future__ import annotations

import hashlib
import json
import logging
import posixpath
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import hcl2
from lark import Token, Tree
from lark.exceptions import UnexpectedInput

from theseus.adapters.terraform.source_index import _children, _key, _text, _unwrap, _value, locate
from theseus.contracts.result import PatchOp
from theseus.errors import PatchError

log = logging.getLogger(__name__)
GENERATED = "terraform/theseus_fixes.tf"
SUB = "token.actions.githubusercontent.com:sub"
_FIELDS = {
    "remove_membership": {"user", "group"},
    "add_membership": {"user", "group"},
    "remove_statement": {"policy_address", "sid"},
    "set_statement_resources": {"policy_address", "sid", "resources"},
    "set_oidc_sub": {"role", "patterns"},
    "add_policy": {"principal", "statements"},
    "add_role": {"name", "trust_principals", "statements"},
}


@dataclass(frozen=True)
class _Ref:
    text: str


@dataclass(frozen=True)
class _Block:
    file: str
    kind: str
    label: str
    node: Tree

    @property
    def address(self) -> str:
        return f"{self.kind}.{self.label}"


def _values(node: Tree) -> list[Tree]:
    return [c for c in node.children if isinstance(c, Tree) and c.data != "new_line_or_comment"]


@lru_cache(maxsize=128)
def _tree(text: str) -> Tree:
    try:
        result = getattr(hcl2, "parses_to_tree", hcl2.parses)(text + "\n")
    except UnexpectedInput as exc:
        raise PatchError("Terraform source cannot be parsed") from exc
    if not isinstance(result, Tree):
        raise PatchError("HCL parser did not return a syntax tree")
    return result


def _string(raw: str) -> str:
    if re.search(r"(?<!\$)\$\{|(?<!%)%\{", raw):
        raise PatchError("dynamic Terraform string cannot be verified")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise PatchError("expected a literal Terraform string") from exc
    if not isinstance(value, str):
        raise PatchError("expected a literal Terraform string")
    return value.replace("$${", "${").replace("%%{", "%{")


def _fields(node: Tree, source: str) -> dict[str, Tree]:
    node = _unwrap(node)
    if node.data == "block":
        node = _children(node, "body")[0]
    if node.data not in {"body", "object"}:
        raise PatchError("expected a literal object or resource body")
    result = {}
    for field in _children(node, "attribute" if node.data == "body" else "object_elem"):
        key = _key(field, source)
        if node.data == "object":
            raw = _text(field.children[0], source)
            if raw.startswith('"'):
                key = _string(raw)
            elif not re.fullmatch(r"[A-Za-z_][\w-]*", raw):
                raise PatchError("dynamic Terraform object key cannot be verified")
        if key in result:
            raise PatchError(f"duplicate field {key}")
        result[key] = field
    return result


def _field(node: Tree, key: str, source: str) -> Tree:
    fields = _fields(node, source)
    if key not in fields:
        raise PatchError(f"missing field {key}")
    return _value(fields[key])


def _decode(node: Tree, source: str) -> Any:
    node = _unwrap(node)
    raw = _text(node, source)
    if node.data == "object":
        return {key: _decode(_value(field), source) for key, field in _fields(node, source).items()}
    if node.data == "tuple":
        return [_decode(c, source) for c in _values(node)]
    if node.data == "string":
        return _string(raw)
    if re.fullmatch(r"aws_iam_(?:user|group|role|openid_connect_provider)\.[\w-]+(?:\.(?:name|arn))?", raw):
        return _Ref(raw)
    if raw in {"true", "false", "null"} or node.data in {"int_lit", "float_lit"}:
        return json.loads(raw)
    raise PatchError("unsupported Terraform expression; cannot verify edit")


def _scan(files: dict[str, str]) -> list[_Block]:
    result = []
    seen = set()
    for path, source in sorted(files.items()):
        if (
            "\\" in path
            or path.startswith("/")
            or re.match(r"^[A-Za-z]:", path)
            or posixpath.normpath(path) != path
            or ".." in path.split("/")
        ):
            raise PatchError("Terraform source path must stay under the world root")
        if not path.endswith(".tf"):
            continue
        for body in _children(_tree(source), "body"):
            for block in _children(body, "block"):
                ids = _children(block, "identifier")
                if not ids or _text(ids[0], source) != "resource":
                    continue
                labels = [
                    _string(_text(c, source))
                    for c in block.children
                    if (isinstance(c, Tree) and c.data == "string")
                    or (isinstance(c, Token) and c.type == "STRING_LIT")
                ]
                if len(labels) != 2:
                    raise PatchError("resource header cannot be verified")
                key = (posixpath.dirname(path), *labels)
                if key in seen:
                    raise PatchError("duplicate resource declaration")
                seen.add(key)
                _fields(block, source)
                result.append(_Block(path, labels[0], labels[1], block))
    return result


def _at(files: dict[str, str], address: str) -> _Block:
    if "[" in address or "]" in address:
        raise PatchError("an instance-specific edit cannot change a shared declaration")
    evidence = locate(files, address)
    found = [b for b in _scan(files) if b.file == evidence.file and b.node.meta.line == evidence.line]
    if len(found) != 1:
        raise PatchError(f"resource {address} is missing or ambiguous")
    block = found[0]
    if {"count", "for_each"} & _fields(block.node, files[block.file]).keys():
        raise PatchError("an instanced resource cannot be edited independently")
    return block


def _principal(files: dict[str, str], principal: str, *, generating: bool = False) -> _Block:
    kind, sep, name = principal.partition(":")
    if not sep or kind not in {"user", "group", "role"} or not name:
        raise PatchError("principal must be a user, group or role ID")
    found = []
    for b in _scan(files):
        if b.kind == f"aws_iam_{kind}" and posixpath.dirname(b.file) == "terraform":
            if _decode(_field(b.node, "name", files[b.file]), files[b.file]) == name:
                found.append(b)
    if len(found) != 1:
        raise PatchError(f"principal {principal} has no unique root declaration")
    block = _at(files, found[0].address)
    if generating and "provider" in _fields(block.node, files[block.file]):
        raise PatchError("cannot infer the provider configuration for a generated resource")
    return block


def _name(node: Tree, source: str, files: dict[str, str]) -> str:
    value = _decode(node, source)
    if isinstance(value, _Ref) and value.text.endswith(".name"):
        block = _at(files, value.text.rsplit(".", 1)[0])
        value = _decode(_field(block.node, "name", files[block.file]), files[block.file])
    if not isinstance(value, str):
        raise PatchError("membership name cannot be resolved")
    return value


def _trust_principal(files: dict[str, str], principal: str, account: str | None) -> tuple[str, _Ref]:
    if not isinstance(account, str) or not re.fullmatch(r"[0-9]{12}", account):
        raise PatchError("role trust needs an explicit 12-digit world account")
    block = _principal(files, principal, generating=True)
    source = files[block.file]
    if "path" in _fields(block.node, source) and _decode(_field(block.node, "path", source), source) != "/":
        raise PatchError("non-root IAM principal paths are outside the engine's canonical ARN subset")
    kind, _, name = principal.partition(":")
    return f"arn:aws:iam::{account}:{kind}/{name}", _Ref(block.address)


def _document(block: _Block, files: dict[str, str], attribute: str = "policy") -> Tree:
    source = files[block.file]
    node = _unwrap(_field(block.node, attribute, source))
    ids = _children(node, "identifier")
    arguments = _children(node, "arguments")
    if (
        node.data != "function_call"
        or not ids
        or _text(ids[0], source) != "jsonencode"
        or len(arguments) != 1
    ):
        raise PatchError("policy must be a literal object inside jsonencode")
    values = _values(arguments[0])
    if len(values) != 1 or _unwrap(values[0]).data != "object":
        raise PatchError("policy must be a literal object inside jsonencode")
    return _unwrap(values[0])


def _statements(document: Tree, source: str) -> tuple[Tree, list[Tree]]:
    node = _unwrap(_field(document, "Statement", source))
    if node.data == "object":
        return node, [node]
    if node.data != "tuple":
        raise PatchError("Statement must be a literal object or list")
    values = [_unwrap(c) for c in _values(node)]
    if any(c.data != "object" for c in values):
        raise PatchError("Statement must contain literal objects")
    return node, values


def _statement(block: _Block, files: dict[str, str], sid: str) -> tuple[Tree, Tree]:
    if block.kind not in {
        "aws_iam_policy",
        "aws_iam_user_policy",
        "aws_iam_group_policy",
        "aws_iam_role_policy",
        "aws_s3_bucket_policy",
    }:
        raise PatchError("target is not a supported policy resource")
    source = files[block.file]
    container, statements = _statements(_document(block, files), source)
    found = [
        s
        for s in statements
        if "Sid" in _fields(s, source) and _decode(_field(s, "Sid", source), source) == sid
    ]
    if len(found) != 1:
        raise PatchError(f"statement {sid} is missing or ambiguous")
    return container, found[0]


def _quote(value: str) -> str:
    encoded = []
    for char in value:
        if 0xD800 <= ord(char) <= 0xDFFF:
            raise PatchError("Terraform strings cannot contain unpaired Unicode surrogates")
        if char in {'"', "\\"}:
            encoded.append("\\" + char)
        elif ord(char) < 32:
            encoded.append(f"\\u{ord(char):04x}")
        else:
            encoded.append(char)
    return '"' + "".join(encoded).replace("${", "$${").replace("%{", "%%{") + '"'


def _hcl(value: Any, indent: int = 0) -> str:
    if isinstance(value, _Ref):
        return value.text
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, list):
        return "[" + ", ".join(_hcl(v, indent) for v in value) + "]"
    if isinstance(value, dict):
        body = "\n".join(
            " " * (indent + 2) + _quote(k) + " = " + _hcl(v, indent + 2) for k, v in sorted(value.items())
        )
        return "{\n" + body + "\n" + " " * indent + "}"
    return json.dumps(value)


def _replace(files: dict[str, str], path: str, node: Tree, text: str) -> None:
    source = files[path]
    files[path] = source[: node.meta.start_pos] + text + source[node.meta.end_pos :]


def _erase(files: dict[str, str], path: str, start: int, end: int) -> None:
    source = files[path]
    line_start = source.rfind("\n", 0, start) + 1
    line_end = source.find("\n", end)
    if line_end < 0:
        line_end = len(source)
    if not source[line_start:start].strip() and not source[end:line_end].strip():
        start, end = line_start, min(line_end + 1, len(source))
    files[path] = source[:start] + source[end:]


def _remove_member(files: dict[str, str], path: str, container: Tree, member: Tree) -> None:
    start, end = member.meta.start_pos, member.meta.end_pos
    commas = [c for c in container.children if isinstance(c, Token) and str(c) == ","]
    after = next((c for c in commas if c.start_pos >= end), None)
    before = [c for c in commas if c.end_pos <= start]
    if after is not None:
        source = files[path]
        files[path] = source[: after.start_pos] + source[after.end_pos :]
        _erase(files, path, start, end)
    elif before:
        _erase(files, path, start, end)
        comma = before[-1]
        source = files[path]
        files[path] = source[: comma.start_pos] + source[comma.end_pos :]
    else:
        _erase(files, path, start, end)


def _strings(value: Any, context: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise PatchError(f"{context} must be a list of strings")
    return sorted(set(value))


def _iam(statements: Any) -> dict[str, Any]:
    if not isinstance(statements, list):
        raise PatchError("statements must be a list")
    result = []
    seen = set()
    for s in statements:
        if (
            not isinstance(s, dict)
            or set(s) - {"sid", "effect", "actions", "resources", "condition"}
            or not {"sid", "effect", "actions", "resources"} <= s.keys()
        ):
            raise PatchError("invalid statement arguments")
        if not isinstance(s["sid"], str) or s["sid"] in seen or s["effect"] not in ("Allow", "Deny"):
            raise PatchError("statement Sid must be unique and Effect must be Allow or Deny")
        seen.add(s["sid"])
        item = {
            "Sid": s["sid"],
            "Effect": s["effect"],
            "Action": _strings(s["actions"], "actions"),
            "Resource": _strings(s["resources"], "resources"),
        }
        condition = s.get("condition")
        if condition is not None:
            if (
                not isinstance(condition, dict)
                or set(condition) != {"op", "key", "value"}
                or not all(isinstance(condition[k], str) for k in ("op", "key"))
            ):
                raise PatchError("invalid condition arguments")
            value = condition["value"]
            if not isinstance(value, str):
                value = _strings(value, "condition value")
            item["Condition"] = {condition["op"]: {condition["key"]: value}}
        result.append(item)
    return {"Version": "2012-10-17", "Statement": sorted(result, key=lambda s: s["Sid"])}


def _args(op: PatchOp) -> dict[str, Any]:
    if op.provider != "aws" or op.op not in _FIELDS or set(op.args) != _FIELDS[op.op]:
        raise PatchError("unsupported patch provider, operation or arguments")
    args = dict(op.args)
    for key, value in args.items():
        if key in {"resources", "patterns", "trust_principals"}:
            args[key] = _strings(value, key)
        elif key == "statements":
            _iam(value)
        elif not isinstance(value, str) or not value:
            raise PatchError(f"{key} must be a nonempty string")
    return args


def _memberships(files: dict[str, str], user: str) -> list[tuple[_Block, list[str]]]:
    result = []
    for b in _scan(files):
        if b.kind != "aws_iam_user_group_membership" or posixpath.dirname(b.file) != "terraform":
            continue
        source = files[b.file]
        if _name(_field(b.node, "user", source), source, files) != user:
            continue
        _at(files, b.address)
        groups = _unwrap(_field(b.node, "groups", source))
        if groups.data != "tuple":
            raise PatchError("membership groups must be a literal list")
        result.append((b, [_name(c, source, files) for c in _values(groups)]))
    return result


def _oidc(block: _Block, files: dict[str, str]) -> list[Tree]:
    source = files[block.file]
    _, statements = _statements(_document(block, files, "assume_role_policy"), source)
    found = []
    for statement in statements:
        action = _decode(_field(statement, "Action", source), source)
        if action == "sts:AssumeRoleWithWebIdentity" or (
            isinstance(action, list) and "sts:AssumeRoleWithWebIdentity" in action
        ):
            principal = _decode(_field(statement, "Principal", source), source)
            if not isinstance(principal, dict) or "Federated" not in principal:
                raise PatchError("OIDC trust has no federated principal")
            federated = principal["Federated"]
            identities = federated if isinstance(federated, list) else [federated]
            github = []
            for identity in identities:
                if isinstance(identity, _Ref) and identity.text.endswith(".arn"):
                    provider = _at(files, identity.text.rsplit(".", 1)[0])
                    if provider.kind != "aws_iam_openid_connect_provider":
                        raise PatchError("federated provider reference cannot be verified")
                    url = _decode(_field(provider.node, "url", files[provider.file]), files[provider.file])
                    github.append(url == "https://token.actions.githubusercontent.com")
                elif isinstance(identity, str) and ":oidc-provider/" in identity:
                    github.append(identity.endswith(":oidc-provider/token.actions.githubusercontent.com"))
                else:
                    raise PatchError("federated provider identity cannot be verified")
            if any(github) and not all(github):
                raise PatchError("one trust statement mixes federated issuers")
            if github and all(github):
                found.append(statement)
    if not found:
        raise PatchError("role has no editable OIDC trust statement")
    return found


def _append(files: dict[str, str], kind: str, label: str, attributes: dict[str, Any]) -> str:
    address = f"{kind}.{label}"
    if any(b.address == address and posixpath.dirname(b.file) == "terraform" for b in _scan(files)):
        raise PatchError("generated resource address already exists")
    body = []
    for key, value in sorted(attributes.items()):
        expression = (
            "jsonencode(" + _hcl(value, 2) + ")"
            if key in {"policy", "assume_role_policy"}
            else _hcl(value, 2)
        )
        body.append(f"  {key} = {expression}")
    block = f'resource "{kind}" "{label}" {{\n' + "\n".join(body) + "\n}\n"
    previous = files.get(GENERATED, "")
    files[GENERATED] = previous + ("\n" if previous.endswith("\n") else "\n\n" if previous else "") + block
    added = _at(files, address)
    source = files[added.file]
    for key, expected in attributes.items():
        node = (
            _document(added, files, key)
            if key in {"policy", "assume_role_policy"}
            else _field(added.node, key, source)
        )
        if _decode(node, source) != expected:
            raise PatchError("generated block failed semantic verification")
    return address


def _apply(files: dict[str, str], op: PatchOp, args: dict[str, Any], account: str | None) -> None:
    if op.op in {"remove_membership", "add_membership"}:
        user, group = args["user"], args["group"]
        memberships = [(b, groups) for b, groups in _memberships(files, user) if group in groups]
        if op.op == "remove_membership":
            if not memberships:
                raise PatchError("membership to remove does not exist")
            # Re-find every resource after each edit, because offsets may have moved.
            for old, groups in memberships:
                b = _at(files, old.address)
                remaining = sorted(set(groups) - {group})
                if remaining:
                    _replace(files, b.file, _field(b.node, "groups", files[b.file]), _hcl(remaining))
                else:
                    _erase(files, b.file, b.node.meta.start_pos, b.node.meta.end_pos)
            if any(group in groups for _, groups in _memberships(files, user)):
                raise PatchError("membership removal failed verification")
            return
        if memberships:
            raise PatchError("membership already exists")
        # A new membership names exact declared users/groups, with no inferred identity.
        _principal(files, f"user:{user}", generating=True)
        _principal(files, f"group:{group}", generating=True)
    if op.op in {"remove_statement", "set_statement_resources"}:
        b = _at(files, args["policy_address"])
        container, statement = _statement(b, files, args["sid"])
        if op.op == "remove_statement":
            if container.data == "object":
                _replace(files, b.file, container, "[]")
            else:
                _remove_member(files, b.file, container, statement)
            after = _at(files, args["policy_address"])
            source = files[after.file]
            _, statements = _statements(_document(after, files), source)
            if any(
                "Sid" in _fields(s, source) and _decode(_field(s, "Sid", source), source) == args["sid"]
                for s in statements
            ):
                raise PatchError("statement removal failed verification")
        else:
            _replace(files, b.file, _field(statement, "Resource", files[b.file]), _hcl(args["resources"]))
            after = _at(files, args["policy_address"])
            _, updated = _statement(after, files, args["sid"])
            if (
                _decode(_field(updated, "Resource", files[after.file]), files[after.file])
                != args["resources"]
            ):
                raise PatchError("statement resources failed verification")
        return
    if op.op == "set_oidc_sub":
        b = _principal(files, "role:" + args["role"])
        for index in range(len(_oidc(b, files))):
            b = _principal(files, "role:" + args["role"])
            statement = _oidc(b, files)[index]
            source = files[b.file]
            fields = _fields(statement, source)
            condition = _field(statement, "Condition", source) if "Condition" in fields else None
            value = _decode(condition, source) if condition is not None else {}
            if not isinstance(value, dict) or any(not isinstance(v, dict) for v in value.values()):
                raise PatchError("OIDC conditions cannot be verified")
            occurrences = [key for key, entries in value.items() if SUB in entries]
            if occurrences == ["StringLike"]:
                target = _field(_field(condition, "StringLike", source), SUB, source)
                _replace(files, b.file, target, _hcl(args["patterns"]))
            else:
                for key in occurrences:
                    del value[key][SUB]
                    if not value[key]:
                        del value[key]
                value.setdefault("StringLike", {})[SUB] = args["patterns"]
                if condition is not None:
                    _replace(files, b.file, condition, _hcl(value, 6))
                else:
                    end = statement.meta.end_pos - 1
                    files[b.file] = source[:end] + "\nCondition = " + _hcl(value) + "\n" + source[end:]
        b = _principal(files, "role:" + args["role"])
        for statement in _oidc(b, files):
            source = files[b.file]
            value = _decode(_field(statement, "Condition", source), source)
            if value.get("StringLike", {}).get(SUB) != args["patterns"] or any(
                SUB in entries for key, entries in value.items() if key != "StringLike"
            ):
                raise PatchError("OIDC subject restriction failed verification")
        return
    payload = json.dumps(
        {"provider": op.provider, "op": op.op, "args": args}, sort_keys=True, separators=(",", ":")
    )
    label = "theseus_" + op.op + "_" + hashlib.sha256(payload.encode()).hexdigest()[:12]
    if op.op == "add_membership":
        _append(
            files,
            "aws_iam_user_group_membership",
            label,
            {
                "user": _Ref(_principal(files, "user:" + args["user"], generating=True).address + ".name"),
                "groups": [
                    _Ref(_principal(files, "group:" + args["group"], generating=True).address + ".name")
                ],
            },
        )
    elif op.op == "add_policy":
        principal = _principal(files, args["principal"], generating=True)
        kind = args["principal"].partition(":")[0]
        _append(
            files,
            f"aws_iam_{kind}_policy",
            label,
            {"name": label, kind: _Ref(principal.address + ".name"), "policy": _iam(args["statements"])},
        )
    elif op.op == "add_role":
        if any(
            b.kind == "aws_iam_role"
            and _decode(_field(b.node, "name", files[b.file]), files[b.file]) == args["name"]
            for b in _scan(files)
        ):
            raise PatchError("role name already exists")
        trusted = []
        dependencies = []
        for principal in args["trust_principals"]:
            if not principal.startswith(("user:", "role:")):
                raise PatchError("role trust accepts only user or role IDs")
            arn, dependency = _trust_principal(files, principal, account)
            trusted.append(arn)
            dependencies.append(dependency)
        if not trusted:
            raise PatchError("role must trust at least one declared principal")
        trust = {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": "sts:AssumeRole", "Principal": {"AWS": trusted}}],
        }
        address = _append(
            files,
            "aws_iam_role",
            label,
            {"name": args["name"], "assume_role_policy": trust, "depends_on": dependencies},
        )
        _append(
            files,
            "aws_iam_role_policy",
            label + "_access",
            {"name": label + "_access", "role": _Ref(address + ".name"), "policy": _iam(args["statements"])},
        )


def render(files: dict[str, str], ops: list[PatchOp], *, account: str | None = None) -> dict[str, str]:
    """An independent source map with verified edits; PatchError if any op cannot be rendered safely."""
    result = dict(sorted(files.items()))
    _scan(result)
    for op in ops:
        args = _args(op)
        _apply(result, op, args, account)
        _scan(result)
    return dict(sorted(result.items()))
