"""Accounts MCP Server -> Balance Enquiry."""
from __future__ import annotations

from .core_banking import core
from .protocol import MCPServer, ToolError

server = MCPServer("accounts-mcp")


def _resolve_account(customer_id: str, account_id: str | None) -> dict:
    accounts = core.accounts_for(customer_id)
    if not accounts:
        raise ToolError("No accounts found for customer")
    if not account_id:
        return accounts[0]
    acc = next((a for a in accounts if a["account_id"] == account_id), None)
    if acc is None:
        raise ToolError("Account not found or not owned by customer")
    return acc


@server.tool("List the customer's accounts (masked numbers, type, status).", {"properties": {}})
def list_accounts(customer_id: str) -> dict:
    return {"accounts": [
        {"account_id": a["account_id"], "masked": "XXXX" + a["account_id"][-4:], "type": a["type"],
         "currency": a["currency"], "status": a["status"]}
        for a in core.accounts_for(customer_id)
    ]}


@server.tool(
    "Balance enquiry: current ledger and available balance for one account (defaults to primary account).",
    {"properties": {"account_id": {"type": "string", "description": "12-digit account number", "maxLength": 20}}},
)
def balance_enquiry(customer_id: str, account_id: str | None = None) -> dict:
    a = _resolve_account(customer_id, account_id)
    return {"account": "XXXX" + a["account_id"][-4:], "type": a["type"], "currency": a["currency"],
            "ledger_balance": a["balance"], "available_balance": a["available"]}
