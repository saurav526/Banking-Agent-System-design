"""Service MCP Server -> Change of Address, Chequebook Request, KYC Update."""
from __future__ import annotations

import json
import re
from datetime import date

from .accounts_server import _resolve_account
from .core_banking import core
from .protocol import MCPServer, ToolError

server = MCPServer("service-mcp")


@server.tool(
    "Change of address: update the customer's registered correspondence address.",
    {"properties": {"new_address": {"type": "string", "maxLength": 300},
                    "idempotency_key": {"type": "string"}}, "required": ["new_address"]},
    is_write=True,
)
def change_of_address(customer_id: str, new_address: str, idempotency_key: str | None = None) -> dict:
    if len(new_address.strip()) < 10:
        raise ToolError("Address looks incomplete - please include street, city and postcode")
    old = core.customer(customer_id)["address"]
    sr = core.create_request(customer_id, "CHANGE_OF_ADDRESS", json.dumps({"old": old, "new": new_address}),
                             idempotency_key)
    if not sr.get("duplicate"):
        core.update_customer(customer_id, address=new_address)
    return {"reference": sr["reference"], "status": "COMPLETED", "new_address": new_address}


@server.tool(
    "Chequebook request: order a new chequebook for an account.",
    {"properties": {"account_id": {"type": "string", "maxLength": 20},
                    "leaves": {"type": "integer", "description": "25, 50 or 100"},
                    "idempotency_key": {"type": "string"}}},
    is_write=True,
)
def chequebook_request(customer_id: str, account_id: str | None = None, leaves: int = 25,
                       idempotency_key: str | None = None) -> dict:
    if leaves not in (25, 50, 100):
        raise ToolError("leaves must be 25, 50 or 100")
    a = _resolve_account(customer_id, account_id)
    if a["type"] not in ("CURRENT", "SAVINGS"):
        raise ToolError("Chequebooks are not available for this account type")
    sr = core.create_request(customer_id, "CHEQUEBOOK", json.dumps({"account_id": a["account_id"], "leaves": leaves}),
                             idempotency_key)
    return {"reference": sr["reference"], "status": sr["status"], "account": "XXXX" + a["account_id"][-4:],
            "leaves": leaves, "eta_days": 7}


_DOC_RULES = {"PAN": r"^[A-Z]{5}\d{4}[A-Z]$", "AADHAAR": r"^\d{4}\s?\d{4}\s?\d{4}$", "PASSPORT": r"^[A-Z]\d{7}$"}


@server.tool("KYC status: check the customer's current KYC verification status.", {"properties": {}})
def kyc_status(customer_id: str) -> dict:
    c = core.customer(customer_id)
    return {"kyc_status": c["kyc_status"], "last_updated": c["kyc_updated"]}


@server.tool(
    "KYC update: submit a KYC document (PAN, AADHAAR, PASSPORT) for re-verification.",
    {"properties": {"document_type": {"type": "string", "enum": ["PAN", "AADHAAR", "PASSPORT"]},
                    "document_number": {"type": "string", "maxLength": 20},
                    "idempotency_key": {"type": "string"}}, "required": ["document_type", "document_number"]},
    is_write=True,
)
def kyc_update(customer_id: str, document_type: str, document_number: str,
               idempotency_key: str | None = None) -> dict:
    if not re.match(_DOC_RULES[document_type], document_number.upper()):
        raise ToolError(f"Invalid {document_type} number format")
    sr = core.create_request(customer_id, "KYC_UPDATE", json.dumps({"type": document_type,
                             "number_last4": document_number[-4:]}), idempotency_key)
    core.update_customer(customer_id, kyc_status="UNDER_REVIEW", kyc_updated=date.today().isoformat())
    return {"reference": sr["reference"], "status": "UNDER_REVIEW", "document_type": document_type,
            "document": "XXXX" + document_number[-4:]}


# keep resolver import used (shared helper)
_ = _resolve_account
