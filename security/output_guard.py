import re

PAN = re.compile(r"\b(?:\d[ -]?){13,19}\b")
CVV = re.compile(r"\bcvv\s*[:=]?\s*\d{3,4}\b", re.IGNORECASE)

def guard_output(text: str, allowed_account_suffixes: set[str]) -> str:
    text = CVV.sub("[REDACTED]", text)
    def mask(m):
        digits = re.sub(r"\D", "", m.group())
        return f"****{digits[-4:]}"
    text = PAN.sub(mask, text)
    # Block responses that mention account suffixes the user doesn't own
    for suffix in set(re.findall(r"\*{4}(\d{4})", text)):
        if suffix not in allowed_account_suffixes:
            return "I can't share that information."
    return text
