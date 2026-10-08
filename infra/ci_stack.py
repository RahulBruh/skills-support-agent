"""CI stack: GitHub Actions -> AWS through OIDC (no stored keys), eval results in S3, and an
eval-trends dashboard.

The role trusts only the two repos' eval workflows: manual runs on the harness's main branch,
and pull-request or manual main-branch runs in this repo. It may write under ``runs/`` in the results bucket and
publish metrics to the ``AgentEvals`` namespace, and nothing else.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct

GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
EVALS_NAMESPACE = "AgentEvals"  # mirrors evalh.publish.NAMESPACE in the harness repo

# GitHub OIDC subjects allowed to assume the role.
DEFAULT_SUBJECTS = (
    "repo:RahulBruh/agent-eval-harness:ref:refs/heads/main",  # manual eval runs
    "repo:RahulBruh/skills-support-agent:pull_request",  # the PR eval gate
    "repo:RahulBruh/skills-support-agent:ref:refs/heads/main",  # manual gate runs
)


class CiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        prefix: str = "support-agent",
        subjects: tuple[str, ...] = DEFAULT_SUBJECTS,
        existing_oidc_provider_arn: str | None = None,
        **kw,
    ):
        super().__init__(scope, cid, **kw)

        # An account can hold only one provider per URL; reuse it if one already exists.
        if existing_oidc_provider_arn:
            provider = iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
                self, "GitHubOidc", existing_oidc_provider_arn
            )
        else:
            provider = iam.OpenIdConnectProvider(
                self, "GitHubOidc", url=GITHUB_OIDC_URL, client_ids=["sts.amazonaws.com"]
            )

        self.bucket = s3.Bucket(
            self,
            "EvalResults",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,  # eval history outlives the stack
        )

        self.role = iam.Role(
            self,
            "GitHubEvalsRole",
            role_name=f"{prefix}-github-evals",
            description="Assumed by GitHub Actions eval workflows via OIDC.",
            max_session_duration=Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(
                provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                    },
                    "StringLike": {"token.actions.githubusercontent.com:sub": list(subjects)},
                },
            ),
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject"], resources=[self.bucket.arn_for_objects("runs/*")]
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],  # no resource ARNs for PutMetricData; scoped by namespace
                conditions={"StringEquals": {"cloudwatch:namespace": EVALS_NAMESPACE}},
            )
        )

        self.dashboard = self._dashboard(prefix)

        CfnOutput(self, "EvalRoleArn", value=self.role.role_arn)
        CfnOutput(self, "ResultsBucket", value=self.bucket.bucket_name)

    def _dashboard(self, prefix: str) -> cw.Dashboard:
        def trend(title: str, metric: str, stat: str = "Average", unit: str = "") -> cw.GraphWidget:
            # SEARCH picks up every Variant ever published, so new variants need no redeploy.
            expr = cw.MathExpression(
                expression=(
                    f"SEARCH('{{{EVALS_NAMESPACE},Variant}} MetricName=\"{metric}\"', "
                    f"'{stat}', 86400)"
                ),
                using_metrics={},
                label="",
                period=Duration.days(1),
            )
            return cw.GraphWidget(
                title=title,
                left=[expr],
                width=12,
                height=6,
                left_y_axis=cw.YAxisProps(label=unit, show_units=False),
            )

        d = cw.Dashboard(
            self,
            "EvalsDashboard",
            dashboard_name=f"{prefix}-evals",
            default_interval=Duration.days(90),
        )
        d.add_widgets(
            cw.TextWidget(
                markdown="# Agent evals over time\nOne line per variant, daily average of every "
                "published run (namespace `AgentEvals`). A drift here shows up before the PR "
                "gate's tolerance trips.",
                width=24,
                height=2,
            )
        )
        d.add_widgets(
            trend("Decision accuracy (%)", "Accuracy", unit="%"),
            trend("Cost per task (USD)", "CostPerTaskUSD", unit="USD"),
        )
        d.add_widgets(
            trend("Tokens per task", "TokensPerTask"),
            trend("p50 latency (s)", "LatencyP50", unit="s"),
        )
        return d
