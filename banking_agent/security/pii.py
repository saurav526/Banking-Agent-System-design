"""
PII Redaction & Reversible Tokenisation Module
==============================================

Provides regex-based detection, masking, and bidirectional tokenisation of
Personally Identifiable Information (PII) before data leaves trust boundaries
(e.g., passing prompts to LLMs, logging to traces, or calling third-party APIs).

Core Pattern Recognizers (`PII_PATTERNS`):
------------------------------------------
Detects sensitive banking and identity tokens using ordered regular expressions:
  - Electronic Mail (`EMAIL`)
  - Payment Cards (`CARD`: 13–16 digit credit/debit PANs)
  - International Bank Account Numbers (`IBAN`)
  - National Identity Numbers (`AADHAAR`, `PAN`, `SSN`)
  - Bank Account Numbers (`ACCOUNT`: exactly 12 digits, prioritized before phone numbers)
  - Telephone Numbers (`PHONE`)
  - Postal Codes (`POSTCODE_UK`)

Key Components & Vault Mechanics:
---------------------------------
1. PIIVault (Bidirectional Token Store):
   - `tokenise(kind, value)`: Maps raw sensitive strings to synthetic placeholders
     (e.g., `<ACCOUNT_1>`, `<PAN_1>`) while maintaining forward (`value -> token`)
     and reverse (`token -> value`) lookup tables.
   - `redact(text)`: Replaces recognized PII in free-form text with token placeholders,
     avoiding re-tokenising already masked strings.
   - `restore(text)`: Rehydrates token placeholders back to original plaintext values
     using the reverse mapping table.
   - `redact_obj(obj)` / `restore_obj(obj)`: Recursively traverses nested structures
     (strings, dictionaries, lists) to apply redaction or rehydration to structured payloads.

2. Static & Logging Utilities:
   - `contains_pii(text)`: Lightweight boolean check to determine if any sensitive
     pattern matches the provided text.
   - `mask_for_logs(text)`: Performs one-way redaction using an ephemeral, discarded
     vault for sanitizing traces and console outputs without storing reverse maps.
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
