"""
Web Application Firewall (WAF) & Threat Inspection Module
=========================================================

Provides signature-based pattern matching and heuristic threat detection to
protect edge services against common OWASP top web vulnerabilities and LLM-targeted
prompt injection attacks.

Core Threat Signatures & Detection Categories:
---------------------------------------------
1. OWASP Web Vulnerabilities (`WAF_RULES`):
   - SQL Injection (`sqli`): Matches UNION SELECT patterns, classic tautologies
     (e.g., OR '1'='1'), schema dropping statements, and SQL commenting styles.
   - Cross-Site Scripting (`xss`): Identifies script tags, javascript: pseudo-protocols,
     inline event handlers (onerror, onload, onclick), and iframe injections.
   - Path Traversal (`path_traversal`): Catches directory climbing attempts via
     standard (../, ..\) and URL-encoded (%2e%2e%2f) sequences.
   - Command Injection (`cmd_injection`): Detects command substitutions ($(...), backticks),
     piped shell executions, and basic binary invocations (cat, ls, curl, wget, bash, sh).

2. LLM Prompt Injection & Jailbreaking (`PROMPT_INJECTION`):
   - Instruction Overrides: Catches phrases instructing the model to ignore, disregard,
     or bypass prior/system prompts.
   - Persona Hijacking & Jailbreaks: Detects DAN-style jailbreaks, developer mode switches,
     and administrative persona prompts ("act as admin", "pretend you are").
   - System Leakage: Prevents queries attempting to reveal or dump internal system prompts.
   - Tenant Data Isolation: Identifies social engineering attempts aiming to access other
     customers' accounts or data.

Key Inspection Functions:
-------------------------
- detect_prompt_injection(text): Evaluates whether a given string triggers prompt-injection
  patterns, returning a boolean.
- inspect(text): Decodes URL-encoded payloads (`unquote_plus`) and sequentially evaluates
  them against OWASP rules and prompt-injection heuristics. Returns the matching threat rule
  identifier (e.g., "sqli", "prompt_injection") or `None` if the payload is clean.
"""

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
