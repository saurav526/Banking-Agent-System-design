"""
Authorization Policy Decision Point (PDP) Module
================================================

Enforces role-based access control (RBAC), multi-factor authentication (MFA) step-up
requirements, and resource-level data isolation for the Coordinator Agent.

Key Responsibilities & Enforcement Policies:
--------------------------------------------
1. Agent-Level Authorization (`can_use_agent`):
   - Restricts sub-agent accessibility by principal roles defined in `AGENT_POLICY`.
   - Distinguishes customer domains (accounts, transactions, service) from operational
     staff scopes (read-only accounts view).

2. Tool-Level Authorization (`can_call_tool`):
   - Implements a deny-by-default posture for unregistered tools.
   - Validates caller role membership against permitted tool invocation roles.
   - Enforces step-up MFA verification on sensitive, state-altering operations
     (e.g., change of address, KYC updates).

3. Data Ownership & Tenant Isolation:
   - Validates that targeted resources (`account_id`) belong exclusively to the
     authenticated principal's set of owned accounts before permitting tool execution.

4. Auditability & Observability:
   - Emits structured telemetry traces via `tracer` recording all evaluation
     events, decisions (allowed/denied), and failure reasons.
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
