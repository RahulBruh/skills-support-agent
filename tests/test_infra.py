"""Synthesize the CDK stack offline and check the security-relevant parts of the template."""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("aws_cdk")

import aws_cdk as cdk  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "infra"))
from stack import SupportAgentStack  # noqa: E402

from support_agent.aws.access import TOOL_ACCESS  # noqa: E402


@pytest.fixture(scope="module")
def template() -> Template:
    app = cdk.App()
    return Template.from_stack(SupportAgentStack(app, "Test", prefix="t"))


def _policy_for(template: Template, tool: str) -> list[dict]:
    role_id = next(
        k
        for k, v in template.find_resources("AWS::IAM::Role").items()
        if v["Properties"].get("RoleName") == f"t-{tool.replace('_', '-')}"
    )
    policies = template.find_resources(
        "AWS::IAM::Policy", {"Properties": {"Roles": [{"Ref": role_id}]}}
    )
    return [s for p in policies.values() for s in p["Properties"]["PolicyDocument"]["Statement"]]


def test_one_function_per_tool(template):
    template.resource_count_is("AWS::Lambda::Function", len(TOOL_ACCESS))
    template.resource_count_is("AWS::DynamoDB::Table", 5)
    for tool in TOOL_ACCESS:
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {"Environment": {"Variables": Match.object_like({"TOOL": tool})}},
        )


def test_every_route_requires_iam_auth(template):
    routes = template.find_resources("AWS::ApiGatewayV2::Route")
    assert len(routes) == len(TOOL_ACCESS)
    assert all(r["Properties"]["AuthorizationType"] == "AWS_IAM" for r in routes.values())


def test_kb_role_can_only_scan_kb(template):
    dynamo = [
        s for s in _policy_for(template, "search_kb") if "dynamodb" in json.dumps(s["Action"])
    ]
    assert len(dynamo) == 1 and dynamo[0]["Action"] == "dynamodb:Scan"
    assert "Tablekb" in json.dumps(dynamo[0]["Resource"])


def test_purchases_role_reads_only_account_ids(template):
    statements = _policy_for(template, "get_purchase_history")
    text = json.dumps(statements)
    assert "Tablepurchases" in text and "Tabletickets" not in text and "Tablekb" not in text
    restricted = [s for s in statements if "Condition" in s]
    assert len(restricted) == 1
    assert restricted[0]["Action"] == "dynamodb:GetItem"
    assert restricted[0]["Condition"]["ForAllValues:StringEquals"] == {
        "dynamodb:Attributes": ["account_id"]
    }


def test_no_wildcard_dynamodb_actions(template):
    for tool in TOOL_ACCESS:
        for s in _policy_for(template, tool):
            actions = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
            assert not any(a in ("*", "dynamodb:*") for a in actions), tool
