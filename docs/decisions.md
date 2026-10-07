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
