"""
OpenAI-Compatible LLM Provider Module
=====================================

Implements the `LLMProvider` protocol for any backend exposing an OpenAI-style
`/v1/chat/completions` REST interface. This serves as a unified client for:
  - Self-hosted runtimes: Ollama, vLLM, Text Generation Inference (TGI), or LM Studio.
  - Third-party endpoints: OpenAI, Azure OpenAI, or managed API gateways.

Key Components & Capabilities:
------------------------------
1. Lazy Client Initialization (`_get`):
   - Lazily instantiates an `AsyncOpenAI` client using the configured `base_url`,
     `api_key`, `timeout`, and a single retry attempt (`max_retries=1`).
   - Reuses the shared client across invocations to optimize connection pooling.

2. Configuration Validation (`configured`):
   - Verifies that the optional `openai` library dependency is installed.
   - For `third_party` providers: requires a non-empty `api_key`.
   - For `self_hosted` providers: requires a defined `base_url`.

3. Chat Completion & Tool Calling (`chat`):
   - Dispatches asynchronous completion requests with deterministic sampling (`temperature=0`).
   - Supplies tool/function definitions when provided, enabling `tool_choice="auto"`.
   - Safely deserializes model-generated tool arguments (`json.loads`) into typed
     `ToolCall` instances, guarding against malformed JSON output.
   - Extracts prompt/completion token usage and packages the result into a normalized
     `LLMResponse`.
"""
from __future__ import annotations

import json

from .base import LLMResponse, ToolCall

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover
    AsyncOpenAI = None


class OpenAICompatibleProvider:
    def __init__(self, name: str, model: str, base_url: str | None, api_key: str | None, timeout: float) -> None:
        self.name = name
        self.model = model
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout
        self._client = None

    def configured(self) -> bool:
        if AsyncOpenAI is None:
            return False
        if self.name == "third_party":
            return bool(self._api_key)
        return bool(self._base_url)

    def _get(self):
        if self._client is None:
            self._client = AsyncOpenAI(base_url=self._base_url, api_key=self._api_key or "none",
                                       timeout=self._timeout, max_retries=1)
        return self._client

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        kwargs: dict = {"model": self.model, "messages": messages, "temperature": 0}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = await self._get().chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tc.id, tc.function.name, args))
        usage = resp.usage
        return LLMResponse(
            content=msg.content,
            tool_calls=calls,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=self.model,
            provider=self.name,
        )
