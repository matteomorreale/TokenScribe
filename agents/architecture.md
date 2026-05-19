# TokenScribe — Architecture

## Folder Structure

```text
TokenScribe/
├── app/
│   ├── __init__.py              # Flask app factory (create_app)
│   ├── controllers/             # HTTP route handlers (MVC Controllers)
│   │   ├── study_controller.py
│   │   ├── prompt_controller.py
│   │   ├── translation_controller.py
│   │   ├── experiment_controller.py
│   │   ├── settings_controller.py
│   │   └── report_controller.py
│   ├── models/                  # Data access layer (MVC Models)
│   │   ├── database.py          # DatabaseManager — connection + schema bootstrap + migrations
│   │   ├── study_model.py
│   │   ├── prompt_model.py
│   │   ├── translation_model.py
│   │   ├── experiment_model.py
│   │   ├── queue_model.py       # QueueModel — run_queue CRUD (dequeue, mark_done/error/timeout)
│   │   ├── selection_score_model.py  # MAGI Phase 1 + readiness semaphore
│   │   └── settings_model.py
│   ├── services/                # Business logic layer
│   │   ├── llm_service.py       # Unified LLM provider interface (8 providers); model_not_found + rate-limit fallback
│   │   ├── queue_service.py     # Daemon thread processing run_queue; tier-aware model fallback; inflated-token heuristic
│   │   ├── scoring_service.py   # SFS (DSF+RTF), LER, PEI, MAGI Phase 1 computation
│   │   ├── magi_service.py      # MAGI Phase 2: three-judge LLM panel with retry
│   │   ├── crypto_service.py    # Fernet AES-128-CBC symmetric encryption for API keys
│   │   ├── correctness_service.py  # Response correctness evaluation (correct / in_target_language / language_leakage)
│   │   └── export_service.py    # Dataset export (CSV, JSON)
│   ├── views/
│   │   └── templates/           # Jinja2 HTML templates (MVC Views)
│   │       ├── base.html
│   │       ├── studies/
│   │       ├── prompts/
│   │       ├── translations/
│   │       ├── experiments/
│   │       ├── settings/
│   │       └── reports/
│   └── static/
│       ├── css/
│       ├── js/
│       └── img/
├── instance/
│   └── tokenscribe.db           # SQLite database (gitignored)
├── agents/                      # AI agent documentation
├── run.py                       # Entry point
├── config.py                    # Configuration classes
├── requirements.txt
├── agent.md
└── claude.md
```

## Core Modules

### Study Management

- controllers/study_controller.py
- models/study_model.py

### Prompt Management

- controllers/prompt_controller.py — includes readiness semaphore via `SelectionScoreModel`
- models/prompt_model.py

### Translation Pipeline

- controllers/translation_controller.py — includes `ai_translate()` for AI candidate generation (uses gpt-5.5)
- models/translation_model.py
- models/selection_score_model.py
- services/scoring_service.py
- services/magi_service.py

### Experiment Execution

- controllers/experiment_controller.py — create/delete runs; readiness check on GET /new; `repetitions` + `reasoning_override_<id>` form params
- controllers/run_controller.py — JSON queue-status polling, stop/restart/resume/retry, redo-model, replace-model, add-models, update-notes, recompute-tokens, revalidate-status
- models/experiment_model.py
- models/queue_model.py
- services/llm_service.py
- services/queue_service.py

### MAGI Repair

- controllers/study_controller.py — `GET /<id>/magi-repair-status` (JSON), `POST /<id>/regen-magi`
- models/selection_score_model.py
- services/magi_service.py

### Settings & Configuration

- controllers/settings_controller.py
- models/settings_model.py — transparent encrypt/decrypt for API key fields via `CryptoService`
- services/crypto_service.py — Fernet-based symmetric encryption; key from `TOKENSCRIBE_ENCRYPTION_KEY` env var

### Reporting & Export

- controllers/report_controller.py — bulk delete runs
- services/export_service.py

## Key Service Methods

### ScoringService

- `score_translation(original, translation, back_translation)` → `{dsf, rtf, sfs, ler_char, ler_token}`
- `compute_ler(original, translation)` → `{ler_char, ler_token}`
- `compute_pei(texts)` → `{cv_char_length, cv_word_count, cv_token_count, pei}`
- `compute_selection_scores(candidates)` → mutates list, adds `score_absolute`, `score_rank`, `score_rank_pct`, `magi_required`
- `compute_structural_metrics(text)` → `{char_length, word_count, token_count}`
- `pei_band(pei)` → `"ottimo" | "plausibile" | "alto"`

### MAGIService

- `evaluate(original, translation, language, sfs, ler_char, llm_service, model_info)` → verdict dict
  — retries up to `MAX_RETRIES=3` times on parse failure or API error
  — verdict: `{model_id, model_name, semantic_fidelity, register_match, naturalness, score, raw_response, error, attempts}`
