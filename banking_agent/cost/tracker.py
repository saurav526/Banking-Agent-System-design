"""
Cost Tracking & Budget Governance Module
========================================

Monitors token consumption, computes real-time LLM spending, and enforces strict
per-session monetary budget guardrails across models, users, and sub-agents.

Key Components & Responsibilities:
----------------------------------
1. Token Estimation (`count_tokens`):
   - Computes token counts using the `cl100k_base` BPE encoding via `tiktoken`
     when enabled (`USE_TIKTOKEN=1`).
   - Falls back gracefully to a standard heuristic (1 token ≈ 4 characters)
     for offline, uninstalled, or low-overhead environments.

2. Cost Accounting & Attribution (`CostTracker.record`):
   - Calculates prompt and completion expenses based on configured unit rates per
     million tokens (`settings.pricing`).
   - Employs thread-safe locks (`threading.Lock`) to attribute USD expenditures across:
     * Session (`by_session`) – contextualized via `current_session_id`.
     * User (`by_user`) – contextualized via `current_user_id`.
     * Domain Agent (`by_agent`) – segmented by calling agent.
     * Model (`by_model`) – tracking call counts, token aggregates, and spend.

3. Budget Guardrail Enforcement (`check_budget`):
   - Compares accumulated session spend against `settings.session_budget_usd`.
   - Raises `BudgetExceeded` to halt pipeline execution before issuing additional
     costly LLM invocations.

4. Spend Reporting (`summary`):
   - Exports high-precision, rounded financial summaries detailing overall and
     dimension-specific expenditure for downstream telemetry and user auditing.
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict

from ..config import settings
from ..observability.tracer import current_session_id, current_user_id

_ENC = None
if os.getenv("USE_TIKTOKEN", "0") == "1":  # opt-in: first use downloads the BPE file
    try:
        import tiktoken

        _ENC = tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - offline / not installed
        _ENC = None


def count_tokens(text: str) -> int:
    if not text:
        return 0
    if _ENC is not None:
        try:
            return len(_ENC.encode(text))
        except Exception:  # noqa: BLE001
            pass
    return max(1, len(text) // 4)


class BudgetExceeded(Exception):
    pass


class CostTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.by_session: dict[str, float] = defaultdict(float)
        self.by_user: dict[str, float] = defaultdict(float)
        self.by_agent: dict[str, float] = defaultdict(float)
        self.by_model: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0})
        self.total_usd = 0.0

    def price(self, model: str, provider: str) -> tuple[float, float]:
        p = settings.pricing
        if model in p:
            return p[model]
        if provider == "self_hosted":
            return p["self_hosted"]
        if provider == "mock":
            return p["mock"]
        return p.get("gpt-4o-mini", (0.15, 0.6))

    def check_budget(self) -> None:
        sid = current_session_id.get()
        if self.by_session.get(sid, 0.0) >= settings.session_budget_usd:
            raise BudgetExceeded(f"Session budget of ${settings.session_budget_usd:.2f} exhausted")

    def record(self, *, agent: str, model: str, provider: str, input_tokens: int, output_tokens: int) -> float:
        pin, pout = self.price(model, provider)
        usd = (input_tokens * pin + output_tokens * pout) / 1_000_000
        with self._lock:
            sid, uid = current_session_id.get(), current_user_id.get()
            self.by_session[sid] += usd
            self.by_user[uid] += usd
            self.by_agent[agent] += usd
            m = self.by_model[model]
            m["calls"] += 1
            m["input_tokens"] += input_tokens
            m["output_tokens"] += output_tokens
            m["usd"] += usd
            self.total_usd += usd
        return usd

    def summary(self) -> dict:
        with self._lock:
            r = lambda d: {k: round(v, 6) for k, v in d.items()}
            return {
                "total_usd": round(self.total_usd, 6),
                "by_model": {k: {**v, "usd": round(v["usd"], 6)} for k, v in self.by_model.items()},
                "by_agent": r(self.by_agent),
                "by_user": r(self.by_user),
                "by_session": r(self.by_session),
                "session_budget_usd": settings.session_budget_usd,
            }


cost_tracker = CostTracker()
