"""Web Application Firewall rules (OWASP-style signatures + LLM prompt-injection)."""
from __future__ import annotations

import re
from urllib.parse import unquote_plus

WAF_RULES: list[tuple[str, re.Pattern]] = [
    ("sqli", re.compile(r"(\bunion\b.+\bselect\b|\bor\b\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+|;\s*drop\s+table|--\s*$|/\*.*\*/)", re.I)),
    ("xss", re.compile(r"(<\s*script|javascript:|on(error|load|click)\s*=|<\s*iframe)", re.I)),
    ("path_traversal", re.compile(r"(\.\./|\.\.\\|%2e%2e%2f)", re.I)),
    ("cmd_injection", re.compile(r"(\$\(|`[^`]+`|\|\s*(cat|ls|curl|wget|bash|sh)\b)", re.I)),
]

PROMPT_INJECTION = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|prompts?)|disregard (the )?(system|previous)|"
    r"you are now|act as (an? )?(admin|developer|dan)|reveal (your|the) (system )?prompt|system prompt|"
    r"jailbreak|developer mode|pretend (to be|you are)|bypass (security|authori[sz]ation)|"
    r"another customer'?s|other customers?'? (account|data))",
    re.I,
)


def detect_prompt_injection(text: str) -> bool:
    return bool(PROMPT_INJECTION.search(text or ""))


def inspect(text: str) -> str | None:
    """Return the rule name that matched, or None if clean."""
    if not text:
        return None
    decoded = unquote_plus(text)
    for name, rule in WAF_RULES:
        if rule.search(decoded):
            return name
    if detect_prompt_injection(decoded):
        return "prompt_injection"
    return None
