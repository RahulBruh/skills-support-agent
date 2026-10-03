# Playbook: Adding a Support Domain (Skill)

**Audience:** system owners and support SMEs. No Python required.
**Time:** about 15–30 minutes, plus an eval run.

## 1. Decide whether it's a new skill

Create a new skill when the domain has its **own intake checklist, escalation policy, or tone**. If it's only a new rule for an existing domain (for example a new refund exception), edit that skill's file instead.

## 2. Create the folder and file

```
skills/
  <your-skill-name>/      # lowercase-kebab-case; must match `name:` below
    SKILL.md
```

## 3. Fill in the frontmatter

```yaml
---
name: connectivity
description: >-            # The ONLY text the router sees. List concrete symptoms players
  Disconnects, lag, ...    # actually type. Keep it under ~300 characters.
persona: One sentence on voice and attitude.
required_fields: [game, platform, region]        # snake_case
intake_questions:                                 # one question per required field
  game: Which game is this in?
  platform: Which platform are you playing on?
  region: Which region or server are you connecting to?
allowed_tools: [get_service_status, search_kb]   # allow-list; see table below
escalation_rules:
  - <condition> → escalate.
priority_rules:            # all four are required
  P1: ...
  P2: ...
  P3: ...
  P4: ...
---
```

| Tool | Use it for |
|---|---|
| `get_account_status` | Account state, security flags, 2FA, suspensions |
| `get_purchase_history` | Orders, amounts, delivery and usage flags |
| `lookup_ticket` | Existing tickets by ID or account |
| `search_kb` | Help-center articles to cite |
| `get_service_status` | Outages and known issues per game/platform |

## 4. Write the body (business rules)

- Use short, imperative bullets. Every sentence costs tokens on every conversation that uses this skill.
- Make each rule **decidable**. "Escalate big refunds" isn't decidable; "Refund request over $100 → escalate" is.
- Give exactly one right answer for each priority. If two priorities could both apply, the eval cases will expose it.
- Cite KB article IDs the agent should share.

## 5. Validate locally

```bash
uv run support-agent skills validate
uv run support-agent skills list
```

Validation catches unknown tools, required fields without a question, a name that doesn't match the folder, a missing priority level, and bad YAML. (Watch for `key: value: more` in an unquoted string; wrap it in quotes.)

## 6. Try it

```bash
uv run support-agent chat
uv run support-agent run "my game keeps disconnecting in EU" --followup "Velocity Kart, PC, EU"
```

## 7. Add eval cases and open a PR

Add 5–10 labeled cases to [`agent-eval-harness/datasets/triage_cases.yaml`](https://github.com/RahulBruh/agent-eval-harness/blob/main/datasets/triage_cases.yaml), tagged with your domain, including at least one hard case and one `smoke` case. When you open the PR, the **Evals** workflow runs the smoke set and blocks the merge if accuracy drops or token use grows beyond tolerance.

## Checklist

- [ ] Folder name equals `name:`
- [ ] Description lists the symptoms players type, without overlapping other skills
- [ ] Every required field has an intake question
- [ ] Every escalation and priority rule is decidable
- [ ] `skills validate` passes
- [ ] Eval cases added; Evals workflow green
