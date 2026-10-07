# AWS deployment

One CDK stack (`stack.py`) deploys the tool services:

```mermaid
flowchart LR
    A[agent / MCP server<br/><i>--backend api</i>] -- SigV4 --> G[API Gateway HTTP API<br/><i>IAM auth, throttled</i>]
    G -- POST /tools/lookup_ticket --> L1[λ lookup_ticket] --> T1[(tickets)] & AC[(accounts<br/>key only)]
    G -- POST /tools/get_account_status --> L2[λ get_account_status] --> AC2[(accounts)]
    G -- POST /tools/get_purchase_history --> L3[λ get_purchase_history] --> P[(purchases)] & AC
    G -- POST /tools/search_kb --> L4[λ search_kb] --> K[(kb)]
    G -- POST /tools/get_service_status --> L5[λ get_service_status] --> S[(service_status)]
```

- **DynamoDB:** five on-demand tables, one per entity, keyed by access pattern ([ADR-7](../docs/decisions.md)).
- **Lambda:** one function per tool, all built from the same package code. `TOOL` picks the tool, and each function has **its own IAM role** generated from [`access.py`](../src/support_agent/aws/access.py) ([ADR-8](../docs/decisions.md)).
- **API Gateway:** an HTTP API whose routes use the IAM authorizer. The `ClientPolicyArn` output grants `execute-api:Invoke` on these routes and nothing else.

## Deploy

Prerequisites: the AWS CLI with credentials (`aws sts get-caller-identity` works), Node 18+ and uv.

```bash
cd infra
npx aws-cdk@2 bootstrap          # once per account/region
npx aws-cdk@2 deploy             # prints ApiUrl, TablePrefix, ClientPolicyArn
cd ..
uv run --extra aws support-agent aws seed    # load data/ into the tables
```

Then run the agent against the deployed tools:

```bash
export SUPPORT_AGENT_API_URL=<ApiUrl output>
uv run --extra aws support-agent run --backend api "I was charged twice for 1000 Shards..."
uv run --extra aws support-agent run --backend dynamodb "..."   # direct to DynamoDB, no Lambdas
```

## Cost

Everything is pay-per-request with no idle cost apart from CloudWatch log storage. At demo volumes (a few hundred tool calls a day) the stack stays inside the free tier.

## Tear down

```bash
cd infra && npx aws-cdk@2 destroy   # tables and log groups are deleted too (demo data)
```

## Tests

`tests/test_infra.py` synthesizes the stack offline and asserts the security properties: a function per tool, IAM auth on every route, no wildcard DynamoDB actions, and attribute-restricted account reads. `tests/test_aws_access.py` records every DynamoDB call each tool makes under moto and checks each one against that tool's policy, in both directions.
