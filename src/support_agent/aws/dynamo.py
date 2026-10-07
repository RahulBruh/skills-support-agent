"""DynamoDB storage for the support tools.

One table per entity rather than a single-table design, so that IAM can scope each tool's
Lambda to exactly the data it may read (see ADR-7 in docs/decisions.md). Keys follow the access
patterns of the tools:

=================  ============================  ===========================================
table              key                           access pattern
=================  ============================  ===========================================
accounts           account_id                    GetItem by ID
  by-email (GSI)   email_lc  (KEYS_ONLY)         email -> account_id, for every account tool
purchases          account_id + sk               Query one account's orders, newest first
                   (sk = "<date>#<order_id>")
tickets            ticket_id                     GetItem by ID
  by-account (GSI) account_id + created          Query one account's tickets
kb                 article_id                    Scan (a few dozen articles; ranked in-process)
service_status     game                          Scan (one item per game)
=================  ============================  ===========================================

``TABLES`` is the single source of truth: the CDK stack, the seed command and the moto tests
all build their tables from it.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..paths import default_data_dir
from ..tools_impl import Backend, load_kb

DEFAULT_PREFIX = "support-agent"

# name -> (partition key, sort key | None, {index name: (pk, sk | None, projection)})
TABLES: dict[str, tuple[str, str | None, dict[str, tuple[str, str | None, str]]]] = {
    "accounts": ("account_id", None, {"by-email": ("email_lc", None, "KEYS_ONLY")}),
    "purchases": ("account_id", "sk", {}),
    "tickets": ("ticket_id", None, {"by-account": ("account_id", "created", "ALL")}),
    "kb": ("article_id", None, {}),
    "service_status": ("game", None, {}),
}

_ACCOUNT_ID = re.compile(r"^acc-\d+$", re.IGNORECASE)


def table_name(entity: str, prefix: str | None = None) -> str:
    prefix = prefix or os.environ.get("SUPPORT_AGENT_TABLE_PREFIX", DEFAULT_PREFIX)
    return f"{prefix}-{entity.replace('_', '-')}"


def create_table_kwargs(entity: str, prefix: str | None = None) -> dict:
    """``create_table`` arguments for one entity (used by tests; CDK mirrors the same spec)."""
    pk, sk, indexes = TABLES[entity]
    attrs = {pk, *([sk] if sk else [])}
    key = [{"AttributeName": pk, "KeyType": "HASH"}]
    if sk:
        key.append({"AttributeName": sk, "KeyType": "RANGE"})
    gsis = []
    for name, (ipk, isk, projection) in indexes.items():
        attrs |= {ipk, *([isk] if isk else [])}
        ikey = [{"AttributeName": ipk, "KeyType": "HASH"}]
        if isk:
            ikey.append({"AttributeName": isk, "KeyType": "RANGE"})
        gsis.append(
            {"IndexName": name, "KeySchema": ikey, "Projection": {"ProjectionType": projection}}
        )
    kwargs = {
        "TableName": table_name(entity, prefix),
        "KeySchema": key,
        "AttributeDefinitions": [{"AttributeName": a, "AttributeType": "S"} for a in sorted(attrs)],
        "BillingMode": "PAY_PER_REQUEST",
    }
    if gsis:
        kwargs["GlobalSecondaryIndexes"] = gsis
    return kwargs


class DynamoBackend(Backend):
    """Reads the same data as ``JsonBackend`` from DynamoDB.

    Each method touches only the tables its tool needs, so a Lambda whose IAM role covers just
    those tables works without errors (and any drift shows up as AccessDenied, not silent leaks).
    """

    def __init__(self, prefix: str | None = None, *, resource=None):
        import boto3

        self.db = resource or boto3.resource("dynamodb")
        self.prefix = prefix
        self._tables: dict[str, Any] = {}

    def _t(self, entity: str):
        if entity not in self._tables:
            self._tables[entity] = self.db.Table(table_name(entity, self.prefix))
        return self._tables[entity]

    def _account_id(self, key: str) -> str | None:
        key = key.strip()
        if _ACCOUNT_ID.match(key):
            # Only the key attribute is requested: the purchases and tickets roles may GetItem on
            # accounts solely with ProjectionExpression=account_id (IAM dynamodb:Attributes).
            res = self._t("accounts").get_item(
                Key={"account_id": key.upper()}, ProjectionExpression="account_id"
            )
            return res["Item"]["account_id"] if "Item" in res else None
        from boto3.dynamodb.conditions import Key

        res = self._t("accounts").query(
            IndexName="by-email", KeyConditionExpression=Key("email_lc").eq(key.lower())
        )
        return res["Items"][0]["account_id"] if res["Items"] else None

    def _account(self, key: str) -> dict | None:
        key = key.strip()
        acc_id = key.upper() if _ACCOUNT_ID.match(key) else self._account_id(key)
        if acc_id is None:
            return None
        item = self._t("accounts").get_item(Key={"account_id": acc_id}).get("Item")
        if item is None:
            return None
        item.pop("email_lc", None)
        return _plain(item)

    def _purchases(self, account_id: str) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        items = _query_all(
            self._t("purchases"),
            KeyConditionExpression=Key("account_id").eq(account_id),
            ScanIndexForward=False,
        )
        return [
            _plain({k: v for k, v in i.items() if k not in ("account_id", "sk")}) for i in items
        ]

    def _tickets(self, ticket_id: str) -> list[dict]:
        item = self._t("tickets").get_item(Key={"ticket_id": ticket_id.upper()}).get("Item")
        return [_plain(item)] if item else []

    def _tickets_for_account(self, account_id: str) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        items = _query_all(
            self._t("tickets"),
            IndexName="by-account",
            KeyConditionExpression=Key("account_id").eq(account_id.upper()),
        )
        return [_plain(i) for i in items]

    def _kb(self) -> list[dict]:
        items = _scan_all(self._t("kb"))
        arts = [
            {
                "id": i["article_id"],
                "title": i["title"],
                "tags": i.get("tags", []),
                "body": i["body"],
            }
            for i in items
        ]
        return sorted(arts, key=lambda a: a["id"])

    def _status(self) -> dict:
        items = _scan_all(self._t("service_status"))
        # Keep the curated order: fuzzy game matching returns the first hit.
        items.sort(key=lambda i: i["position"])
        meta = ("game", "as_of", "position")
        games = {i["game"]: _plain({k: v for k, v in i.items() if k not in meta}) for i in items}
        as_of = max((i["as_of"] for i in items), default=None)
        return {"as_of": as_of, "games": games}


# -- seeding ----------------------------------------------------------------------------------


def items_from_data(data_dir: Path | None = None) -> dict[str, list[dict]]:
    """Turn the files under ``data/`` into DynamoDB items, keyed by entity."""
    data_dir = Path(data_dir or default_data_dir())

    def load(name: str):
        # Floats must be Decimal for DynamoDB.
        return json.loads((data_dir / name).read_text(encoding="utf-8"), parse_float=Decimal)

    out: dict[str, list[dict]] = {e: [] for e in TABLES}
    for a in load("accounts.json"):
        purchases = a.pop("purchases")
        out["accounts"].append({**a, "email_lc": a["email"].lower()})
        for p in purchases:
            out["purchases"].append(
                {"account_id": a["account_id"], "sk": f"{p['date']}#{p['order_id']}", **p}
            )
    out["tickets"] = load("tickets.json")
    for art in load_kb(data_dir):
        out["kb"].append(
            {
                "article_id": art["id"],
                "title": art["title"],
                "tags": art["tags"],
                "body": art["body"],
            }
        )
    status = load("service_status.json")
    for position, (game, info) in enumerate(status["games"].items()):
        out["service_status"].append(
            {"game": game, "as_of": status["as_of"], "position": position, **info}
        )
    return out


def seed(
    prefix: str | None = None, data_dir: Path | None = None, *, resource=None
) -> dict[str, int]:
    """Load the mock data into existing tables. Idempotent: items are overwritten by key."""
    import boto3

    db = resource or boto3.resource("dynamodb")
    counts = {}
    for entity, items in items_from_data(data_dir).items():
        with db.Table(table_name(entity, prefix)).batch_writer() as batch:
            for item in items:
                batch.put_item(Item=item)
        counts[entity] = len(items)
    return counts


# -- helpers ----------------------------------------------------------------------------------


def _query_all(table, **kwargs) -> list[dict]:
    items, start = [], None
    while True:
        res = table.query(**kwargs, **({"ExclusiveStartKey": start} if start else {}))
        items += res["Items"]
        if not (start := res.get("LastEvaluatedKey")):
            return items


def _scan_all(table) -> list[dict]:
    items, start = [], None
    while True:
        res = table.scan(**({"ExclusiveStartKey": start} if start else {}))
        items += res["Items"]
        if not (start := res.get("LastEvaluatedKey")):
            return items


def _plain(value):
    """DynamoDB returns numbers as Decimal; give tools the same JSON types as the files."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value
