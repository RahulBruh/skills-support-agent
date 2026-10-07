import os

import aws_cdk as cdk
from stack import SupportAgentStack

app = cdk.App()
SupportAgentStack(
    app,
    "SupportAgent",
    prefix=app.node.try_get_context("prefix") or "support-agent",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
)
app.synth()
