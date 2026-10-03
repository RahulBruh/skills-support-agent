from __future__ import annotations

from pydantic import BaseModel, Field

from .llm import Usage
from .skills import Priority


class RouteDecision(BaseModel):
    reason: str = Field(description="One short sentence explaining the choice.")
    skill: str = Field(description="Exactly one skill name from the list.")
    confidence: float = Field(ge=0, le=1)


class TriageDecision(BaseModel):
    rationale: str = Field(
        description="One sentence: which skill rules apply to this case and why."
    )
    priority: Priority
    escalate: bool
    escalation_reason: str | None = Field(
        None, description="The escalation rule that applied, if any."
    )
    kb_articles: list[str] = Field(
        default_factory=list,
        description="IDs (KB-xxx) of articles to share, only from tool results.",
    )
    reply: str = Field(
        description="2-5 sentence message to the player, in the skill persona's voice."
    )


class ToolCallRecord(BaseModel):
    tool: str
    args: dict
    result: str


class TriageResult(BaseModel):
    skill: str
    route_confidence: float
    route_reason: str
    priority: Priority
    escalate: bool
    escalation_reason: str | None
    rationale: str
    fields: dict[str, str]
    missing_fields: list[str]
    kb_articles: list[str]
    reply: str
    questions_asked: list[str]
    tool_calls: list[ToolCallRecord]
    usage: Usage
    cost_usd: float | None
    latency_s: float
    model: str
    context_mode: str
    skills_dir: str
