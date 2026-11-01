"""PII Redaction.

Reversible tokenisation: PII in text is replaced by placeholders such as
<ACCOUNT_1> before it leaves the trust boundary (LLM prompts, logs,
third-party model). A per-request ``PIIVault`` keeps the mapping so tool
arguments produced by the LLM can be de-tokenised before hitting the MCP
servers, and final answers can be restored for the authenticated customer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Order matters: more specific patterns first.
PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("AADHAAR", re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # bank account numbers are 12 digits - must be matched before generic phone numbers
    ("ACCOUNT", re.compile(r"\b\d{12}\b")),
    ("PHONE", re.compile(r"(?<!\w)(?:\+?\d{1,3}[ -]?)?(?:\(?\d{3,5}\)?[ -]?)\d{3}[ -]?\d{3,4}(?!\w)")),
    ("POSTCODE_UK", re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")),
]

_PLACEHOLDER = re.compile(r"<([A-Z_]+)_(\d+)>")


@dataclass
class PIIVault:
    forward: dict[str, str] = field(default_factory=dict)  # value -> token
    reverse: dict[str, str] = field(default_factory=dict)  # token -> value
    counters: dict[str, int] = field(default_factory=dict)

    def tokenise(self, kind: str, value: str) -> str:
        if value in self.forward:
            return self.forward[value]
        self.counters[kind] = self.counters.get(kind, 0) + 1
        token = f"<{kind}_{self.counters[kind]}>"
        self.forward[value] = token
        self.reverse[token] = value
        return token

    def redact(self, text: str) -> str:
        if not text:
            return text
        for kind, pattern in PII_PATTERNS:
            text = pattern.sub(lambda m, k=kind: self._sub(k, m), text)
        return text

    def _sub(self, kind: str, m: re.Match) -> str:
        val = m.group(0)
        # don't re-tokenise existing placeholders / short noise
        if val.startswith("<"):
            return val
        return self.tokenise(kind, val)

    def restore(self, text: str) -> str:
        if not text:
            return text
        return _PLACEHOLDER.sub(lambda m: self.reverse.get(m.group(0), m.group(0)), text)

    def restore_obj(self, obj):
        if isinstance(obj, str):
            return self.restore(obj)
        if isinstance(obj, dict):
            return {k: self.restore_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.restore_obj(v) for v in obj]
        return obj

    def redact_obj(self, obj):
        if isinstance(obj, str):
            return self.redact(obj)
        if isinstance(obj, dict):
            return {k: self.redact_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.redact_obj(v) for v in obj]
        return obj


def contains_pii(text: str) -> bool:
    return any(p.search(text or "") for _, p in PII_PATTERNS)


def mask_for_logs(text: str) -> str:
    """One-way masking for logs/traces (no vault kept)."""
    return PIIVault().redact(text)
