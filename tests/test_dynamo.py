"""DynamoBackend against moto: same answers as JsonBackend for every tool."""

import os

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from support_agent.aws.dynamo import TABLES, DynamoBackend, create_table_kwargs, seed  # noqa: E402
from support_agent.tools_impl import JsonBackend  # noqa: E402

PREFIX = "test"


@pytest.fixture
def dynamo():
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        db = boto3.resource("dynamodb", region_name="us-east-1")
        for entity in TABLES:
            db.create_table(**create_table_kwargs(entity, PREFIX))
        counts = seed(PREFIX, resource=db)
        assert counts["accounts"] == 10 and counts["kb"] == 14
        yield DynamoBackend(PREFIX, resource=db)


def _by_order(out: dict) -> dict:
    # DynamoDB returns purchases newest-first by sort key; the JSON file is hand-ordered.
    if "purchases" in out:
        out = {**out, "purchases": sorted(out["purchases"], key=lambda p: p["order_id"])}
    return out


@pytest.mark.parametrize(
    "tool,kwargs",
    [
        ("get_account_status", {"account": "ACC-1003"}),
        ("get_account_status", {"account": "acc-1003"}),
        ("get_account_status", {"account": " PRIYA.S@example.com "}),
        ("get_account_status", {"account": "ACC-9999"}),
        ("get_account_status", {"account": "nobody@example.com"}),
        ("get_purchase_history", {"account": "maya.r@example.com"}),
        ("get_purchase_history", {"account": "ACC-1001"}),
        ("get_purchase_history", {"account": "ACC-1005"}),
        ("get_purchase_history", {"account": "ACC-9999"}),
        ("lookup_ticket", {"ticket_id": "tck-7001"}),
        ("lookup_ticket", {"ticket_id": "TCK-0000"}),
        ("lookup_ticket", {"account": "jordan.k@example.com"}),
        ("lookup_ticket", {"account": "ACC-1004"}),
        ("lookup_ticket", {}),
        ("search_kb", {"query": "refund playstation"}),
        ("search_kb", {"query": "forgot password", "top_k": 5}),
        ("search_kb", {"query": "zzzz"}),
        ("get_service_status", {}),
        ("get_service_status", {"game": "starfall"}),
        ("get_service_status", {"game": "Unknown Game"}),
    ],
)
def test_parity_with_json_backend(dynamo, tool, kwargs):
    expected = getattr(JsonBackend(), tool)(**kwargs)
    assert _by_order(getattr(dynamo, tool)(**kwargs)) == _by_order(expected)


def test_purchases_newest_first_with_json_number_types(dynamo):
    purchases = dynamo.get_purchase_history("ACC-1001")["purchases"]
    assert [p["order_id"] for p in purchases] == ["ORD-50012", "ORD-50011", "ORD-49870"]
    assert isinstance(purchases[0]["amount_usd"], float)


def test_email_index_is_keys_only(dynamo):
    # The purchases/tickets roles may query this index; it must not leak account data.
    res = dynamo._t("accounts").query(
        IndexName="by-email",
        KeyConditionExpression=boto3.dynamodb.conditions.Key("email_lc").eq("priya.s@example.com"),
    )
    assert set(res["Items"][0]) == {"account_id", "email_lc"}
