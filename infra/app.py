import os

import aws_cdk as cdk
from ci_stack import CiStack
from stack import SupportAgentStack

app = cdk.App()
prefix = app.node.try_get_context("prefix") or "support-agent"
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

SupportAgentStack(
    app,
    "SupportAgent",
    prefix=prefix,
    alarm_email=app.node.try_get_context("alarm_email"),  # -c alarm_email=you@example.com
    env=env,
)
CiStack(
    app,
    "SupportAgentCi",
    prefix=prefix,
    # -c github_oidc_provider_arn=... if the account already has a GitHub OIDC provider
    existing_oidc_provider_arn=app.node.try_get_context("github_oidc_provider_arn"),
    env=env,
)
app.synth()
