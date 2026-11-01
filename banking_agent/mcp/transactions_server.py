"""Transactions MCP Server -> Transaction Details, Statement Request."""
from __future__ import annotations

import json

from .accounts_server import _resolve_account
from .core_banking import core
from .protocol import MCPServer, ToolError

server = MCPServer("transactions-mcp")


@server.tool(
    "Transaction details: recent transactions for an account, or a single transaction by id.",
    {"properties": {
        "account_id": {"type": "string", "maxLength": 20},
        "limit": {"type": "integer", "description": "1-20, default 5"},
        "transaction_id": {"type": "string", "maxLength": 20},
    }},
)
def transaction_details(customer_id: str, account_id: str | None = None, limit: int = 5,
                        transaction_id: str | None = None) -> dict:
    a = _resolve_account(customer_id, account_id)
    limit = max(1, min(int(limit), 20))
    txns = core.transactions(a["account_id"], limit=limit, txn_id=transaction_id)
    if transaction_id and not txns:
        raise ToolError("Transaction not found on this account")
    return {"account": "XXXX" + a["account_id"][-4:], "transactions": [
        {"id": t["txn_id"], "date": t["ts"], "description": t["description"], "amount": t["amount"],
         "category": t["category"], "balance_after": t["balance_after"]} for t in txns]}


@server.tool(
    "Statement request: generate and dispatch an account statement for a date range.",
    {"properties": {
        "account_id": {"type": "string", "maxLength": 20},
        "from_date": {"type": "string", "description": "YYYY-MM-DD"},
        "to_date": {"type": "string", "description": "YYYY-MM-DD"},
        "delivery": {"type": "string", "enum": ["email", "post", "download"]},
        "idempotency_key": {"type": "string"},
    }, "required": ["from_date", "to_date"]},
    is_write=True,
)
def statement_request(customer_id: str, from_date: str, to_date: str, account_id: str | None = None,
                      delivery: str = "email", idempotency_key: str | None = None) -> dict:
    if from_date > to_date:
        raise ToolError("from_date must be before to_date")
    a = _resolve_account(customer_id, account_id)
    n = len(core.transactions(a["account_id"], limit=1000, from_date=from_date, to_date=to_date))
    sr = core.create_request(customer_id, "STATEMENT", json.dumps(
        {"account_id": a["account_id"], "from": from_date, "to": to_date, "delivery": delivery}), idempotency_key)
    return {"reference": sr["reference"], "status": sr["status"], "account": "XXXX" + a["account_id"][-4:],
            "period": f"{from_date} to {to_date}", "transactions_included": n, "delivery": delivery}
