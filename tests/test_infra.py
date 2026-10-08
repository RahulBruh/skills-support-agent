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


def test_alarms_per_skill_and_per_tool(template):
    from support_agent.paths import default_skills_dir
    from support_agent.skills import load_skills

    names = {
        a["Properties"]["AlarmName"]
        for a in template.find_resources("AWS::CloudWatch::Alarm").values()
    }
    for skill in load_skills(default_skills_dir()):
        assert {f"t-{skill}-error-rate", f"t-{skill}-latency-p90"} <= names
    for tool in TOOL_ACCESS:
        assert f"t-tool-{tool}-errors" in names
    assert "t-api-5xx" in names
    template.resource_count_is("AWS::CloudWatch::Dashboard", 1)


def test_client_policy_metrics_scoped_to_namespace(template):
    policy = next(iter(template.find_resources("AWS::IAM::ManagedPolicy").values()))
    statements = policy["Properties"]["PolicyDocument"]["Statement"]
    put = next(s for s in statements if s["Action"] == "cloudwatch:PutMetricData")
    assert put["Condition"] == {"StringEquals": {"cloudwatch:namespace": "SupportAgent"}}


@pytest.fixture(scope="module")
def ci_template() -> Template:
    from ci_stack import CiStack

    return Template.from_stack(CiStack(cdk.App(), "TestCi", prefix="t"))


def test_ci_role_trusts_only_the_eval_workflows(ci_template):
    roles = ci_template.find_resources(
        "AWS::IAM::Role", {"Properties": {"RoleName": "t-github-evals"}}
    )
    role = next(iter(roles.values()))
    stmt = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
    assert stmt["Action"] == "sts:AssumeRoleWithWebIdentity"
    cond = stmt["Condition"]
    assert cond["StringEquals"] == {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"}
    subs = cond["StringLike"]["token.actions.githubusercontent.com:sub"]
    assert subs == [
        "repo:RahulBruh/agent-eval-harness:ref:refs/heads/main",
        "repo:RahulBruh/skills-support-agent:pull_request",
        "repo:RahulBruh/skills-support-agent:ref:refs/heads/main",
    ]


def test_ci_role_can_only_write_results_and_eval_metrics(ci_template):
    role_id = next(
        iter(
            ci_template.find_resources(
                "AWS::IAM::Role", {"Properties": {"RoleName": "t-github-evals"}}
            )
        )
    )
    policies = ci_template.find_resources(
        "AWS::IAM::Policy", {"Properties": {"Roles": [{"Ref": role_id}]}}
    )
    statements = [
        s for p in policies.values() for s in p["Properties"]["PolicyDocument"]["Statement"]
    ]
    assert sorted(s["Action"] for s in statements) == ["cloudwatch:PutMetricData", "s3:PutObject"]
    put = next(s for s in statements if s["Action"] == "s3:PutObject")
    assert "/runs/*" in json.dumps(put["Resource"])


def test_results_bucket_is_private_and_tls_only(ci_template):
    ci_template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )
    policy = next(iter(ci_template.find_resources("AWS::S3::BucketPolicy").values()))
    deny = policy["Properties"]["PolicyDocument"]["Statement"][0]
    assert deny["Effect"] == "Deny" and deny["Condition"]["Bool"]["aws:SecureTransport"] == "false"
