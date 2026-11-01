"""Common LLM abstractions (OpenAI chat-completions message format)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    provider: str = ""


class LLMProvider(Protocol):
    name: str  # "self_hosted" | "third_party" | "mock"
    model: str

    def configured(self) -> bool: ...

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse: ...
