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
- **PromptController** — prompt management, template enforcement, readiness status
- **TranslationController** — candidate management, scoring (SFS + LER), approval, MAGI scores
- **ExperimentController** — run experiments via LLM APIs, store token results, delete runs
- **SettingsController** — API keys, model configuration
- **ReportController** — export dataset, score visualizations, bulk delete runs
- **LLMService** — unified interface to all providers (7 total)
- **ScoringService** — SFS (DSF+RTF), LER, PEI, MAGI Selection Score computation
- **MAGIService** — three-judge LLM panel (Balthasar, Caspar, Melchior) with retry logic
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

### MAGI Selection Score — Phase 1

`score_absolute = SFS − λ·PEI − ν·|LER_char − 1|`
λ = 0.5, ν = 0.5
Rank candidates by score_absolute descending; `score_rank_pct = 1 − (rank−1)/(n−1)`.
`magi_required = rank > max(1, ⌊n/4⌋)` — flags candidates needing LLM panel (Phase 2).
Stored in `selection_score_results`.

### MAGI Phase 2 — LLM Judge Panel

Three independent LLM judges (Balthasar, Caspar, Melchior) each score a translation on **three dimensions**:
`semantic_fidelity`, `register_match`, `naturalness` — each an integer 1–5.
Aggregate score per judge = `mean((v-1)/4)` across the three dimensions → normalized to 0.0–1.0.
`magi_score = mean(valid_scores)` — skips judges that failed.
`magi_disagreement = stdev(valid_scores) > 0.15`.
Per-judge verdict stored in `magi_judges` (JSON): `{model_id, model_name, semantic_fidelity, register_match, naturalness, score, raw_response, error, attempts}`.
MAGIService retries each judge up to 3 times on parse failure or API error.
`_parse_verdict()` is the primary parser: extracts a JSON object `{semantic_fidelity, register_match, naturalness}` from the response.
Falls back to `_parse_score()` (three-pass: bare float → embedded 0.xx/1.0x decimal → standalone 0/1) for holistic responses.
The judge prompt asks for a single JSON object with the three dimension keys, structured with
`## Output format (MANDATORY)` and one valid-response example to anchor models
(especially reasoning models like gpt-5) that may add explanatory text.

### Token Efficiency Metrics (experiment runs)

- `visible_output_tokens` — tiktoken (cl100k_base) count of the visible response text
- `api_reported_output_tokens` — tokens as reported by the provider API
- `reasoning_tokens = max(0, api_reported − visible)` — hidden reasoning overhead
- `cost_visible_only = visible_output_tokens × cost_per_output_token` — comparable across models
- `ror = reasoning_tokens / visible_output_tokens` — Reasoning Overhead Ratio
- `is_reasoning_model = reasoning_tokens > REASONING_THRESHOLD` — derived boolean; threshold (`TokenScribeConfig.REASONING_THRESHOLD = 10`) avoids false positives from tokenizer drift (tiktoken vs provider tokenizer can introduce 1–3 token discrepancies on any model)

Note: `visible_output_tokens` uses tiktoken (cl100k_base) for all models. For non-OpenAI models
(e.g. Anthropic, DeepSeek), small non-zero `reasoning_tokens` may reflect tokenizer mismatch
rather than true hidden reasoning. The `> 10` threshold guards against this noise.

## Primary Application Flows

1. Create study → add prompts → generate candidates (AI or manual) → score SFS+LER → approve
2. Compute MAGI Selection Scores (Phase 1) → rank candidates → flag `magi_required`
3. Optionally: run Phase 2 LLM panel for flagged candidates → store per-judge verdicts + consensus
4. Check pre-run readiness (semaphore) per prompt → run experiment → store token results (immutable) → compute PEI
5. Export dataset (CSV/JSON) enriched with: SFS, LER, PEI, visible/reasoning tokens, MAGI scores + judge breakdown

## Pre-Run Readiness Semaphore

Before launching an experiment, both `/prompts/<id>` and `/studies/<id>/experiments/new` show
a per-prompt readiness status computed by `SelectionScoreModel.get_readiness_by_prompts()`:

- **green** — all approved translations are scored (SFS) + MAGI Phase 1 computed + no `magi_required`
- **yellow** — not all scored, or MAGI not computed, or at least one candidate is `magi_required`
- **red** — no approved translations

The experiment new page shows a readiness table with columns:
Approved, SFS scored, MAGI count, Judge↯ count, Status badge.
A red warning banner appears if any prompt has no approved translations.

## UX — Loading States

Any `<button type="submit" data-loading="…">` inside a form gets automatic loading feedback
on submit: the button is disabled, gains `.ts-btn-loading` class (CSS spinner via `::before`),
and its text changes to the `data-loading` value.
Key buttons: "Run Experiment", "Calcola MAGI Scores", "Genera traduzioni", "Score SFS".

## MAGI Judge Tooltip

In the MAGI Results card (`translations/list.html`), each B/C/M score cell is a
`.ts-judge-cell` with a `.ts-judge-tooltip` child div that appears on hover.
The tooltip shows: judge name + model name, score (4 decimal places), attempt count,
error reason (if failed), and raw LLM response (truncated to 200 chars).
A `—` for a failed judge is styled with `text-decoration: underline dotted; cursor: help`
to signal it is hoverable. Old records (stored before `raw_response` was added) show
`"n/a (record predates raw logging)"` in the tooltip.

## Development Conventions

- Author: Matteo Morreale
- No references to "manus" in class/object/variable names
- Routes: /studies, /prompts, /translations, /experiments, /settings, /reports
- All experiment runs are immutable (no UPDATE on token_results)
- Prompt template: [Instruction] <<< [Input] >>> [Expected Output]
- Schema migrations via `_migrate_schema()` in DatabaseManager using ALTER TABLE ADD COLUMN
- Derived fields (`reasoning_tokens`, `ror`, `cost_visible_only`, `is_reasoning_model`) are
  computed in Python inside `get_results_by_run()` — NOT stored in the DB
- `magi_judges` is stored as JSON TEXT in DB; deserialized to dict in both
  `SelectionScoreModel.get_by_prompt()` and `ExperimentModel.get_translation_scores_by_run()`
  so templates and exports always receive a Python dict, never a raw string

## Documentation Map

- agents/architecture.md — folder structure and module responsibilities
- agents/datastructure.md — DB schema and relationships
- agents/api.md — internal API contracts (routes)
- agents/task.md — task tracker
- agents/log_history/ — bug/regression logs (consult only when needed)
