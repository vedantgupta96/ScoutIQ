# Triage labels

| Label | Meaning |
|---|---|
| `needs-triage` | Maintainer evaluation required |
| `needs-info` | Exact information required before work can continue |
| `ready-for-agent` | Fully specified and eligible for an agent |
| `ready-for-human` | Requires human implementation or decision |
| `wontfix` | Will not be actioned |

Cards waiting only on a native prerequisite may remain Backlog with `ready-for-agent`; they become eligible after the dependency recheck. Remove `ready-for-agent` for human or information blockage and apply the corresponding label. Cards with any other label in this table, except `ready-for-agent`, are ineligible for automatic pickup. `wayfinder:map` is never an executable pickup card.

Use native Linear blockers rather than prose alone. A blocked card moves to Backlog with an exact comment and either `needs-info` or `ready-for-human`; it returns to Todo only after that need is resolved.
