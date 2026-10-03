"""Thin LLM layer: structured output + tool calling, with per-run token accounting.

The graph only depends on the ``LLM`` protocol, so tests can swap in a scripted fake.
"""

from __future__ import annotations

import os
from typing import Protocol, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# USD per million tokens: (input, output, cache_write_5m, cache_read).
# Source: https://platform.claude.com/docs/en/about-claude/pricing (checked 2026-10-03).
PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0, 1.25, 0.10),
    "claude-sonnet-5-5": (2.0, 10.0, 2.50, 0.20),
    "claude-sonnet-4-5": (3.0, 15.0, 3.75, 0.30),
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
}


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    llm_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, msg: AIMessage) -> None:
        meta = msg.usage_metadata or {}
        details = meta.get("input_token_details") or {}
        self.input_tokens += meta.get("input_tokens", 0)
        self.output_tokens += meta.get("output_tokens", 0)
        self.cache_read_tokens += details.get("cache_read", 0) or 0
        self.cache_write_tokens += details.get("cache_creation", 0) or 0
        self.llm_calls += 1

    def cost_usd(self, model: str) -> float | None:
        price = next((p for k, p in PRICING.items() if model.startswith(k)), None)
        if price is None:
            return None
        inp, out, cw, cr = price
        # langchain-anthropic reports input_tokens inclusive of cache reads/writes.
        uncached = self.input_tokens - self.cache_read_tokens - self.cache_write_tokens
        return (
            uncached * inp
            + self.output_tokens * out
            + self.cache_write_tokens * cw
            + self.cache_read_tokens * cr
        ) / 1_000_000


class LLM(Protocol):
    usage: Usage

    async def structured(self, system: str, messages: list[BaseMessage], schema: type[T]) -> T: ...

    async def with_tools(
        self, system: str, messages: list[BaseMessage], tools: list[BaseTool]
    ) -> AIMessage: ...


class AnthropicLLM:
    """One instance per triage run so usage is attributed to that run."""

    def __init__(self, chat):
        self.chat = chat
        self.usage = Usage()

    async def structured(self, system, messages, schema):
        runnable = self.chat.with_structured_output(schema, include_raw=True)
        out = await runnable.ainvoke([SystemMessage(system), *messages])
        self.usage.add(out["raw"])
        if out.get("parsed") is None:
            raise ValueError(
                f"Model did not return a valid {schema.__name__}: {out.get('parsing_error')}"
            )
        return out["parsed"]

    async def with_tools(self, system, messages, tools):
        msg = await self.chat.bind_tools(tools).ainvoke([SystemMessage(system), *messages])
        self.usage.add(msg)
        return msg


def anthropic_headers() -> dict[str, str]:
    """Org-level API keys must name a workspace; workspace-scoped keys need nothing."""
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    return {"anthropic-workspace-id": ws} if ws else {}


def make_chat_model(model: str, temperature: float | None = 0.0, max_tokens: int = 1024):
    from langchain_anthropic import ChatAnthropic

    kwargs = {"model": model, "max_tokens": max_tokens, "max_retries": 4}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if headers := anthropic_headers():
        kwargs["default_headers"] = headers
    return ChatAnthropic(**kwargs)
