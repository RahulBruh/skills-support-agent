# Design Decisions

Short ADR-style records (architecture decision records) of the choices that shape the framework.

## ADR-1: Skills are markdown files with YAML frontmatter

**Context.** Support SMEs own policy but don't write Python.
**Decision.** Each domain is a `SKILL.md`. Structured config (fields, tools, rules) goes in the frontmatter; free-form policy goes in the markdown body. A pydantic schema validates both.
**Consequence.** A new domain is a folder, not a deploy. The schema keeps "declarative" from turning into "anything goes".

## ADR-2: Progressive disclosure for context

**Context.** Putting every skill in every prompt makes cost grow linearly with the number of domains.
**Decision.** The router sees only `name` + `description`. Later nodes load only the active skill's rules.
**Consequence.** Prompt size stays roughly flat as skills are added. Descriptions become load-bearing, so the playbook says how to write them. The `inline_all` mode is kept as a benchmark baseline.

## ADR-3: Deterministic intake questions

**Context.** Letting the LLM phrase follow-up questions costs output tokens and makes behaviour drift.
**Decision.** The LLM only *extracts* fields. Missing fields are asked with the skill's own `intake_questions`, verbatim.
**Consequence.** SMEs control exact wording; intake costs one extraction call per turn.

## ADR-4: Tools via one MCP server, allow-listed per skill

**Context.** Every domain needs a subset of the same back-office lookups.
**Decision.** One FastMCP stdio server exposes all tools. Each skill's `allowed_tools` filters what the model sees, and the engine rejects calls to tools outside that list.
**Consequence.** Tools are written once. Any MCP client can reuse the server.

## ADR-5: Agent recommends, humans act

**Decision.** No tool mutates state (refunds, unbans, password resets). The output is a `TriageResult` for a human queue.
**Consequence.** Lower risk while accuracy is being established. Write tools can be added later behind an approval step.

## ADR-6: Evaluation lives in a separate repo

**Decision.** [`agent-eval-harness`](https://github.com/RahulBruh/agent-eval-harness) imports the agent as a package and benchmarks any configuration (model × skill set × context mode).
**Consequence.** The harness can compare variants the agent repo doesn't ship. This repo's PR workflow pulls in the harness to gate changes.

## ADR-7: DynamoDB with one table per entity, keyed by access pattern

**Context.** The tools need durable, managed storage instead of JSON files, and each tool reads a different slice of player data. The usual DynamoDB advice is single-table design.
**Decision.** Five tables (`accounts`, `purchases`, `tickets`, `kb`, `service_status`). Keys are chosen per access pattern: purchases use `account_id` + `<date>#<order_id>` so one query returns an account's orders newest-first; tickets have a `by-account` GSI; accounts have a `KEYS_ONLY` `by-email` GSI so email lookups never project account data. The spec lives in `support_agent/aws/dynamo.py` (`TABLES`) and the CDK stack, seed command and tests all build from it.
**Why not single-table.** IAM can restrict a role to partition keys (`dynamodb:LeadingKeys`) but not to sort-key prefixes, so in one table the account-status role could also read purchases. Separate tables make the per-tool IAM boundary exact, which is worth more here than saving a round trip on joins the tools never do.
**Consequence.** `search_kb` and the status overview are scans; fine for tens of items, and the place to swap in OpenSearch or a Bedrock knowledge base if the KB grows. `JsonBackend` stays the default, so tests and the eval gate need no AWS access; a moto test asserts `DynamoBackend` returns the same answers for every tool.

## ADR-8: Tools as separate Lambdas, with IAM mirroring the skill allow-lists

**Context.** ADR-4 restricts which tools each *skill* can call, but that check lives inside the engine. A bug or a prompt injection that gets past it would still reach every table.
**Decision.** Each tool is its own Lambda behind an IAM-authorized HTTP API, with its own role. Roles are generated from `support_agent/aws/access.py`. Tools that only need to resolve an email or ID to `account_id` (purchases, tickets) get `GetItem` on accounts restricted to that one attribute (`dynamodb:Attributes`), plus the `KEYS_ONLY` email index. The MCP server stays the protocol layer: `--backend api` makes it proxy each call over SigV4.
**Consequence.** Defense in depth. The engine decides which tools a skill may call, and IAM decides what data each tool can touch. A test records every DynamoDB call under moto and fails if any call falls outside its tool's policy *or* if a grant goes unused, so the policies cannot silently widen. The cost is one cold start per tool, and an extra network hop compared to the in-process `dynamodb` backend, which is kept for local use.

## ADR-9: Bedrock as a provider switch, not a second code path

**Context.** Running Claude through Amazon Bedrock keeps inference inside the AWS account: IAM auth instead of an API key, and CloudTrail and billing alongside the tools.
**Decision.** `--provider bedrock` swaps the SDK client inside the existing LangChain `ChatAnthropic` for the official `AnthropicBedrockMantle` client (the Messages API on Bedrock). Model IDs map to `anthropic.<model>`. The graph, tool binding, structured output and usage accounting are untouched.
**Consequence.** The same eval cases can benchmark both providers by changing a single config value. Bedrock is priced by AWS, so costs reported for Bedrock runs use first-party rates and are labeled as an estimate.

## ADR-10: CI reaches AWS through OIDC, and eval results become time series

**Context.** The PR gate catches large regressions on a single run. It cannot show slow drift, and long-lived AWS keys in GitHub secrets are a standing liability.
**Decision.** GitHub Actions assumes a role through GitHub's OIDC provider. The trust policy pins exact `sub` claims (harness `main`; this repo's PRs and `main`), and the role can only write under `runs/` in one bucket and publish to one metrics namespace. Every eval run, pass or fail, is uploaded to S3 and pushed to CloudWatch (`AgentEvals`) per variant. A dashboard plots accuracy, cost, tokens and latency over 90 days.
**Consequence.** No AWS secrets exist anywhere. Regressions show up as a trend before they trip the gate's tolerance, and a full report for every historical run stays in S3. The same role can later run the gate's evals on Bedrock, which would remove the Anthropic API key secret too.
