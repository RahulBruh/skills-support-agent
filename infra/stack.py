"""CDK stack: DynamoDB tables, one Lambda + IAM role per tool, and an IAM-authorized HTTP API.

Tables come from ``support_agent.aws.dynamo.TABLES`` and each role's policy from
``support_agent.aws.access.TOOL_ACCESS``, so infrastructure and code cannot drift apart.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack, Tags
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk.aws_apigatewayv2_authorizers import HttpIamAuthorizer
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from constructs import Construct

from support_agent.aws.access import TOOL_ACCESS, Access
from support_agent.aws.dynamo import TABLES, table_name

SRC = Path(__file__).resolve().parents[1] / "src"


class SupportAgentStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, prefix: str = "support-agent", **kw):
        super().__init__(scope, cid, **kw)
        Tags.of(self).add("project", "skills-support-agent")
        self.prefix = prefix

        self.tables = {entity: self._table(entity) for entity in TABLES}

        code = lambda_.Code.from_asset(
            str(SRC), exclude=["**/__pycache__", "**/*.pyc", "*.egg-info"]
        )
        self.functions: dict[str, lambda_.Function] = {}
        for tool, access in TOOL_ACCESS.items():
            self.functions[tool] = self._tool_function(tool, access, code)

        self.api = self._api()

        # Attach this to whatever runs the agent (a user, a CI role) instead of admin rights.
        self.client_policy = iam.ManagedPolicy(
            self,
            "ToolsClientPolicy",
            description="Invoke the support-agent tool API (and nothing else).",
            statements=[
                iam.PolicyStatement(
                    actions=["execute-api:Invoke"],
                    resources=[self.api.arn_for_execute_api("POST", "/tools/*")],
                )
            ],
        )

        CfnOutput(self, "ApiUrl", value=self.api.api_endpoint)
        CfnOutput(self, "TablePrefix", value=prefix)
        CfnOutput(self, "ClientPolicyArn", value=self.client_policy.managed_policy_arn)

    # -- tables -------------------------------------------------------------------------------
    def _table(self, entity: str) -> ddb.Table:
        pk, sk, indexes = TABLES[entity]
        attr = lambda name: ddb.Attribute(name=name, type=ddb.AttributeType.STRING)  # noqa: E731
        table = ddb.Table(
            self,
            f"Table-{entity}",
            table_name=table_name(entity, self.prefix),
            partition_key=attr(pk),
            sort_key=attr(sk) if sk else None,
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,  # demo data, reseeded from data/
        )
        for name, (ipk, isk, projection) in indexes.items():
            table.add_global_secondary_index(
                index_name=name,
                partition_key=attr(ipk),
                sort_key=attr(isk) if isk else None,
                projection_type=ddb.ProjectionType[projection],
            )
        return table

    # -- tool functions -----------------------------------------------------------------------
    def _tool_function(self, tool: str, access: tuple[Access, ...], code) -> lambda_.Function:
        cid = tool.replace("_", "-")
        role = iam.Role(
            self,
            f"Role-{cid}",
            role_name=f"{self.prefix}-{cid}",
            description=f"Least-privilege role for the {tool} tool",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        for statement in self._statements(access):
            role.add_to_policy(statement)

        log_group = logs.LogGroup(
            self,
            f"Logs-{cid}",
            log_group_name=f"/aws/lambda/{self.prefix}-{cid}",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        log_group.grant_write(role)

        return lambda_.Function(
            self,
            f"Fn-{cid}",
            function_name=f"{self.prefix}-{cid}",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="support_agent.aws.lambdas.handler",
            code=code,
            role=role,
            log_group=log_group,
            memory_size=256,
            timeout=Duration.seconds(10),
            environment={"TOOL": tool, "SUPPORT_AGENT_TABLE_PREFIX": self.prefix},
        )

    def _statements(self, access: tuple[Access, ...]) -> list[iam.PolicyStatement]:
        """One statement per (resource, attribute restriction), merging actions."""
        grouped: dict[tuple, set[str]] = defaultdict(set)
        for a in access:
            arn = self.tables[a.entity].table_arn
            if a.index:
                arn = f"{arn}/index/{a.index}"
            grouped[(arn, a.attributes)].add(f"dynamodb:{a.action}")
        out = []
        for (arn, attributes), actions in grouped.items():
            conditions = None
            if attributes:
                conditions = {
                    "ForAllValues:StringEquals": {"dynamodb:Attributes": list(attributes)},
                    "StringEqualsIfExists": {"dynamodb:Select": "SPECIFIC_ATTRIBUTES"},
                }
            out.append(
                iam.PolicyStatement(actions=sorted(actions), resources=[arn], conditions=conditions)
            )
        return out

    # -- API ----------------------------------------------------------------------------------
    def _api(self) -> apigw.HttpApi:
        api = apigw.HttpApi(
            self,
            "ToolsApi",
            api_name=f"{self.prefix}-tools",
            description="Shared MCP tool services, one Lambda per tool. IAM (SigV4) auth.",
            default_authorizer=HttpIamAuthorizer(),
        )
        for tool, fn in self.functions.items():
            api.add_routes(
                path=f"/tools/{tool}",
                methods=[apigw.HttpMethod.POST],
                integration=HttpLambdaIntegration(f"Int-{tool.replace('_', '-')}", fn),
            )

        access_logs = logs.LogGroup(
            self,
            "ApiAccessLogs",
            log_group_name=f"/aws/apigateway/{self.prefix}-tools",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        stage: apigw.CfnStage = api.default_stage.node.default_child
        stage.default_route_settings = apigw.CfnStage.RouteSettingsProperty(
            throttling_burst_limit=20, throttling_rate_limit=10
        )
        stage.access_log_settings = apigw.CfnStage.AccessLogSettingsProperty(
            destination_arn=access_logs.log_group_arn,
            format=(
                '{"requestId":"$context.requestId","route":"$context.routeKey",'
                '"status":"$context.status","latencyMs":"$context.responseLatency",'
                '"integrationLatencyMs":"$context.integrationLatency",'
                '"caller":"$context.identity.userArn"}'
            ),
        )
        return api
