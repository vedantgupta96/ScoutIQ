# Domain Docs

ScoutIQ uses a single-context domain-documentation layout.

## Before exploring

Read:

- `CONTEXT.md` at the repository root.
- Relevant decisions under `docs/adr/`.

If either is absent, proceed silently. Domain documentation is created or expanded only when terminology or architectural decisions are resolved.

## File structure

```text
/
├── CONTEXT.md
└── docs/
    └── adr/
```

## Use the glossary’s vocabulary

When naming a domain concept in an issue, specification, proposal, test, or implementation, use the term defined in `CONTEXT.md`.

Do not substitute terms the glossary explicitly rejects. If a necessary concept is missing, reconsider whether existing vocabulary covers it or note the gap for domain modeling.

## Flag ADR conflicts

If proposed work contradicts an existing ADR, surface the conflict explicitly instead of silently overriding the decision.
