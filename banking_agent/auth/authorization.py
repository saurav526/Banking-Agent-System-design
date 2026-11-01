"""Authorisation: policy decision point used by the Coordinator Agent.

Decides whether a principal may (a) use an agent and (b) invoke a tool, and
enforces data-ownership (a customer can only touch their own accounts) and
step-up authentication for sensitive, state-changing operations.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..observability.tracer import tracer
from .identity_provider import Principal

# role -> agents allowed
AGENT_POLICY: dict[str, set[str]] = {
    "customer": {"accounts", "transactions", "service"},
    "ops": {"accounts"},  # ops staff may only view (read-only demo)
}

# tool -> (required role(s), requires MFA/step-up, is_write)
TOOL_POLICY: dict[str, tuple[set[str], bool, bool]] = {
    "list_accounts": ({"customer"}, False, False),
    "balance_enquiry": ({"customer"}, False, False),
    "transaction_details": ({"customer"}, False, False),
    "statement_request": ({"customer"}, False, True),
    "change_of_address": ({"customer"}, True, True),
    "chequebook_request": ({"customer"}, False, True),
    "kyc_status": ({"customer"}, False, False),
    "kyc_update": ({"customer"}, True, True),
}


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


class Authoriser:
    def can_use_agent(self, p: Principal, agent: str) -> Decision:
        ok = any(agent in AGENT_POLICY.get(r, set()) for r in p.roles)
        d = Decision(ok, "" if ok else f"Role(s) {p.roles} may not use the {agent} agent")
        tracer.event("authz", "agent", agent=agent, allowed=d.allowed, reason=d.reason)
        return d

    def can_call_tool(self, p: Principal, tool: str, args: dict, owned_accounts: set[str]) -> Decision:
        policy = TOOL_POLICY.get(tool)
        if policy is None:
            d = Decision(False, f"Tool '{tool}' is not registered in policy (deny by default)")
        else:
            roles, needs_mfa, _ = policy
            if not roles.intersection(p.roles):
                d = Decision(False, f"Role not permitted for {tool}")
            elif needs_mfa and not p.mfa:
                d = Decision(False, f"'{tool}' requires step-up (MFA) authentication")
            elif args.get("account_id") and args["account_id"] not in owned_accounts:
                d = Decision(False, "Account does not belong to the authenticated customer")
            else:
                d = Decision(True)
        tracer.event("authz", "tool", tool=tool, allowed=d.allowed, reason=d.reason)
        return d


authoriser = Authoriser()
