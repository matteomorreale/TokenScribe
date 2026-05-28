# TokenScribe

Scientific platform for studying LLM token efficiency across languages and writing systems.
Measures SFS, LER, PEI, and MAGI Selection Scores (Phase 1 + Phase 2 LLM judge panel)
to isolate tokenizer behavior from translation artifacts.

**Stack:** Python 3.11, Flask, SQLite, Jinja2, Vanilla JS
**Author:** Matteo Morreale

## Language

All UI text, labels, tooltips, messages, and interface copy must be in **English only**.
No Italian strings in templates, JS, or Python views — if you find any, treat them as a bug and fix them.

For architecture and modules see:

- agents/agent.md
- agents/architecture.md
- agents/datastructure.md
- agents/api.md
- agents/task.md
