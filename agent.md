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

- **StudyController** — CRUD for studies; `GET /<id>/magi-repair-status` (JSON progress), `POST /<id>/regen-magi` (bulk MAGI regeneration)
- **PromptController** — prompt management, template enforcement, readiness status
- **TranslationController** — candidate management, scoring (SFS + LER), approval, MAGI scores
- **ExperimentController** — create runs (with `repetitions` param), delete runs
- **RunController** — JSON queue-status polling; stop/restart/resume/retry; redo-model / replace-model; revalidate-status
- **SettingsController** — API keys (Fernet-encrypted at rest), model configuration (including Qwen region)
- **ReportController** — export dataset, score visualizations, bulk delete runs
- **LLMService** — unified interface to all providers (7 total); `TokenScribeCallResult` carries `model_not_found` flag; cross-provider 404/deprecation detection via `_is_model_not_found()`
- **QueueService** — daemon thread processing `run_queue` one item at a time; dispatches `llm_call`, `magi_phase2`, `compute_pei`, `finalize_pei_groups`, `snapshot_translations`; automatic tier-aware fallback on `model_not_found`
- **QueueModel** — CRUD for `run_queue`; dequeue / mark_done / mark_error / mark_timeout / cancel_pending_items / restart_stopped_run / reset_items_for_retry / recompute_run_status
- **ScoringService** — SFS (DSF+RTF), LER, PEI, MAGI Selection Score computation
- **MAGIService** — three-judge LLM panel (Balthasar, Caspar, Melchior) with retry logic
- **CryptoService** — Fernet AES-128-CBC symmetric encryption; key from `TOKENSCRIBE_ENCRYPTION_KEY` env var (auto-generated to `.env` on first run); `SettingsModel` calls it transparently for `*_api_key` fields
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
Also stored as a **snapshot** on the `prompts` row (`pei_value`, `pei_cv_*`, `pei_saved_at`) via
`PromptModel.save_pei_snapshot()` — called automatically by `compute_selection_scores()` and
manually via `POST /prompts/<id>/pei/refresh`. The detail page shows a staleness warning when
`pei_saved_at < MAX(approved_at)` for that prompt.

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
- `cost_visible_only = visible_output_tokens × cost_per_output_token / 1_000_000` — comparable across models
- `ror = reasoning_tokens / visible_output_tokens` — Reasoning Overhead Ratio
- `is_reasoning_capable` — from `models.is_reasoning` (static DB flag set at model seed time)
- `reasoning_observed = reasoning_tokens > REASONING_THRESHOLD` — dynamic boolean per result; threshold `TokenScribeConfig.REASONING_THRESHOLD = 10` guards against tokenizer-drift false positives
- `reasoning_state` — 4-way classification derived by crossing the two flags:
  - `"active"` — capable model, reasoning tokens observed
  - `"capable_but_inactive"` — capable model, no reasoning tokens (e.g. extended-thinking disabled)
  - `"anomaly"` — non-capable model yet reasoning tokens detected → WARNING logged
  - `"non_reasoning"` — non-capable model, no reasoning tokens
- `response_valid` — `0` if response text is empty/blank or visible_output_tokens = 0; used by `recompute_run_status()` to detect partial completions

Note: `visible_output_tokens` uses tiktoken (cl100k_base) for all models. For non-OpenAI models
(e.g. Anthropic, DeepSeek), small non-zero `reasoning_tokens` may reflect tokenizer mismatch
rather than true hidden reasoning. The `> 10` threshold guards against this noise.

### Repetition Support

Each experiment run can specify `repetitions_per_cell` (1–10, default 3): every (prompt × model × language)
cell gets N queue items with `repetition_index` 0..N−1. Each item inserts a `token_results` row with
that `repetition_index`. Retries within a cell increment `attempt_index` atomically; only the latest
`attempt_status='success'` row per (run, prompt, language, model, repetition_index) is surfaced by
`get_results_by_run()`.

## Primary Application Flows

1. Create study → add prompts → generate candidates (AI or manual) → score SFS+LER → approve
2. Compute MAGI Selection Scores (Phase 1) → rank candidates → flag `magi_required`
3. Optionally: run Phase 2 LLM panel for flagged candidates → store per-judge verdicts + consensus
4. (Optional) MAGI repair via study detail page: `POST /studies/<id>/regen-magi` → re-runs Phase 1+2 for selected prompts as a `[MAGI repair]` run
5. Check pre-run readiness (semaphore) per prompt → run experiment (choose `repetitions`) → store token results → compute PEI
6. (Optional) Stop mid-flight: `POST /experiments/<id>/stop` cancels pending items; `POST /experiments/<id>/restart` re-queues them
7. Export dataset (CSV/JSON) enriched with: SFS, LER, PEI, visible/reasoning tokens, MAGI scores + judge breakdown

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

