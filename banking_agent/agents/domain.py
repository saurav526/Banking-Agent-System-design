"""Accounts, Transaction and Service agents (one per MCP server)."""
"""
Domain Agents Module
====================

Defines specialized downstream domain agents and a centralized factory function
for interacting with Model Context Protocol (MCP) servers across banking verticals.

Agent Implementations:
----------------------
1. AccountsAgent:
   - Scope: Account identification and balance enquiries.
   - MCP Integration: Connects to the accounts MCP server endpoint.

2. TransactionAgent:
   - Scope: Transaction records, spending history lookups, and account statement requests.
   - Constraints: Enforces YYYY-MM-DD date formatting with a 90-day default window.
   - MCP Integration: Connects to the transactions MCP server endpoint.

3. ServiceAgent:
   - Scope: Operational banking service requests (address updates, chequebook issuance,
     and KYC lifecycle/status verification).
   - MCP Integration: Connects to the service MCP server endpoint.

Factory:
--------
- build_agents(): Instantiates each DomainAgent subclass wired to its respective
  in-memory server instance and external MCP URL defined in system settings.
"""
from __future__ import annotations

from ..config import settings
from ..mcp import accounts_server, service_server, transactions_server
from ..mcp.client import MCPClient
from .base import DomainAgent


class AccountsAgent(DomainAgent):
    name = "accounts"
    description = "Account information: list accounts and balance enquiries."
    instructions = "You answer questions about the customer's accounts and balances."


class TransactionAgent(DomainAgent):
    name = "transactions"
    description = "Transaction details, spending history and statement requests."
    instructions = ("You look up transactions and raise statement requests. Dates must be YYYY-MM-DD; "
                    "default statement period is the last 90 days.")


class ServiceAgent(DomainAgent):
    name = "service"
    description = "Servicing requests: change of address, chequebook request, KYC update/status."
    instructions = "You handle servicing requests: change of address, chequebook orders and KYC updates."


def build_agents() -> dict[str, DomainAgent]:
    return {
        "accounts": AccountsAgent(MCPClient(accounts_server.server, settings.accounts_mcp_url)),
        "transactions": TransactionAgent(MCPClient(transactions_server.server, settings.transactions_mcp_url)),
        "service": ServiceAgent(MCPClient(service_server.server, settings.service_mcp_url)),
    }
