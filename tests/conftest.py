from __future__ import annotations

import os
from collections.abc import Callable

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from support_agent.llm import Usage
from support_agent.tools_impl import JsonBackend


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
    b = JsonBackend()
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


TEST_TABLE_PREFIX = "test"


@pytest.fixture
def dynamo_db():
    """Mocked DynamoDB (moto) with every table created and seeded from data/."""
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    from support_agent.aws.dynamo import TABLES, create_table_kwargs, seed

    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        db = boto3.resource("dynamodb", region_name="us-east-1")
        for entity in TABLES:
            db.create_table(**create_table_kwargs(entity, TEST_TABLE_PREFIX))
        counts = seed(TEST_TABLE_PREFIX, resource=db)
        assert counts["accounts"] == 10 and counts["kb"] == 14
        yield db


@pytest.fixture
def dynamo(dynamo_db):
    from support_agent.aws.dynamo import DynamoBackend

    return DynamoBackend(TEST_TABLE_PREFIX, resource=dynamo_db)
