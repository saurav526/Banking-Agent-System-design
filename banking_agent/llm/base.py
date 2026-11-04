"""
LLM Provider Abstraction & Data Contracts Module
================================================

Establishes provider-agnostic interfaces and data structures standardizing
large language model (LLM) interactions across the multi-agent system using
the OpenAI Chat Completions schema.

Core Data Contracts & Protocols:
--------------------------------
1. ToolCall:
   - Encapsulates structured tool/function invocation metadata emitted by an LLM:
     * `id`: Unique identifier of the tool call.
     * `name`: Function/tool name to be dispatched.
     * `arguments`: Decoded key-value arguments supplied for tool invocation.

2. LLMResponse:
   - Unified envelope returned across all provider implementations containing:
     * `content`: Generated textual response or reasoning summary.
     * `tool_calls`: List of requested `ToolCall` executions.
     * `input_tokens` / `output_tokens`: Billed or measured token usage for cost tracking.
     * `model` / `provider`: Target model name and backend identifier.

3. LLMProvider (Protocol):
   - Defines the structural typing interface required for any upstream LLM backend
     (e.g., self-hosted vLLM/Ollama, third-party APIs like Anthropic/OpenAI, or unit-test mocks):
     * `name`: Provider class identifier ("self_hosted", "third_party", "mock").
     * `model`: Specific model identifier string.
     * `configured()`: Validates whether required API credentials, hosts, or configurations exist.
     * `chat(messages, tools)`: Asynchronous completion interface consuming OpenAI-format
       chat messages and optional function schemas, returning an `LLMResponse`.
"""
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
