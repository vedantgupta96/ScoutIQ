## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Model split

For plain-language “pick up the next card”, follow `docs/agents/issue-tracker.md`; local `/next` executes that workflow.

Use the project-scoped Codex `implementer` agent for hands-on code changes after the main thread has finished planning and written a precise specification.

Rules:
- The main thread owns exploration, ideation, product and design decisions, architecture, specifications, diff review, browser and accessibility review, final verification, and user communication.
- Delegate implementation to exactly one `implementer` agent at a time. Do not fan out parallel writing agents unless the user explicitly requests parallel implementation.
- Give the implementer a bounded specification with the file list, exact requested changes, constraints, and verification commands. Ambiguities return to the main thread for a decision.
- Keep follow-up fixes with the same implementer when practical so it can reuse context.
- The main thread reviews the resulting diff before accepting the work and owns commits, pushes, and pull requests.
