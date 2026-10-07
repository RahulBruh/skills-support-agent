import os

import aws_cdk as cdk
from stack import SupportAgentStack

app = cdk.App()
SupportAgentStack(
    app,
    "SupportAgent",
    prefix=app.node.try_get_context("prefix") or "support-agent",
    alarm_email=app.node.try_get_context("alarm_email"),  # -c alarm_email=you@example.com
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
)
app.synth()