- `run_panel(…, judge_models)` → `{judges: {name: verdict}, magi_score, magi_disagreement}`
  — `judge_models`: list of 3 model_info dicts (Balthasar, Caspar, Melchior)
  — `magi_score = mean(valid_scores)`; `magi_disagreement = stdev > 0.15`
- `_parse_verdict(text)` → `{semantic_fidelity, register_match, naturalness, score, error}` — primary parser
  — extracts JSON object with three 1–5 integer dimensions; score = `mean((v-1)/4)` → 0–1
  — falls back to `_parse_score()` on JSON failure ("Holistic fallback")
- `_parse_score(text)` → float 0–1 or None — fallback only
  — Pass 1: bare number as full response
  — Pass 2: first `0.xx` or `1.0x` decimal in text (skips denominators via `(?<!/)\b`)
  — Pass 3: standalone `0` or `1`

### TranslationModel (new methods)

- `get_candidates_for_export(prompt_id)` → list of all candidates with scores + MAGI data (for per-prompt JSON download)
- `update_candidate_text(candidate_id, text)` — overwrites candidate text (edit flow)
- `get_latest_approved_at(prompt_id)` → ISO string or None — MAX(approved_at) in `approved_translations`

### SelectionScoreModel

- `upsert_scores(candidates)` — persists MAGI Phase 1 scores; resets magi_score/magi_judges on recompute
- `update_magi_result(candidate_id, magi_score, magi_disagreement, magi_judges)` — persists Phase 2
- `get_by_prompt(prompt_id)` → ranked list; `magi_judges` JSON deserialized to dict
- `get_by_prompt_multi(prompt_ids)` → `{prompt_id: [candidates]}`; `magi_judges` deserialized
- `get_readiness_by_prompts(prompt_ids)` → `{prompt_id: {approved_count, scored_count, magi_count, magi_required_count, judge_count, status}}`
  — `status`: `"green"` | `"yellow"` | `"red"` (see agent.md for logic)

### ExperimentModel

- `get_results_by_run(run_id)` — filters to `attempt_status='success'` rows, selects MAX `attempt_index` per (run, prompt, language, model, repetition_index); enriches with: `reasoning_tokens`, `cost_visible_only`, `ror`, `reasoning_observed`, `reasoning_state` (4-way), `prompt_notes`, `is_reasoning_capable`, `response_valid`; logs WARNING for `anomaly` state
- `insert_token_result(…, repetition_index, attempt_status)` — `attempt_index` auto-incremented atomically via MAX+1 subquery; `response_valid` auto-derived from response text if not passed explicitly
- `get_translation_scores_by_run(run_id)` — joins `run_translation_snapshot` → immune to re-approvals; includes all MAGI fields; `magi_judges` deserialized to dict before returning
- `get_latest_pei_for_prompt(prompt_id)` — most recent PEI from `pei_results`
- `snapshot_translations(run_id, study_id)` — freezes approved translations at run start
- `delete_run(run_id)` / `delete_runs_bulk(run_ids)` — cascade-deletes token_results
- `archive_model_results(run_id, model_id, model_name, reason, replaced_by_model_id, replaced_by_model_name)` — snapshots token_results for a model into `run_history` before redo/replace
- `delete_model_results(run_id, model_id)` — deletes token_results for a specific model in a run
- `get_run_history(run_id)` — returns archived history entries for a run (without `results_json`)
- `reconstruct_llm_payloads(run_id, model_id)` — rebuilds llm_call payloads from token_results + run_translation_snapshot; used for runs created before the queue system (no run_queue rows)
- `get_run_model_ids(run_id)` → `set[int]` — returns all model_ids already present in the run (from both `token_results` and `run_queue` llm_call items)
- `build_llm_payloads_from_snapshot(run_id, model_id, repetitions)` → `list[dict]` — generates llm_call payloads for a new model using the frozen `run_translation_snapshot`; used by add-models flow
- `update_run_notes(run_id, notes)` — updates `experiment_runs.notes` in place (used by the inline notes editor on detail.html)
- `recompute_visible_tokens(run_id)` → `dict` — retroactively applies the inflated-API-count heuristic to all stored `token_results`; returns `{checked, updated, skipped, unchanged}`; overwrites `visible_output_tokens` with a tiktoken cl100k_base count whenever `api_reported_output_tokens / max(1, len(response_text))` exceeds the script-aware ceiling (2.0 alphabetic, 1.5 logographic)

### QueueModel

