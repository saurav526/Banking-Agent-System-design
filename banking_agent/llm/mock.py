"""Deterministic offline LLM.

Speaks the exact same tool-calling protocol as a real model so the whole
agentic pipeline (routing -> agent -> MCP tool -> answer) runs without any
API key. It is also handy as a last-resort fallback and for CI evals.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, timedelta

from ..cost.tracker import count_tokens
from .base import LLMResponse, ToolCall

# Keyword rules per tool name (coordinator routes + MCP tools).
RULES: dict[str, list[str]] = {
    "route_to_accounts_agent": [r"\bbalance", r"how much (money|do i have)", r"\bfunds\b", r"\baccounts\b",
                                r"available"],
    "route_to_transaction_agent": [r"transaction", r"\bspent\b", r"spending", r"statement", r"payments?\b",
                                   r"\bhistory\b", r"\btxn", r"debits?|credits?"],
    "route_to_service_agent": [r"address", r"\bmoved?\b", r"cheque ?book", r"\bkyc\b", r"\bpan\b", r"aadhaar",
                               r"passport", r"<PAN_\d+>", r"<AADHAAR_\d+>"],
    "list_accounts": [r"(list|show|which|what).{0,15}accounts", r"my accounts\b"],
    "balance_enquiry": [r"balance", r"how much", r"funds", r"available"],
    "transaction_details": [r"transaction", r"spent", r"spending", r"payments?", r"history", r"txn", r"recent"],
    "statement_request": [r"statement"],
    "change_of_address": [r"address", r"\bmoved?\b"],
    "chequebook_request": [r"cheque ?book", r"\bcheques?\b"],
    "kyc_status": [r"kyc.{0,20}status", r"status.{0,20}kyc"],
    "kyc_update": [r"\bkyc\b", r"\bpan\b", r"aadhaar", r"passport", r"<PAN_\d+>", r"<AADHAAR_\d+>"],
}

GREETING = re.compile(r"^\s*(hi|hello|hey|good (morning|afternoon|evening)|namaste)\b", re.I)


def _last(messages: list[dict], role: str) -> str:
    for m in reversed(messages):
        if m["role"] == role and m.get("content"):
            return m["content"]
    return ""


def _account_aliases(system: str) -> dict[str, str]:
    # system prompt contains lines like "- SAVINGS: <ACCOUNT_1>"
    return {t.lower(): tok for t, tok in re.findall(r"-\s*(\w+):\s*(<ACCOUNT_\d+>)", system)}


class MockProvider:
    name = "mock"
    model = "mock"

    def configured(self) -> bool:
        return True

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        prompt_text = json.dumps(messages)
        resp = self._decide(messages, tools or [])
        out_text = (resp.content or "") + json.dumps([c.arguments for c in resp.tool_calls])
        resp.input_tokens, resp.output_tokens = count_tokens(prompt_text), count_tokens(out_text)
        resp.model, resp.provider = self.model, self.name
        return resp

    # ------------------------------------------------------------------
    def _decide(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        last = messages[-1]
        # After tool results -> produce final answer.
        if last["role"] == "tool":
            return LLMResponse(content=self._summarise(messages))

        user = _last(messages, "user")
        system = _last(messages, "system")
        names = [t["function"]["name"] for t in tools]
        low = user.lower()

        matched = [n for n in names if any(re.search(p, low if not p.startswith("<") else user) for p in RULES.get(n, []))]
        # list_accounts and balance_enquiry overlap - prefer the most specific
        if "balance_enquiry" in matched and "list_accounts" in matched:
            matched.remove("list_accounts" if re.search(r"balance|how much", low) else "balance_enquiry")
        if "statement_request" in matched and "transaction_details" in matched:
            matched.remove("transaction_details")
        if "kyc_status" in matched and "kyc_update" in matched:
            matched.remove("kyc_update")
        if not matched:
            if GREETING.search(user):
                return LLMResponse(content="Hello! I'm your banking assistant. I can help with balances, "
                                           "transactions, statements, address changes, chequebooks and KYC.")
            return LLMResponse(content="I'm sorry, I can only help with banking requests such as balances, "
                                       "transactions, statements, address changes, chequebooks and KYC updates.")

        if names and names[0].startswith("route_to_"):
            return LLMResponse(None, [ToolCall(f"call_{uuid.uuid4().hex[:8]}", n, {"task": user}) for n in matched])

        tool = matched[0]
        return LLMResponse(None, [ToolCall(f"call_{uuid.uuid4().hex[:8]}", tool, self._args(tool, user, system))])

    def _args(self, tool: str, user: str, system: str) -> dict:
        low = user.lower()
        args: dict = {}
        acc = re.search(r"<ACCOUNT_\d+>", user)
        if acc:
            args["account_id"] = acc.group(0)
        else:
            for alias, tok in _account_aliases(system).items():
                if alias in low:
                    args["account_id"] = tok
            if "account_id" not in args and re.search(r"(same|that) account", low):
                m = re.search(r"Last referenced account:\s*(<ACCOUNT_\d+>)", system)
                if m:
                    args["account_id"] = m.group(1)

        if tool in ("list_accounts", "kyc_status"):
            return {}
        if tool == "transaction_details":
            if m := re.search(r"\b(?:last|recent|past)\s+(\d{1,2})\b", low):
                args["limit"] = int(m.group(1))
            if m := re.search(r"\bTXN\w+", user, re.I):
                args["transaction_id"] = m.group(0).upper()
        elif tool == "statement_request":
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", user)
            today = date.today()
            if len(dates) >= 2:
                args["from_date"], args["to_date"] = dates[0], dates[1]
            elif m := re.search(r"last\s+(\d+)\s+days", low):
                args["from_date"], args["to_date"] = (today - timedelta(days=int(m.group(1)))).isoformat(), today.isoformat()
            elif "last month" in low:
                first = today.replace(day=1)
                prev_end = first - timedelta(days=1)
                args["from_date"], args["to_date"] = prev_end.replace(day=1).isoformat(), prev_end.isoformat()
            else:
                args["from_date"], args["to_date"] = (today - timedelta(days=90)).isoformat(), today.isoformat()
            for d in ("email", "post", "download"):
                if d in low:
                    args["delivery"] = d
        elif tool == "change_of_address":
            args.pop("account_id", None)
            m = re.search(r"(?:address (?:is|to)|moved to|change (?:my )?address to|new address[:\s]+|to)\s+(.+)$",
                          user, re.I)
            args["new_address"] = (m.group(1) if m else user).strip().rstrip(".")
        elif tool == "chequebook_request":
            if m := re.search(r"\b(25|50|100)\b", user):
                args["leaves"] = int(m.group(1))
        elif tool == "kyc_update":
            args.pop("account_id", None)
            if m := re.search(r"<PAN_\d+>", user):
                args.update(document_type="PAN", document_number=m.group(0))
            elif m := re.search(r"<AADHAAR_\d+>", user):
                args.update(document_type="AADHAAR", document_number=m.group(0))
            elif m := re.search(r"\b([A-Z]\d{7})\b", user):
                args.update(document_type="PASSPORT", document_number=m.group(1))
            elif "aadhaar" in low:
                args["document_type"] = "AADHAAR"
            elif "passport" in low:
                args["document_type"] = "PASSPORT"
            else:
                args["document_type"] = "PAN"
        return args

    # ------------------------------------------------------------------
    def _summarise(self, messages: list[dict]) -> str:
        # collect trailing tool messages
        outs = []
        for m in reversed(messages):
            if m["role"] != "tool":
                break
            outs.append(m)
        outs.reverse()
        id_to_name = {tc["id"]: tc["function"]["name"]
                      for msg in messages if msg["role"] == "assistant" for tc in msg.get("tool_calls") or []}
        parts = []
        for m in outs:
            name = id_to_name.get(m.get("tool_call_id"), "")
            try:
                data = json.loads(m["content"])
            except (json.JSONDecodeError, TypeError):
                parts.append(str(m["content"]))
                continue
            parts.append(_format(name, data))
        return "\n\n".join(parts)


def _money(v: float, cur: str = "INR") -> str:
    return f"{cur} {v:,.2f}"


def _format(name: str, d: dict) -> str:
    if d.get("error"):
        return f"Sorry, I couldn't complete that: {d['error']}"
    if name.startswith("route_to_"):  # coordinator synthesis
        return d.get("answer", "")
    if name == "list_accounts":
        rows = [f"- {a['type']} account {a['masked']} ({a['status']})" for a in d["accounts"]]
        return "Here are your accounts:\n" + "\n".join(rows)
    if name == "balance_enquiry":
        return (f"Your {d['type']} account {d['account']} has an available balance of "
                f"{_money(d['available_balance'], d['currency'])} (ledger balance "
                f"{_money(d['ledger_balance'], d['currency'])}).")
    if name == "transaction_details":
        rows = [f"- {t['date'][:10]}  {t['description']:<20} {t['amount']:>12,.2f}  [{t['id']}]" for t in d["transactions"]]
        return f"Recent transactions on account {d['account']}:\n" + "\n".join(rows)
    if name == "statement_request":
        return (f"Your statement for account {d['account']} ({d['period']}, {d['transactions_included']} "
                f"transactions) has been requested via {d['delivery']}. Reference: {d['reference']}.")
    if name == "change_of_address":
        return f"Your address has been updated to: {d['new_address']}. Reference: {d['reference']}."
    if name == "chequebook_request":
        return (f"A {d['leaves']}-leaf chequebook for account {d['account']} has been ordered and should arrive "
                f"in about {d['eta_days']} days. Reference: {d['reference']}.")
    if name == "kyc_status":
        return f"Your KYC status is {d['kyc_status']} (last updated {d['last_updated']})."
    if name == "kyc_update":
        return (f"Your {d['document_type']} ({d['document']}) has been submitted for KYC re-verification. "
                f"Status: {d['status']}. Reference: {d['reference']}.")
    return json.dumps(d)
