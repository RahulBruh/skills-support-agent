from __future__ import annotations

from collections.abc import Callable

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from support_agent.llm import Usage
from support_agent.tools_impl import Backend


class FakeLLM:
    """Scripted LLM. ``handler(kind, system, messages, schema_or_tools)`` returns the response;
    every call is recorded so tests can assert on prompts."""

    def __init__(self, handler: Callable):
        self.handler = handler
        self.usage = Usage()
        self.calls: list[tuple[str, str]] = []

    async def structured(self, system, messages, schema):
        self.calls.append(("structured:" + schema.__name__, system))
        self.usage.llm_calls += 1
        out = self.handler("structured", system, messages, schema)
        return out if isinstance(out, schema) else schema(**out)

    async def with_tools(self, system, messages, tools):
        self.calls.append(("tools", system))
        self.usage.llm_calls += 1
        return self.handler("tools", system, messages, tools)


def tool_call(name: str, **args) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"call_{name}"}])


@pytest.fixture
def local_tools() -> list[StructuredTool]:
    """The same tools the MCP server exposes, wrapped in-process (no subprocess)."""
    b = Backend()
    return [
        StructuredTool.from_function(getattr(b, name), name=name, description=name)
        for name in (
            "lookup_ticket",
            "get_account_status",
            "get_purchase_history",
            "search_kb",
            "get_service_status",
        )
    ]
