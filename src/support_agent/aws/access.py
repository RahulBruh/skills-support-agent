"""Least-privilege data access per tool.

The CDK stack turns each entry into the IAM policy of that tool's Lambda role, and
``tests/test_aws_access.py`` records every DynamoDB call a tool makes and checks it against the
same entry. So the policy is both sufficient (the tests pass) and minimal (nothing unused is
granted), and the engine's per-skill ``allowed_tools`` is mirrored by a per-tool IAM boundary.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Access:
    entity: str  # key of support_agent.aws.dynamo.TABLES
    action: str  # DynamoDB API action, e.g. "Query"
    index: str | None = None  # restrict to this GSI instead of the base table
    attributes: tuple[str, ...] | None = None  # restrict readable attributes (IAM FGAC)


# The purchases and tickets tools must turn an account ID or email into an account_id, but may
# not read the account itself: the email GSI is KEYS_ONLY, and GetItem on accounts is limited
# to the key attribute via dynamodb:Attributes.
_RESOLVE_ACCOUNT = (
    Access("accounts", "GetItem", attributes=("account_id",)),
    Access("accounts", "Query", index="by-email"),
)

TOOL_ACCESS: dict[str, tuple[Access, ...]] = {
    "get_account_status": (
        Access("accounts", "GetItem"),
        Access("accounts", "Query", index="by-email"),
    ),
    "get_purchase_history": (*_RESOLVE_ACCOUNT, Access("purchases", "Query")),
    "lookup_ticket": (
        *_RESOLVE_ACCOUNT,
        Access("tickets", "GetItem"),
        Access("tickets", "Query", index="by-account"),
    ),
    "search_kb": (Access("kb", "Scan"),),
    "get_service_status": (Access("service_status", "Scan"),),
}
