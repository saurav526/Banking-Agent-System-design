"""
LLM Router & Resilience Module
==============================

Coordinates multi-tier LLM selection, sensitive-traffic policy routing,
dynamic circuit breaking, and telemetry instrumentation across model backends.

Key Routing Policies & Architecture:
------------------------------------
1. Sensitivity-Based Provider Chaining (`chain`):
   - Sensitive Traffic: Routes customer-facing, state-affecting, or private banking
     prompts to the on-premise/self-hosted model when `ROUTE_SENSITIVE_TO_SELF_HOSTED`
     is active and properly configured.
   - Default Traffic: Defaults to `LLM_DEFAULT_PROVIDER` (e.g., third-party frontier API).
   - Mock Fallback: Appends the deterministic `MockProvider` as a terminal zero-cost
     fallback to guarantee pipeline continuity during outages or testing.
   - Pre-Condition: Assumes PII redaction and vaulting have been applied prior to ingress.

2. Circuit Breaking & Fault Recovery:
   - Tracks provider downtime windows via `_open_until`.
   - On provider exception (timeout, HTTP 5xx, connection failure), trips the circuit
     breaker for 60 seconds and seamlessly fails over to the next candidate in the chain.

3. Observability & Telemetry Integration:
   - Records prompt payload summaries and tool schemas via `tracer.event`.
   - Wraps completion turns in distributed spans (`tracer.span("llm_call")`) capturing
     token consumption, estimated USD expenses, truncated response content, and tool calls.

4. Governance & Budget Enforcement:
   - Validates session spending limits via `cost_tracker.check_budget()` before initiating
     downstream provider invocations.
   - Computes and records accurate per-turn monetary usage via `cost_tracker.record()`.

5. Operational Health Monitoring:
   - `status()`: Reports real-time backend readiness, configuration states, models, and
     circuit breaker flags across all registered providers.
"""
from __future__ import annotations

import time

from ..config import settings
from ..cost.tracker import cost_tracker
from ..observability.tracer import tracer
from .base import LLMResponse
from .mock import MockProvider
from .openai_compat import OpenAICompatibleProvider


class LLMRouter:
    def __init__(self) -> None:
        self.providers = {
            "self_hosted": OpenAICompatibleProvider("self_hosted", settings.self_hosted_model,
                                                    settings.self_hosted_base_url, settings.self_hosted_api_key,
                                                    settings.llm_timeout_seconds),
            "third_party": OpenAICompatibleProvider("third_party", settings.third_party_model,
                                                    settings.third_party_base_url, settings.third_party_api_key,
                                                    settings.llm_timeout_seconds),
            "mock": MockProvider(),
        }
        self._open_until: dict[str, float] = {}

    def chain(self, sensitive: bool) -> list[str]:
        default = settings.llm_default_provider
        order = [default]
        if sensitive and settings.route_sensitive_to_self_hosted and default == "third_party":
            order = ["self_hosted", "third_party"]
        for p in ("self_hosted", "third_party"):
            if p not in order and default != "mock":
                order.append(p)
        order.append("mock")
        seen, out = set(), []
        for p in order:
            if p not in seen and self.providers[p].configured():
                seen.add(p)
                out.append(p)
        return out

    async def chat(self, *, agent: str, messages: list[dict], tools: list[dict] | None = None,
                   sensitive: bool = True) -> LLMResponse:
        cost_tracker.check_budget()
        last_err = None
        for name in self.chain(sensitive):
            if self._open_until.get(name, 0) > time.time():
                continue
            provider = self.providers[name]
            tracer.event("prompt", agent, provider=name, model=provider.model,
                         messages=messages[-3:], tools=[t["function"]["name"] for t in tools or []])
            try:
                with tracer.span("llm_call", agent, provider=name, model=provider.model) as span:
                    resp = await provider.chat(messages, tools)
                    usd = cost_tracker.record(agent=agent, model=resp.model or provider.model, provider=name,
                                              input_tokens=resp.input_tokens, output_tokens=resp.output_tokens)
                    span.update(input_tokens=resp.input_tokens, output_tokens=resp.output_tokens, usd=round(usd, 6),
                                tool_calls=[{"name": c.name, "args": c.arguments} for c in resp.tool_calls],
                                content=(resp.content or "")[:500])
                return resp
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                self._open_until[name] = time.time() + 60
                tracer.event("error", "llm_fallback", provider=name, error=repr(exc))
        raise RuntimeError(f"All LLM providers failed: {last_err!r}")

    def status(self) -> dict:
        return {n: {"configured": p.configured(), "model": p.model,
                    "circuit_open": self._open_until.get(n, 0) > time.time()} for n, p in self.providers.items()}


llm_router = LLMRouter()
