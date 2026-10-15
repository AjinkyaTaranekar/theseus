"""Hygiene for untrusted text before a model reads it (06-agent.md, "Untrusted text"): normalize it, reveal
what a reviewer cannot see, mask secrets, and flag text that tries to steer the review.

The screen is deterministic and only adds suspicion: the model's own `suspicious` answer still counts, and a
flag never removes anything the model would otherwise read.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import unicodedata

log = logging.getLogger(__name__)

# Unicode tag characters carry ASCII that GitHub never renders. A subdivision flag emoji (U+1F3F4, then tag
# characters ending in U+E007F) is their one legitimate use.
_TAGS = re.compile("[\U000e0000-\U000e007f]+")
_FLAG = "\U0001f3f4"
_CANCEL_TAG = "\U000e007f"
_BIDI = re.compile("[\U0000202a-\U0000202e\U00002066-\U00002069]")
# Zero-width space, word joiner, byte order mark, soft hyphen. The joiners U+200C and U+200D stay in the text,
# since emoji and some scripts need them, and leave only the screening copy.
_INVISIBLE = re.compile("[\U0000200b\U00002060\U0000feff\U000000ad]")
_JOINERS = re.compile("[\U0000200c\U0000200d]")

# Cyrillic and Greek letters that look like Latin ones, folded only in the screening copy.
_CYRILLIC = {0x430: "a", 0x435: "e", 0x43E: "o", 0x440: "p", 0x441: "c", 0x443: "y", 0x445: "x", 0x456: "i"}
_CYRILLIC |= {0x458: "j", 0x455: "s", 0x501: "d", 0x4CF: "l", 0x4BB: "h", 0x51B: "q", 0x51D: "w"}
_GREEK = {0x3B1: "a", 0x3BF: "o", 0x3B5: "e", 0x3B9: "i", 0x3BA: "k", 0x3BD: "v", 0x3C1: "p", 0x3C4: "t"}
_GREEK |= {0x3C5: "u", 0x3C7: "x"}
_CONFUSABLES = str.maketrans(_CYRILLIC | _GREEK)

_FLAGS: list[tuple[str, re.Pattern[str]]] = [
    (
        "asks to ignore instructions",
        re.compile(
            r"\b(ignore|disregard|forget)\s+(all\s+|any\s+)?(of\s+)?(the\s+|your\s+|my\s+|these\s+|those\s+)?"
            r"(previous|prior|above|earlier|preceding|system|original)\s+(instructions|prompts?|rules|guidelines)"
            r"|\b(ignore|disregard|forget)\s+(all\s+)?your\s+(instructions|prompts?|rules|guidelines)\b"
        ),
    ),
    (
        "fake role or fence tag",
        re.compile(
            r"<\s*/?\s*(system|assistant|developer|instructions?|tool|untrusted_[a-z_]*)\s*>"
            r"|<\|im_(start|end)\|>|\[/?inst\]"
        ),
    ),
    (
        "fake system message",
        re.compile(r"(^|\n)[\s#>*]*(system|developer)\s+(prompt|message|instructions?)\s*:"),
    ),
    (
        "speaks to the tool",
        re.compile(
            r"(^|\n)[\s#>*]*(ai|llm|assistant|theseus|automated\s+reviewer)\s*:"
            r"|\b(note|message|instructions?)\s+(to|for)\s+(the\s+)?"
            r"(ai|llm|model|assistant|bot|tool|theseus|automated\s+(reviewer|review|tool|scanner))\b"
        ),
    ),
    (
        "claims the rules changed",
        re.compile(
            r"\b(vocabulary|allowlist|your\s+rules|your\s+instructions|output\s+format)\s+"
            r"(has|have|was|were|is|are)\s+(been\s+)?(changed|updated|extended|replaced|expanded)\b"
        ),
    ),
    (
        "role-play",
        re.compile(
            r"\b(pretend\s+(to\s+be|you\s+are)|role[\s-]?play|let'?s\s+play\s+a\s+game|you\s+are\s+now\s+an?)\b"
        ),
    ),
    (
        "claims security approval",
        re.compile(r"\b(pre[\s-]?)?approved\s+by\s+(the\s+)?(security|secops|ciso|admin)"),
    ),
]
_BASE64 = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")

# Each pattern with a group keeps that group (the `=` or `:` after a key name) and masks the rest.
_SECRETS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    ),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "AWS secret key",
        re.compile(r"(?i)(?<=aws_secret_access_key)(\s*[:=]\s*)[\"']?[A-Za-z0-9/+=]{40}[\"']?"),
    ),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("password", re.compile(r"(?i)(?<=\bpassword)(\s*[:=]\s*)[\"']?[^\s\"']{6,}[\"']?")),
]


def normalize(text: str) -> tuple[str, list[str], list[str]]:
    """(text, revealed, flags): the text in NFKC form without invisible characters; the ASCII smuggled in tag
    characters, decoded; and a flag for each kind of invisible trick found."""
    flags: list[str] = []
    revealed: list[str] = []

    def reveal(m: re.Match[str]) -> str:
        run = m.group(0)
        if m.start() > 0 and text[m.start() - 1] == _FLAG and run.endswith(_CANCEL_TAG) and len(run) <= 7:
            return run
        decoded = "".join(chr(ord(c) - 0xE0000) for c in run if 0x20 <= ord(c) - 0xE0000 < 0x7F).strip()
        if decoded:
            revealed.append(decoded)
        return ""

    out = _TAGS.sub(reveal, text)
    if revealed:
        flags.append("text in invisible tag characters")
    if _BIDI.search(out):
        flags.append("bidirectional control characters")
        out = _BIDI.sub("", out)
    out = _INVISIBLE.sub("", unicodedata.normalize("NFKC", out))
    return out, revealed, flags


def mask_secrets(text: str) -> tuple[str, list[str]]:
    """(text, kinds): secret-shaped strings replaced by `[masked <kind>]`, and the kind of each one masked."""
    kinds: list[str] = []
    for kind, pattern in _SECRETS:

        def mask(m: re.Match[str], kind: str = kind) -> str:
            kinds.append(kind)
            return f"{m.group(1) if m.re.groups else ''}[masked {kind}]"

        text = pattern.sub(mask, text)
    return text, kinds


def _fold(text: str) -> str:
    return _INVISIBLE.sub("", _JOINERS.sub("", text)).casefold().translate(_CONFUSABLES)


def _decoded(text: str) -> list[str]:
    """Readable text hidden in base64 runs."""
    out: list[str] = []
    for m in _BASE64.finditer(text):
        run = m.group(0)
        try:
            raw = base64.b64decode(run + "=" * (-len(run) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            continue
        if raw and sum(c.isprintable() or c.isspace() for c in raw) / len(raw) >= 0.9:
            out.append(raw)
    return out


def injection_flags(text: str) -> list[str]:
    """Why the text looks like an attempt to steer the review, sorted; empty for ordinary PR text.

    Matches the text with look-alike letters folded, and any readable base64 inside it.
    """
    found: set[str] = set()
    for source, label in [(text, ""), *((d, "encoded: ") for d in _decoded(text))]:
        folded = _fold(source)
        found.update(label + name for name, pattern in _FLAGS if pattern.search(folded))
    return sorted(found)
