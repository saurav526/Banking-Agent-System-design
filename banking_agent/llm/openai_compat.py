"""OpenAI-compatible provider - used for BOTH:

* Self-hosted LLM  (Ollama / vLLM / TGI / LM Studio expose /v1 chat completions)
* Third-party LLM  (OpenAI, Azure OpenAI, or any compatible gateway)
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
