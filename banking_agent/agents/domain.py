from __future__ import annotations
from typing import Any
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
