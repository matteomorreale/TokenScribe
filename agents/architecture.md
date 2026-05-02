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
│   │   ├── llm_service.py       # Unified LLM provider interface (7 providers); model_not_found fallback
│   │   ├── queue_service.py     # Daemon thread processing run_queue; tier-aware model fallback
│   │   ├── scoring_service.py   # SFS (DSF+RTF), LER, PEI, MAGI Phase 1 computation
│   │   ├── magi_service.py      # MAGI Phase 2: three-judge LLM panel with retry
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

- controllers/experiment_controller.py — create/delete runs; readiness check on GET /new
- controllers/run_controller.py — JSON queue-status polling, resume/retry, redo-model, replace-model
- models/experiment_model.py
- models/queue_model.py
- services/llm_service.py
- services/queue_service.py

### Settings & Configuration

- controllers/settings_controller.py
- models/settings_model.py

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

- `get_results_by_run(run_id)` — rows enriched with: `reasoning_tokens`, `cost_visible_only`, `ror`, `reasoning_observed`, `reasoning_state` (4-way: `active` | `capable_but_inactive` | `anomaly` | `non_reasoning`), `prompt_notes`, `is_reasoning_capable`; logs WARNING for `anomaly` state
- `get_translation_scores_by_run(run_id)` — joins `run_translation_snapshot` → immune to re-approvals; includes all MAGI fields; `magi_judges` deserialized to dict before returning
- `get_latest_pei_for_prompt(prompt_id)` — most recent PEI from `pei_results` (fallback when no approved translations exist at MAGI Phase 1 compute time)
- `snapshot_translations(run_id, study_id)` — freezes approved translations at run start
- `delete_run(run_id)` / `delete_runs_bulk(run_ids)` — cascade-deletes token_results
- `archive_model_results(run_id, model_id, model_name, reason, replaced_by_model_id, replaced_by_model_name)` — snapshots token_results for a model into `run_history` before redo/replace
- `delete_model_results(run_id, model_id)` — deletes token_results for a specific model in a run
- `get_run_history(run_id)` — returns archived history entries for a run (without `results_json`)
- `reconstruct_llm_payloads(run_id, model_id)` — rebuilds llm_call payloads from token_results + run_translation_snapshot; used for runs created before the queue system (no run_queue rows)

### QueueModel (new redo/replace methods)

- `get_model_llm_payloads(run_id, model_id)` — returns all llm_call payloads for a model from run_queue (any status)
- `redo_model_items(run_id, model_id, payloads)` — resets existing llm_call items for the model to `pending`; if no queue items exist, creates them from `payloads` (legacy runs support)
- `replace_model_items(run_id, old_model_id, new_model_id, new_model_info, payloads)` — deletes old model's queue items and inserts new ones for `new_model_id` with updated payload fields

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
4. Check pre-run readiness semaphore (`/prompts/<id>` widget + `/experiments/new` table)
5. Run experiment → call LLM APIs → snapshot translations → store token results → compute PEI
6. Export dataset (CSV/JSON) with full enrichment (SFS, LER, PEI, MAGI, token efficiency)
7. (Optional) Redo/Replace model — on completed/partial run: optionally archive results to `run_history`, delete model results, reset/swap queue items, re-queue under same or new model

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

## External Dependencies

- sentence-transformers — local multilingual embeddings (paraphrase-multilingual-MiniLM-L12-v2)
- tiktoken — neutral tokenizer (cl100k_base) for PEI and visible_output_tokens
- openai, anthropic, google-generativeai, mistralai (LLM provider SDKs)
- Qwen uses the `openai` SDK pointed at DashScope endpoints (no separate SDK)

## Files Agents Should Avoid Reading Unless Necessary

- instance/tokenscribe.db (binary SQLite)
- app/static/* (CSS/JS assets)
