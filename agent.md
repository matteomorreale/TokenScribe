# TokenScribe — Agent Context

## Project Summary

TokenScribe is a scientific research platform for studying how language and writing systems
affect token usage in Large Language Model APIs. It measures SFS, LER, PEI, and MAGI
Selection Scores to ensure that token differences are attributable to language/tokenizer
behavior, not translation artifacts.

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
- tiktoken cl100k_base (neutral tokenizer for PEI and visible_output_tokens)

## Core Modules

- **StudyController** — CRUD for studies
- **PromptController** — prompt management and template enforcement
- **TranslationController** — candidate management, scoring (SFS + LER), approval, MAGI scores
- **ExperimentController** — run experiments via LLM APIs, store token results
- **SettingsController** — API keys, model configuration
- **ReportController** — export dataset, score visualizations
- **LLMService** — unified interface to all providers (7 total)
- **ScoringService** — SFS (DSF+RTF), LER, PEI, MAGI Selection Score computation
- **ExportService** — CSV and JSON export with full metric enrichment
- **DatabaseManager** — SQLite connection, schema bootstrap, and migrations

## Scoring Metrics (in pipeline order)

### SFS — Semantic Fidelity Score

`SFS = 0.7 * DSF + 0.3 * RTF`
DSF = cosine similarity(original, translation); RTF = cosine similarity(original, back-translation).
Stored per translation_candidate in `translation_scores`.

### LER — Length Expansion Ratio

`ler_char = len(translation) / len(original)` (characters)
`ler_token = tiktoken_count(translation) / tiktoken_count(original)`
Expected range: ~1.0–1.3. Stored in `translation_scores` alongside SFS.

### PEI — Prompt Equivalence Index

`PEI = mean(CV_char, CV_word, CV_token)` across all approved translations for a prompt.
CV = stdev/mean. Lower is better (less variance = fairer comparison across languages).
Bands: < 0.20 ottimo, ≤ 0.35 plausibile, > 0.35 alto.
Stored in `pei_results` and `pei_group_results` per experiment run.

### MAGI Selection Score (Phase 1)

`score_absolute = SFS − λ·PEI − ν·|LER_char − 1|`
λ = 0.5 (derived: range_SFS / range_PEI = 0.10 / 0.20), ν = 0.5
Rank candidates by score_absolute descending; `score_rank_pct = 1 − (rank−1)/(n−1)`.
`magi_required = rank > max(1, ⌊n/4⌋)` — flags candidates needing LLM panel (Phase 2).
Stored in `selection_score_results`.

### Token Efficiency Metrics (experiment runs)

- `visible_output_tokens` — tiktoken (cl100k_base) count of the visible response text
- `api_reported_output_tokens` — tokens as reported by the provider API
- `reasoning_tokens = max(0, api_reported − visible)` — hidden reasoning overhead
- `cost_visible_only = visible_output_tokens × cost_per_output_token` — comparable across models
- `ror = reasoning_tokens / visible_output_tokens` — Reasoning Overhead Ratio
- `is_reasoning_model = reasoning_tokens > 0` — derived boolean

Note: `visible_output_tokens` uses tiktoken (cl100k_base) for all models. For non-OpenAI models
(e.g. DeepSeek), small non-zero `reasoning_tokens` on non-reasoning models may reflect tokenizer
mismatch rather than true reasoning overhead.

## Primary Application Flows

1. Create study → add prompts → generate candidates (AI or manual) → score SFS+LER → approve
2. Compute MAGI Selection Scores → rank candidates → flag `magi_required` for borderline cases
3. Run experiment → call LLM APIs → store token results (immutable) → compute PEI
4. Export dataset (CSV/JSON) enriched with: SFS, LER, PEI, visible/reasoning tokens, MAGI scores

## Development Conventions

- Author: Matteo Morreale
- No references to "manus" in class/object/variable names
- Routes: /studies, /prompts, /translations, /experiments, /settings, /reports
- All experiment runs are immutable (no UPDATE on token_results)
- Prompt template: [Instruction] <<< [Input] >>> [Expected Output]
- Schema migrations via `_migrate_schema()` in DatabaseManager using ALTER TABLE ADD COLUMN
- Derived fields (`reasoning_tokens`, `ror`, `cost_visible_only`, `is_reasoning_model`) are
  computed in Python inside `get_results_by_run()` — NOT stored in the DB

## Documentation Map

- agents/architecture.md — folder structure and module responsibilities
- agents/datastructure.md — DB schema and relationships
- agents/api.md — internal API contracts (routes)
- agents/task.md — task tracker
- agents/log_history/ — bug/regression logs (consult only when needed)
