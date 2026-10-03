# Workflow Map

## Current state (manual triage)

```mermaid
flowchart LR
    P[Player submits contact] --> Q[Generic queue]
    Q --> A1[Tier-1 advocate reads message]
    A1 --> A2{Which domain?}
    A2 --> A3[Asks player for missing info<br/>often multiple round trips]
    A3 --> A4[Searches KB / ticket history manually]
    A4 --> A5{Resolve or escalate?}
    A5 -->|resolve| R[Reply to player]
    A5 -->|escalate| T2[Tier-2 / Security queue]
```

Pain points: domain knowledge lives in people's heads and wikis, intake is inconsistent, and the time to first meaningful response is long.

## Future state (skills-driven agent)

```mermaid
flowchart TD
    M[Player message] --> R[Router<br/><i>sees only skill names + descriptions</i>]
    R -->|confidence ≥ 0.5| L[Load selected SKILL.md body]
    R -->|no match / low confidence| G[general fallback → escalate]
    L --> I{Required fields<br/>present?}
    I -->|missing & turns < 2| Ask[Ask intake question] --> Player([Player reply]) --> I
    I -->|complete or turns exhausted| Act[Act: call allowed MCP tools]
    Act --> D[Decide: priority, escalate, KB refs, reply]
    G --> D
    D --> Out[[TriageResult + usage + latency]]

    subgraph MCP["MCP server (shared)"]
        T1[lookup_ticket]
        T2[get_account_status]
        T3[search_kb]
    end
    Act -.-> MCP

    subgraph Skills["skills/ (declarative)"]
        S1[billing/SKILL.md]
        S2[account-recovery/SKILL.md]
        S3[bug-report/SKILL.md]
        S4[connectivity/SKILL.md]
    end
    Skills -.-> R
    Skills -.-> L
```

## Change-management flow (skill authoring)

```mermaid
flowchart LR
    E[Author edits SKILL.md] --> V[support-agent skills validate]
    V --> PR[Open PR]
    PR --> CI[CI: lint + unit tests]
    PR --> EV[evals.yml: run eval smoke set]
    EV --> Gate{Accuracy ≥ baseline − tolerance?}
    Gate -->|yes| Merge[Merge]
    Gate -->|no| Fix[Fix skill / update cases]
    Fix --> E
```
