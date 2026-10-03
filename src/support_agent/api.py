"""Public entry point. The eval harness and the CLI both use ``SupportAgent``.

async with SupportAgent(AgentConfig(model="claude-haiku-4-5-20251001")) as agent:
    result = await agent.triage("I was charged twice for Shards", followups=["ACC-1001, PC"])
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool

from .graph import ContextMode, ReplyProvider, Runtime, build_graph
from .llm import DEFAULT_MODEL, LLM, AnthropicLLM, make_chat_model
from .models import TriageResult
from .paths import default_data_dir, resolve_skills_dir
from .skills import load_skills


@dataclass
class AgentConfig:
    model: str = DEFAULT_MODEL
    skills_dir: str | Path | None = None  # path, or a name like "skills_v1"
    data_dir: str | Path | None = None
    context_mode: ContextMode = "progressive"
    max_intake_turns: int = 2
    max_tool_rounds: int = 4
    temperature: float | None = 0.0
    today: str = field(default_factory=lambda: date.today().isoformat())


class SupportAgent:
    def __init__(
        self,
        config: AgentConfig | None = None,
        *,
        llm_factory: Callable[[], LLM] | None = None,
        tools: list[BaseTool] | None = None,
    ):
        self.config = config or AgentConfig()
        self.skills_dir = resolve_skills_dir(self.config.skills_dir)
        self.data_dir = Path(self.config.data_dir or default_data_dir())
        self.skills = load_skills(self.skills_dir)
        self._llm_factory = llm_factory
        self._tools = tools
        self._stack: AsyncExitStack | None = None
        self.graph = build_graph()

    async def __aenter__(self) -> SupportAgent:
        if self._llm_factory is None:
            chat = make_chat_model(self.config.model, self.config.temperature)
            self._llm_factory = lambda: AnthropicLLM(chat)
        if self._tools is None:
            self._stack = AsyncExitStack()
            self._tools = await self._stack.enter_async_context(_mcp_tools(self.data_dir))
        return self

    async def __aexit__(self, *exc) -> None:
        if self._stack:
            await self._stack.aclose()

    @property
    def tools(self) -> list[BaseTool]:
        return self._tools or []

    async def triage(
        self,
        message: str,
        *,
        followups: list[str] | None = None,
        reply_provider: ReplyProvider | None = None,
    ) -> TriageResult:
        """Triage one player contact. Intake questions are answered by ``reply_provider``, or
        from the scripted ``followups`` list (used by evals), or not at all."""
        if reply_provider is None and followups is not None:
            reply_provider = _scripted(followups)
        llm = self._llm_factory()
        rt = Runtime(
            llm=llm,
            skills=self.skills,
            tools=self.tools,
            today=self.config.today,
            context_mode=self.config.context_mode,
            reply_provider=reply_provider,
            max_intake_turns=self.config.max_intake_turns,
            max_tool_rounds=self.config.max_tool_rounds,
        )
        start = time.perf_counter()
        state = await self.graph.ainvoke(
            {"messages": [HumanMessage(message)], "intake_turns": 0},
            config={"configurable": {"rt": rt}, "recursion_limit": 25},
        )
        latency = time.perf_counter() - start
        d = state["decision"]
        return TriageResult(
            skill=state["skill"],
            route_confidence=state["route_confidence"],
            route_reason=state["route_reason"],
            priority=d.priority,
            escalate=d.escalate,
            escalation_reason=d.escalation_reason,
            rationale=d.rationale,
            fields=state.get("fields", {}),
            missing_fields=state.get("missing", []),
            kb_articles=d.kb_articles,
            reply=d.reply,
            questions_asked=rt.questions,
            tool_calls=state.get("tool_calls", []),
            usage=llm.usage,
            cost_usd=llm.usage.cost_usd(self.config.model),
            latency_s=round(latency, 3),
            model=self.config.model,
            context_mode=self.config.context_mode,
            skills_dir=self.skills_dir.name,
        )


async def run_triage(message: str, config: AgentConfig | None = None, **kw) -> TriageResult:
    """One-shot convenience wrapper (starts and stops the MCP server)."""
    async with SupportAgent(config) as agent:
        return await agent.triage(message, **kw)


def _scripted(replies: list[str]) -> ReplyProvider:
    queue = list(replies)

    async def provider(_question: str) -> str | None:
        return queue.pop(0) if queue else None

    return provider


class _mcp_tools:
    """Start the MCP server over stdio once and keep the session open for many triages."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    async def __aenter__(self) -> list[BaseTool]:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_mcp_adapters.tools import load_mcp_tools

        client = MultiServerMCPClient(
            {
                "support": {
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "support_agent.mcp_server"],
                    "env": {**os.environ, "SUPPORT_AGENT_DATA": str(self.data_dir)},
                }
            }
        )
        self._cm = client.session("support")
        session = await self._cm.__aenter__()
        return await load_mcp_tools(session)

    async def __aexit__(self, *exc):
        await self._cm.__aexit__(*exc)