- `cancel_pending_items(run_id)` → int — marks all `pending` items as `cancelled`; used by stop flow
- `restart_stopped_run(run_id)` → int — resets `cancelled` / `error` / `timeout` / `running` items to `pending`; used by restart flow
- `reset_items_for_retry(run_id, model_ids)` → int — resets `error` / `timeout` items (optionally filtered by model_ids) to `pending`
- `recover_stale_running(run_id)` — resets items stuck in `running` after crash/restart
- `recompute_run_status(run_id)` → str — derives `experiment_runs.status` from queue counts and `response_valid` flag; returns new status
- `get_model_llm_payloads(run_id, model_id)` — returns all llm_call payloads for a model from run_queue (any status)
- `redo_model_items(run_id, model_id, payloads)` — resets existing llm_call items for the model to `pending`; if no queue items exist, creates them from `payloads` (legacy runs support)
- `replace_model_items(run_id, old_model_id, new_model_id, new_model_info, payloads)` — deletes old model's queue items and inserts new ones for `new_model_id` with updated payload fields
- `get_run_repetitions(run_id)` → int — returns the number of repetitions used in the run (from `token_results` MAX repetition_index; fallback from queue payloads; default 3)

### CryptoService

- `__init__(env_path)` — reads `TOKENSCRIBE_ENCRYPTION_KEY` from env; auto-generates and appends key to `.env` on first run
- `encrypt(value)` → str — Fernet-encrypts a plaintext string
- `decrypt(value)` → str — decrypts a Fernet token; returns value unchanged for pre-encryption plain-text (transparent migration path)

### CorrectnessService

Module-level (no class), imported as `from app.services.correctness_service import evaluate`.

- `evaluate(response_text, prompt_id, language_name, extra_any_variants, extra_target_variants)` → `dict | None`
  — returns `{correct, in_target_language, language_leakage}` or `None` if no expected answers are registered for `prompt_id`
  — `correct` — the expected factual answer appears in the response (any language form)
  — `in_target_language` — the answer uses the target language form
  — `language_leakage` — correct fact but in the wrong language (cross-language confusion)
  — `extra_any_variants` / `extra_target_variants` — runtime-injected MAGI-discovered variants; merged with static registry
  — matching is substring-based after `_normalize()` (lowercase, numeral-map, strip punctuation, collapse whitespace)
- `EXPECTED_ANSWERS` — dict keyed by `prompt_id`; each entry has `any_language_variants: list[str]` and `target_language_variants: dict[str, list[str]]`; extend to add new prompts
- `_normalize(text)` — normalises text before comparison; maps 8 non-ASCII numeral blocks to ASCII digits; does NOT touch non-Latin scripts

## UX Patterns

### Loading States

`data-loading="…"` on any `<button type="submit">` triggers automatic loading feedback on form
submit: button is disabled, `.ts-btn-loading` CSS class adds a spinning border-circle via `::before`,
text changes to the `data-loading` value. Implemented in `tokenscribe.js` as a global form listener.

### Judge Tooltips

`.ts-judge-cell` + `.ts-judge-tooltip` CSS pattern in `translations/list.html`.
On hover, shows: judge name, model name, score, attempt count, error reason, raw LLM response.
`magi_judges` JSON must be deserialized before reaching the template (done in model layer).

### Translation Text Modal

`#ts-modal-view-text` in `prompts/detail.html`. "View" button on each candidate row opens a
full-screen modal (`ts-modal` + `active` class toggle) with the raw translation text in a `<pre>`.
Closed via ×, Escape, or click-outside.

### Language Preset Buttons

`data-ts-lang-preset-key` / `data-ts-lang-preset-value` on `<button>` elements select matching
`<option>` elements in the multi-select. Supported key types:

- `writingSystem` / `scriptGroup` / `morphologyGroup` — matches against `data-*` attribute on `<option>`
- `langCodes` — value is comma-separated language codes; matches `data-lang-code` on each `<option>`
  (used by the "Mixed 10" preset: `it,de,ru,pl,ar,hi,zh-Hans,ja,ko`)

## Main Entry Points

- `run.py` — starts Flask dev server
- `app/__init__.py` — Flask app factory, registers all blueprints

## Primary Application Flows

1. Create study → add prompts → generate candidates (AI or manual) → score SFS+LER → approve
2. Compute MAGI Phase 1 scores → rank candidates → flag `magi_required`
3. Optionally: run Phase 2 LLM panel (modal in `translations/list.html`) → store judge verdicts
4. (Optional) MAGI repair: `POST /studies/<id>/regen-magi` → creates `[MAGI repair]` run, recomputes Phase 1 + Phase 2 for selected prompts
5. Check pre-run readiness semaphore (`/prompts/<id>` widget + `/experiments/new` table)
6. Run experiment (with `repetitions` param, default 3) → call LLM APIs `N` times per cell → snapshot translations → store token results (`repetition_index`, `attempt_index`) → compute PEI
7. (Optional) Stop run mid-flight: `POST /experiments/<id>/stop` cancels pending items; `POST /experiments/<id>/restart` re-queues cancelled/error items
8. Export dataset (CSV/JSON) with full enrichment (SFS, LER, PEI, MAGI, token efficiency)
9. (Optional) Redo/Replace model — on completed/partial run: optionally archive results to `run_history`, delete model results, reset/swap queue items, re-queue under same or new model
10. (Optional) Add models — on completed/partial/stopped run: `POST /experiments/<id>/add-models`; builds payloads from frozen `run_translation_snapshot` via `build_llm_payloads_from_snapshot()`; skips models already present in the run

