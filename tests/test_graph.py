from langchain_core.messages import AIMessage

from support_agent.api import AgentConfig, SupportAgent
from tests.conftest import FakeLLM, tool_call


def make_agent(handler, tools, **cfg):
    fake = FakeLLM(handler)
    agent = SupportAgent(
        AgentConfig(today="2026-10-03", **cfg), llm_factory=lambda: fake, tools=tools
    )
    return agent, fake


def billing_handler(kind, system, messages, schema_or_tools):
    if kind == "tools":
        if not any(m.type == "tool" for m in messages):
            return tool_call("get_purchase_history", account="ACC-1001")
        return AIMessage("DONE")
    name = schema_or_tools.__name__
    if name == "RouteDecision":
        return {"reason": "double charge", "skill": "billing", "confidence": 0.95}
    if name == "billing_fields":
        said = " ".join(str(m.content) for m in messages)
        fields = {"issue_type": "duplicate charge"}
        if "ACC-1001" in said:
            fields |= {
                "account_id": "ACC-1001",
                "platform": "PC",
                "transaction_reference": "ORD-50012",
            }
        return fields
    return {
        "rationale": "Duplicate confirmed",
        "priority": "P2",
        "escalate": True,
        "escalation_reason": "duplicate charge",
        "kb_articles": ["KB-101"],
        "reply": "On it.",
    }


async def test_billing_flow_asks_for_missing_fields_then_uses_tools(local_tools):
    agent, _ = make_agent(billing_handler, local_tools)
    r = await agent.triage(
        "I got charged twice for Shards!", followups=["ACC-1001 on PC, ORD-50012"]
    )
    assert r.skill == "billing" and r.priority == "P2" and r.escalate
    assert len(r.questions_asked) == 1 and "account" in r.questions_asked[0].lower()
    assert r.fields["account_id"] == "ACC-1001" and r.missing_fields == []
    assert [c.tool for c in r.tool_calls] == ["get_purchase_history"]
    assert "ORD-50012" in r.tool_calls[0].result
    assert r.usage.llm_calls == 6  # route, extract x2, tools x2, decide


async def test_no_followups_means_no_questions(local_tools):
    agent, _ = make_agent(billing_handler, local_tools)
    r = await agent.triage("I got charged twice for Shards!")
    assert r.questions_asked == [] and set(r.missing_fields) == {
        "account_id",
        "platform",
        "transaction_reference",
    }


async def test_intake_turns_are_capped(local_tools):
    agent, _ = make_agent(billing_handler, local_tools, max_intake_turns=2)
    r = await agent.triage("charged twice", followups=["idk", "still idk", "never asked"])
    assert len(r.questions_asked) == 2


async def test_low_confidence_routes_to_general_and_escalates(local_tools):
    def handler(kind, system, messages, s):
        if kind == "tools":
            return AIMessage("DONE")
        if s.__name__ == "RouteDecision":
            return {"reason": "unclear", "skill": "billing", "confidence": 0.3}
        return {"rationale": "x", "priority": "P4", "escalate": False, "reply": "Thanks"}

    agent, _ = make_agent(handler, local_tools)
    r = await agent.triage("what's your favourite colour")
    assert r.skill == "general" and r.escalate is True


async def test_disallowed_tool_call_is_blocked(local_tools):
    def handler(kind, system, messages, tools):
        if kind == "tools":
            assert {t.name for t in tools} == {"get_service_status", "search_kb", "lookup_ticket"}
            if not any(m.type == "tool" for m in messages):
                return tool_call("get_purchase_history", account="ACC-1001")
            return AIMessage("DONE")
        if tools.__name__ == "RouteDecision":
            return {"reason": "crash", "skill": "bug-report", "confidence": 0.9}
        if tools.__name__.endswith("_fields"):
            return {}
        return {"rationale": "x", "priority": "P3", "escalate": False, "reply": "ok"}

    agent, _ = make_agent(handler, local_tools)
    r = await agent.triage("game crashes")
    assert "not allowed" in r.tool_calls[0].result


async def test_progressive_router_sees_only_descriptions(local_tools):
    agent, fake = make_agent(billing_handler, local_tools, context_mode="progressive")
    await agent.triage("charged twice")
    router_prompt = fake.calls[0][1]
    assert "- billing: Charges, refunds" in router_prompt
    assert "Refund window" not in router_prompt  # skill body not loaded for routing
    decide_prompt = fake.calls[-1][1]
    assert "Refund window" in decide_prompt and "lost 2FA" not in decide_prompt


async def test_inline_all_loads_every_skill(local_tools):
    agent, fake = make_agent(billing_handler, local_tools, context_mode="inline_all")
    await agent.triage("charged twice")
    decide_prompt = fake.calls[-1][1]
    assert "Refund window" in decide_prompt and "Lost 2FA" in decide_prompt
    assert len(decide_prompt) > 2 * len(
        make_agent(billing_handler, local_tools)[0].skills["billing"].rules_block()
    )
