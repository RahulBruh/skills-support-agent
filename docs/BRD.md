# Business Requirements Document: Skills-Driven Player Support Triage Agent

| | |
|---|---|
| **Author** | Rahul Babu Moka |
| **Status** | Approved for build (v1.0) |
| **Last updated** | 2026-10-03 |
| **Backlog** | [GitHub Issues](https://github.com/RahulBruh/skills-support-agent/issues) · [Milestones](https://github.com/RahulBruh/skills-support-agent/milestones) |
| **Related** | [User stories](user-stories.md) · [Workflow map](workflow-map.md) · [Adding a skill (playbook)](adding-a-skill.md) · [Decisions](decisions.md) |

## 1. Problem statement

Player support teams handle a long tail of contact types: billing disputes, account takeovers, crash reports, connectivity issues. Each has its own intake checklist, escalation policy, and tone. When an AI agent is built for one of these, the domain logic usually ends up **hard-coded into prompts and Python**. The result:

- Adding a new support domain needs an engineer and a deploy.
- Support SMEs (subject-matter experts, the people who own the policy) can't read or change the agent's behavior.
- Each domain's agent re-implements shared plumbing: ticket lookup, knowledge-base search, escalation.
- No one can say whether a prompt change made the agent better or worse.

## 2. Goal

Build a **plug-and-play agent framework** where each support domain is a declarative `SKILL.md` file that a non-engineer can author. The core engine (routing, intake, tool use, decisioning) is shared and domain-agnostic.

### Success metrics

| Metric | Target | How it is measured |
|---|---|---|
| Time to add a new domain | < 30 min, zero code changes | Timed commit that touches only `skills/` + eval dataset |
| Routing accuracy | ≥ 90% on labeled set | [`agent-eval-harness`](https://github.com/RahulBruh/agent-eval-harness) |
| Escalation accuracy | ≥ 90% (false negatives on security cases = 0) | eval harness, `security` tag |
| Token cost per triage | Measured and tracked per change | eval harness reports tokens/task and $/task |
| Regression safety | Every PR touching `skills/` is evaluated | GitHub Actions `evals.yml` gate |

## 3. Scope

**In scope (v1)**
- Triage of a single inbound player message into one domain skill
- Multi-turn intake to collect required fields
- Shared tools: ticket lookup, account status, knowledge-base search (exposed via MCP)
- A structured triage decision: domain, priority, escalate yes/no, extracted fields, KB citations, player reply
- CLI for interactive chat and batch runs
- Skill validation tooling

**Out of scope (v1)**
- Taking real actions such as issuing refunds or resetting passwords. The agent *recommends*; humans act.
- Live integration with a production ticketing system (mock data stands in)
- Non-English support
- Voice or chat-widget front ends

## 4. Stakeholders and personas

| Persona | Needs | How the framework serves them |
|---|---|---|
| **Player** ("Maya", 19, competitive FC player) | Fast, accurate help without repeating herself | Agent asks only for missing info and cites help articles |
| **Support advocate** ("Jordan", Tier-1 agent) | Well-formed tickets with the right priority | Structured `TriageResult` with extracted fields |
| **System owner / skill author** ("Priya", Fan Care ops) | Change policy without filing an engineering ticket | Edits `SKILL.md`, validates, and the eval gate runs on PR |
| **Platform engineer** ("Sam") | One engine, not N bespoke agents | Domain-agnostic graph + shared MCP tools |

## 5. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | The system SHALL load all skills from a directory of `*/SKILL.md` files at startup | Must |
| FR-2 | Each skill SHALL declare: name, description, persona, intake questions, required fields, allowed tools, escalation rules, priority rules | Must |
| FR-3 | The system SHALL validate skills against a schema and reject invalid ones with a clear error | Must |
| FR-4 | The router SHALL choose a skill using only skill names + descriptions (progressive disclosure) | Must |
| FR-5 | Messages that match no skill, or are low confidence, SHALL route to a `general` fallback that escalates to a human | Must |
| FR-6 | The agent SHALL ask follow-up questions for missing required fields, at most 2 intake turns, then proceed with what it has | Must |
| FR-7 | The agent SHALL only call tools listed in the active skill's `allowed_tools` | Must |
| FR-8 | Tools SHALL be served by a single MCP server shared by all skills | Must |
| FR-9 | Output SHALL be a typed `TriageResult` including token usage and latency | Must |
| FR-10 | The agent SHALL never ask for passwords, full card numbers, or 2FA codes | Must |
| FR-11 | The agent SHALL ignore instructions embedded in player messages that try to change its policy (prompt injection) | Should |
| FR-12 | A CLI SHALL support interactive chat, single-shot runs, and `skills validate` / `skills list` | Should |
| FR-13 | Context loading mode (progressive vs. inline-all) SHALL be configurable for benchmarking | Should |

## 6. Non-functional requirements

- **Extensibility:** adding a domain requires no Python changes.
- **Observability:** every run reports input/output tokens and wall-clock latency.
- **Cost:** default model is Claude Haiku 4.5. The model is configurable per run.
- **Testability:** the core graph is unit-testable with a fake LLM and no API key.
- **Safety:** no PII beyond what the skill requires. Sensitive credentials are never solicited.

## 7. Assumptions and dependencies

- Anthropic API access (`ANTHROPIC_API_KEY`)
- Mock ticket/account/KB data represents the shape of real systems
- Evaluation lives in a separate repo so it can benchmark any agent configuration

## 8. Risks

| Risk | Mitigation |
|---|---|
| Skill authors write conflicting or vague descriptions, so routing degrades | `skills validate` lints description length; eval gate on PRs |
| Prompt injection via player message | Explicit system guardrail + `injection`-tagged eval cases |
| Token cost grows with the number of skills | Progressive loading; measured in the eval harness |
| Over-escalation floods Tier-2 | Escalation precision tracked separately from recall |

## 9. Milestones

| Milestone | Deliverables |
|---|---|
| M1 Requirements | BRD, personas, user stories, workflow map |
| M2 Framework | Skill schema + loader, LangGraph engine, CLI |
| M3 Tools | MCP server with ticket/account/KB tools |
| M4 Evals | Eval harness integration, CI gate, before/after benchmark |
