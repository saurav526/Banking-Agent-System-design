"""
Transactions MCP Server Module
==============================

Exposes an in-process Model Context Protocol (MCP) tool server providing
transaction history lookups and formal account statement generation over the core
banking system.

Key Tools & Capabilities:
-------------------------
1. Transaction Details (`transaction_details`):
   - Retrieves chronological recent ledger entries for an account or looks up a
     specific transaction by its identifier (`transaction_id`).
   - Automatically clamps result sets between 1 and 20 entries (defaulting to 5).
   - Validates transaction existence, raising `ToolError` if a targeted record is missing.
   - Enforces data loss prevention (DLP) by returning masked account numbers (`XXXX1234`)
     alongside structured transaction fields (timestamp, description, amount, category, balance_after).

2. Statement Request (`statement_request`):
   - Generates and dispatches formal account statements across specified date ranges
     (`from_date` to `to_date`).
   - Validates chronological boundaries, raising `ToolError` if `from_date > to_date`.
   - Counts matching ledger transactions within the designated window (up to 1,000 records).
   - Dispatches a mutating asynchronous service request (`STATEMENT`) through `core.create_request`
     with idempotency guarantees (`idempotency_key`) and configurable delivery channels
     (`email`, `post`, `download`).
   - Returns a structured confirmation envelope containing the tracking reference, status,
     period, delivery mode, and total transaction count.
"""
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