## Redo / Replace Model Flow

Available on `completed` or `partial` runs via the "Gestione Modelli" card in `experiments/detail.html`.

**Redo** (`POST /experiments/<id>/redo-model`):

1. Retrieve llm_call payloads from run_queue; fall back to `reconstruct_llm_payloads()` for legacy runs
2. Optionally archive current token_results to `run_history` (reason=`"redo"`)
3. Delete token_results for the model
4. Reset existing queue items to `pending`; or insert fresh items if none exist
5. Update run status → `queued`

**Replace** (`POST /experiments/<id>/replace-model`):

1. Retrieve payloads for the old model
2. Optionally archive to `run_history` (reason=`"replace"`, `replaced_by_model_*` filled)
3. Delete token_results for old model
4. Delete old model's queue items; insert new items with new model fields (model_id, model_name, provider, costs, is_reasoning)
5. Update run status → `queued`

PEI is not recomputed (it depends on translations, not model calls).

## LLM Resilience

`TokenScribeCallResult.model_not_found` (bool) is set by `_is_model_not_found()` when any provider
returns a 404 / "no longer available" / "not_found_error" response.
`QueueService._get_fallback_model(provider, exclude_id, original_name)` selects a same-tier
replacement (flash→flash, sonnet→sonnet, etc.) from active models, updating `model_id` in the
`token_results` insert to avoid FK violations against the deleted/deactivated model row.

`TokenScribeCallResult.rate_limited` (bool) is set by `_is_rate_limited()` on 429 / "rate_limit" /
"quota exceeded" / "resource_exhausted" responses. In `QueueService._exec_llm_call()` a rate-limited
result raises `RateLimitError`; the worker loop catches it and calls `QueueModel.requeue_at_end()`
(delete + re-insert with new auto-increment id) so the item goes to the back of the queue. After
`max_retries=10` re-queues the item is marked `error`.

OpenAI Responses API fallback: `_call_openai()` catches a "not a chat model" / "v1/completions" error
and retries via `_call_openai_responses()` (using `client.responses.create()` with `reasoning.effort`).
This transparently handles models only available on the Responses API (e.g. gpt-5.4-pro).

**Reasoning override** (`reasoning_override` in llm_call payload): `""` (default) — model's own `is_reasoning` flag governs behaviour; `"on"` — force `is_reasoning=True` for this call; `"off"` — force `is_reasoning=False`.
For OpenAI models that accept `reasoning_effort` (`o1`/`o3`/`o4`/`gpt-5*`): `"on"` → `reasoning_effort="high"`, `"off"` → `reasoning_effort="low"` (or `"medium"` for gpt-5.5 which does not support `"low"`).
Set per model in the new-experiment form via `reasoning_override_<model_id>` select; a global preset syncs all selects at once.

**Inflated API token count heuristic** (in `QueueService._exec_llm_call()` and `ExperimentModel.recompute_visible_tokens()`):
Some providers (notably Qwen reasoning models) bundle undisclosed reasoning tokens into `completion_tokens`, making `api_reported_output_tokens` disproportionately large.
Detection: if `api_output / max(1, len(response_text)) > threshold` (2.0 for alphabetic scripts, 1.5 for logographic CJK scripts), the provider count is deemed inflated.
Correction: `visible_output_tokens` is overwritten with a local tiktoken `cl100k_base` count; `reasoning_tokens` is recalculated as `max(0, api_output − local_toks)`.
The same logic is available retroactively via `ExperimentModel.recompute_visible_tokens()` (triggered by `POST /experiments/<id>/recompute-tokens`).

## External Dependencies

- sentence-transformers — local multilingual embeddings (paraphrase-multilingual-MiniLM-L12-v2)
- tiktoken — neutral tokenizer (cl100k_base) for PEI and visible_output_tokens
- openai, anthropic, google-generativeai, mistralai (LLM provider SDKs)
- Qwen uses the `openai` SDK pointed at DashScope endpoints (no separate SDK)
- xAI (Grok) uses the `openai` SDK pointed at `https://api.x.ai/v1` (no separate SDK)

## Files Agents Should Avoid Reading Unless Necessary

- instance/tokenscribe.db (binary SQLite)
- app/static/* (CSS/JS assets)
