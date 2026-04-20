# Agents Documentation — Info

This directory contains structured documentation for AI agents working on TokenScribe.
Files are designed to minimize token usage while maximizing contextual accuracy.

## Agent Reading Order

1. `claude.md` — ultra-brief project orientation
2. `agent.md` — stable reusable context (architecture, conventions)
3. `architecture.md` — folder map and module responsibilities
4. `datastructure.md` — DB schema and data relationships
5. `api.md` — internal route/API contracts
6. `task.md` — current task tracker
7. Open codebase files only when strictly necessary

## log_history

Located at `agents/log_history/YYYY/MM/DD/HH-MM-SS_issue.md`.
Do NOT include in base context. Consult only when:
- A bug emerges
- A known error recurs
- Investigating a regression

Each log file follows this structure:
- problem
- context
- attempted solutions
- final solution
- lessons learned