## LLM Provider Resilience

### model_not_found Fallback

`TokenScribeCallResult` carries a `model_not_found: bool` flag (default `False`).
`_is_model_not_found(error_str)` in `llm_service.py` detects 404/deprecation errors across all providers:

- Anthropic: `"not_found_error"` in error string
- OpenAI-compatible (OpenAI, DeepSeek, Meta, Qwen, Mistral): `"error code: 404"` + `"model"`, or `"model_not_found"`, `"no such model"`, `"model does not exist"`
- Google: `"no longer available"` or error string starting with `"404 "`

All 7 provider `except` blocks call `_is_model_not_found()` and set the flag accordingly.

When `QueueService._exec_llm_call` receives `model_not_found=True`, it calls `_get_fallback_model()`:

- Queries active models for the same provider ordered by `id DESC`
- **Tier-aware selection**: first looks for a model whose name contains the same tier keyword
  (`flash`, `sonnet`, `haiku`, `opus`, `turbo`, `pro`, `mini`, `nano`) as the original model
- Falls back to the most-recently-added active model if no same-tier match exists
- Updates `model_id` to the fallback's DB id (prevents FK constraint violations when the
  original model has been removed from the `models` table)
- Examples: `gemini-2.0-flash` → `gemini-2.5-flash`; `claude-sonnet-4` → `claude-sonnet-4-6`

### Qwen Region Setting

Qwen (DashScope) has two endpoints depending on where the API key was created:

- `"china"` (default): `https://dashscope.aliyuncs.com/compatible-mode/v1` — keys from `aliyun.com`
- `"international"`: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` — keys from `alibabacloud.com`

The endpoint is selected at call time by reading `settings["qwen_region"]`.
Configured in the Settings dashboard (API Keys card → Qwen Region dropdown).
Saved via `POST /settings/api-keys` alongside the API key.

### Invalid / Deprecated Models

Models with no version suffix or deprecated by the provider are removed from `config.py` DEFAULT_MODELS
and deactivated (`is_active=0`) in the DB to prevent them from appearing in the UI:

- `claude-sonnet-4`, `claude-opus-4` — removed (Anthropic requires full version suffix)
- `gemini-2.0-flash` — deactivated (deprecated by Google; replaced by `gemini-2.5-flash`)

## Development Conventions

- Author: Matteo Morreale
- No references to "manus" in class/object/variable names
- Routes: /studies, /prompts, /translations, /experiments, /settings, /reports
- `token_results` rows are INSERT-only per (run, prompt, language, model, repetition_index, attempt_index); retries add a new row with incremented `attempt_index`
- Prompt template: [Instruction] <<< [Input] >>> [Expected Output]
- Schema migrations via `_migrate_schema()` in DatabaseManager using ALTER TABLE ADD COLUMN
- Derived fields (`reasoning_tokens`, `ror`, `cost_visible_only`, `reasoning_observed`, `reasoning_state`, `response_valid`) are computed in Python inside `get_results_by_run()` — NOT stored in the DB
- `magi_judges` is stored as JSON TEXT in DB; deserialized to dict in both
  `SelectionScoreModel.get_by_prompt()` and `ExperimentModel.get_translation_scores_by_run()`
  so templates and exports always receive a Python dict, never a raw string
- `model_not_found` flag on `TokenScribeCallResult` drives automatic fallback in QueueService;
  never raise directly — let the flag propagate so the queue can substitute a valid model
- API keys are encrypted at rest using `CryptoService` (Fernet); `SettingsModel` handles encryption/decryption transparently; old plain-text values in the DB are decrypted gracefully (InvalidToken → return as-is)
- Run statuses: `queued` | `running` | `completed` | `partial` | `error` | `stopped`
- Queue item statuses: `pending` | `running` | `done` | `error` | `timeout` | `cancelled`

## Documentation Map

- agents/architecture.md — folder structure and module responsibilities
- agents/datastructure.md — DB schema and relationships
- agents/api.md — internal API contracts (routes)
- agents/task.md — task tracker
- agents/log_history/ — bug/regression logs (consult only when needed)
