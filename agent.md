# TokenScribe — Agent Context

## Project Summary
TokenScribe is a scientific research platform for studying how language and writing systems
affect token usage in Large Language Model APIs. It measures SFS and PEI metrics to ensure
that token differences are attributable to language/tokenizer behavior, not translation artifacts.

## Main Architecture
MVC pattern. Flask MPA (Multi-Page Application) with Jinja2 templates.
SQLite database accessed via raw SQL through a DatabaseManager class.
Services layer handles business logic; Controllers handle HTTP routing.

## Main Technologies
- Python 3.11 + Flask 3.x
- SQLite (via sqlite3 stdlib)
- Jinja2 (Flask built-in templating)
- Vanilla JS + modern CSS (no Bootstrap, no heavy frameworks)
- sentence-transformers (local embeddings for SFS computation)
- tiktoken (neutral tokenizer for PEI)

## Core Modules
- **StudyController** — CRUD for studies
- **PromptController** — prompt management and template enforcement
- **TranslationController** — candidate management, scoring, approval
- **ExperimentController** — run experiments via LLM APIs, store results
- **SettingsController** — API keys, model configuration
- **ReportController** — export dataset, visualizations
- **LLMService** — unified interface to all providers
- **ScoringService** — SFS (DSF + RTF) and PEI computation
- **DatabaseManager** — SQLite connection and schema bootstrap

## Development Conventions
- Author: Matteo Morreale
- No references to "manus" in class/object/variable names
- All class names prefixed with project domain (e.g. TokenScribe*, Study*, Prompt*)
- Routes: /studies, /prompts, /translations, /experiments, /settings, /reports
- All experiment runs are immutable (no UPDATE on token_results)
- Prompt template: [Instruction] <<< [Input] >>> [Expected Output]

## Documentation Map
- agents/architecture.md — folder structure and module responsibilities
- agents/datastructure.md — DB schema and relationships
- agents/api.md — internal API contracts
- agents/task.md — task tracker
- agents/log_history/ — bug/regression logs (consult only when needed)
