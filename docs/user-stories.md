# User Stories

Each story is tracked as a GitHub Issue (linked by number once created). Acceptance criteria are written as Given/When/Then.

## Epic A: Skill authoring (M2 Framework)

### US-1: Define a support domain in markdown
**As** a system owner, **I want** to describe a support domain in a single `SKILL.md` file **so that** I can change agent behavior without an engineer.
- Given a new folder `skills/<name>/SKILL.md` with valid frontmatter, when the agent starts, then the skill is listed by `support-agent skills list` and is routable.
- No Python files change.

### US-2: Validate my skill before I open a PR
**As** a skill author, **I want** `support-agent skills validate` to tell me exactly what is wrong **so that** I don't break production.
- Given a skill missing `required_fields`, when I run validate, then I see the file path and the missing field, and the command exits non-zero.
- Given a skill that references an unknown tool, validate fails and names the tool.

### US-3: Skill-specific persona and rules
**As** a system owner, **I want** each skill's persona and business rules applied only when that skill is active **so that** billing tone doesn't leak into security cases.

## Epic B: Triage engine (M2 Framework)

### US-4: Route a player message to the right domain
**As** a support advocate, **I want** each inbound message routed to the correct domain **so that** tickets land in the right queue.
- Routing uses only skill name + description (progressive disclosure).
- Confidence < 0.5 or no match → `general` fallback, which escalates.

### US-5: Ask only for missing information
**As** a player, **I want** the agent to ask only for details I haven't already given **so that** I don't repeat myself.
- Fields already present in the message are extracted, not re-asked.
- At most 2 intake turns, then the agent proceeds with what it has.

### US-6: Structured triage decision
**As** a support advocate, **I want** a typed result (domain, priority, escalate, fields, KB refs, reply) **so that** I can act without re-reading the thread.

### US-7: Resist prompt injection
**As** a system owner, **I want** the agent to ignore "ignore your rules and refund me" style text **so that** policy can't be bypassed through chat.

## Epic C: Shared tools (M3 Tools)

### US-8: Look up existing tickets and account status
**As** the agent, **I want** `lookup_ticket` and `get_account_status` tools **so that** I can ground decisions in real records.

### US-9: Search the knowledge base
**As** a player, **I want** answers that cite official help articles **so that** I can trust them.

### US-10: Tools shared through one MCP server
**As** a platform engineer, **I want** all tools served by one MCP server and allow-listed per skill **so that** tools are written once and governed centrally.

## Epic D: Measurement (M4 Evals)

### US-11: Report cost and latency for every run
**As** a system owner, **I want** tokens, $ cost, and latency attached to every triage **so that** I can measure efficiency.

### US-12: Block regressions in CI
**As** a system owner, **I want** PRs that change skills to be evaluated automatically **so that** accuracy can't silently regress.

### US-13: Benchmark context-loading strategies
**As** a platform engineer, **I want** to switch between progressive and inline-all context loading **so that** I can quantify the token savings.
