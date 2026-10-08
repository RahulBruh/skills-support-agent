"""Every DynamoDB call a tool makes must be allowed by its IAM entry in TOOL_ACCESS, and every
entry must be needed by some call: the deployed policies are sufficient and minimal."""

import pytest

from support_agent.aws.access import TOOL_ACCESS, Access
from support_agent.aws.dynamo import TABLES, table_name
from support_agent.tools_impl import TOOL_NAMES

from .conftest import TEST_TABLE_PREFIX

pytest.importorskip("boto3")

# Inputs that drive every code path: ID vs email vs unknown, found vs not found.
CALLS = {
    "get_account_status": [
        {"account": "ACC-1003"},
        {"account": "priya.s@example.com"},
        {"account": "nobody@example.com"},
    ],
    "get_purchase_history": [
        {"account": "ACC-1001"},
        {"account": "maya.r@example.com"},
        {"account": "ACC-9999"},
    ],
    "lookup_ticket": [
        {"ticket_id": "TCK-7001"},
        {"account": "ACC-1004"},
        {"account": "jordan.k@example.com"},
    ],
    "search_kb": [{"query": "refund"}],
    "get_service_status": [{}, {"game": "starfall"}],
}

_ENTITY_BY_TABLE = {table_name(e, TEST_TABLE_PREFIX): e for e in TABLES}


def _record(db) -> list[dict]:
    calls: list[dict] = []

    def hook(params, model, **_):
        proj = params.get("ProjectionExpression")
        calls.append(
            {
                "entity": _ENTITY_BY_TABLE[params["TableName"]],
                "action": model.name,
                "index": params.get("IndexName"),
                "attributes": tuple(a.strip() for a in proj.split(",")) if proj else None,
            }
        )

    db.meta.client.meta.events.register("provide-client-params.dynamodb.*", hook)
    return calls


def _allows(a: Access, call: dict) -> bool:
    return (
        a.entity == call["entity"]
        and a.action == call["action"]
        and a.index == call["index"]
        and (
            a.attributes is None
            or (call["attributes"] or ())
            and set(call["attributes"]) <= set(a.attributes)
        )
    )


def test_every_tool_has_an_access_entry():
    assert set(TOOL_ACCESS) == TOOL_NAMES == set(CALLS)


@pytest.mark.parametrize("tool", sorted(TOOL_ACCESS))
def test_tool_calls_are_exactly_covered_by_its_policy(dynamo, dynamo_db, tool):
    calls = _record(dynamo_db)
    for kwargs in CALLS[tool]:
        getattr(dynamo, tool)(**kwargs)
    assert calls, f"{tool} made no DynamoDB calls"

    denied = [c for c in calls if not any(_allows(a, c) for a in TOOL_ACCESS[tool])]
    assert not denied, f"{tool} would get AccessDenied for: {denied}"

    unused = [a for a in TOOL_ACCESS[tool] if not any(_allows(a, c) for c in calls)]
    assert not unused, f"{tool} is granted access it never uses: {unused}"


def test_resolving_an_account_never_reads_account_attributes(dynamo, dynamo_db):
    calls = _record(dynamo_db)
    dynamo.get_purchase_history("ACC-1001")
    dynamo.lookup_ticket(account="ACC-1001")
    gets = [c for c in calls if c["entity"] == "accounts" and c["action"] == "GetItem"]
    assert gets and all(c["attributes"] == ("account_id",) for c in gets)
