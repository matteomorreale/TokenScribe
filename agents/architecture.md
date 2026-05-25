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
│   │   ├── ne_service.py        # Named Entity Preservation Rate (NEPR) computation
│   │   ├── olf_service.py       # Output Language Fidelity (OLF) via fasttext lid.176
│   │   ├── translation_ai_service.py  # Bulk AI translation with PEI-aware iterative refinement
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
├── data/
│   └── lid.176.bin              # fasttext language-ID model (130 MB — not bundled, downloaded once)
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

- controllers/translation_controller.py — single-prompt AI candidate generation
- controllers/study_controller.py — bulk translation (`POST /<id>/bulk-translate`, background worker thread)
- models/translation_model.py
- models/selection_score_model.py
- services/scoring_service.py
- services/magi_service.py
- services/translation_ai_service.py — iterative PEI-aware AI translation (called by both controllers)
- services/tsf_service.py — TSF 3-judge panel: classify translation strategy for TSF probe prompts

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
- `discover_answer_variant(prompt_text, language, response_text, llm_service, judge_models)` → `{is_correct, canonical_form, judges}`
  — 3-judge panel with majority vote (≥2 of 3); `is_correct=True` if ≥2 agree; `canonical_form` = surface form from first positive judge
  — `judges` dict: per-judge `{is_correct, canonical_form, raw_response, error, attempts}`
  — on success, caller stores `canonical_form` via `ExperimentModel.insert_magi_answer_variant()`
- `label_named_entities(prompt_text, language, llm_service, judge_models)` → `list[{entity_name, expected_form, allow_original}]`
  — 3-judge panel with per-entity majority vote (≥2 of 3); an entity is included only if ≥2 judges independently identify it
  — `allow_original=True` if ≥2 agreeing judges say the original English form is acceptable
  — stored via `ExperimentModel.insert_ne_expectations()`; status tracked in `ne_labeling_status`
- `_parse_json_bool_response(text)` → `dict | None` — JSON parser for `{is_correct, canonical_form}` shaped responses
- `_parse_json_array_response(text)` → `list | None` — JSON parser for array-shaped responses (NE labeling)
- `_parse_verdict(text)` → `{semantic_fidelity, register_match, naturalness, score, error}` — primary parser for Phase 2
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
- `update_correctness_metrics(token_result_id, metrics)` — writes `{answer_correct, answer_in_target_language, language_leakage}` to `token_results`
- `update_olf_score(token_result_id, score)` — writes `olf_score` to `token_results`
- `update_nepr_score(token_result_id, score)` — writes `nepr_score` to `token_results`
- `get_prompt_base_text(prompt_id)` → `str | None`
- `get_magi_answer_variants(prompt_id, language_id)` → `list[str]` — fetches MAGI-discovered answer variants; `language_id=None` returns any-language variants
- `insert_magi_answer_variant(prompt_id, language_id, variant, judge_name, judge_model)` — stores a new variant in `magi_answer_variants`
- `update_answer_correct_by_row(token_result_id)` — re-evaluates and updates correctness fields for a single row using current MAGI variants
- `get_ne_expectations(prompt_id, language_id)` → `list[dict]` — returns NE expectations for a (prompt, language) pair from `ne_expectations`
- `get_ne_labeling_status(prompt_id, language_id)` → `str | None` — `"pending" | "done" | "failed"` or None if not started
- `set_ne_labeling_status(prompt_id, language_id, status)` — upserts status in `ne_labeling_status`
- `insert_ne_expectations(prompt_id, language_id, entities, judge_name, judge_model)` — bulk-upserts into `ne_expectations`

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
- `has_pending_running_of_type(run_id, operation_type)` → bool — returns True if any item of the given type is still `pending` or `running` (used for dependency gating between queue operations)
- `requeue_for_dependency(item_id)` — resets a `pending` item back to `pending` after its dependency completes (used when an `answer_discovery` item was blocked waiting for the llm_call to finish)

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

### NEService (Named Entity Preservation Rate)

Module-level (no class), file `app/services/ne_service.py`.

- `compute_nepr(response_text, expectations)` → `float | None`
  — `expectations`: list of `{entity_name, expected_form, allow_original}` dicts (from `ExperimentModel.get_ne_expectations()`)
  — returns fraction of expected entities found in response (0.0–1.0); `None` if expectations is empty
  — matching is substring-based via `_normalize()` from correctness_service; `allow_original=True` makes the English original form also count

### OLFService (Output Language Fidelity)

Module-level (no class), file `app/services/olf_service.py`.

- `compute_olf(response_text, language_name)` → `float | None`
  — returns fraction of response characters detected as belonging to `language_name` (0.0–1.0)
  — returns `None` when fasttext model is unavailable, language not in `LANG_TO_FT`, or text is too short (< `MIN_CHUNK_CHARS=15`)
  — splits text into sentence-level chunks; per-chunk fasttext `lid.176` prediction; weights by character count
  — model lazily loaded from `data/lid.176.bin`; set `_model=False` on load failure to avoid retrying
- `LANG_TO_FT` — dict mapping TokenScribe language names to fasttext ISO 639-1 codes (Arabic → ar, Chinese → zh, etc.)

### TranslationAIService

Module-level function, file `app/services/translation_ai_service.py`.

- `run_ai_translate(prompt, language_ids, sfs_min, pei_profile, pei_max, candidates_per_lang, db, settings, log_service)` → `dict`
  — generates AI translations for one prompt across given language IDs
  — iterative refinement loop: generate candidate → score SFS+LER → check PEI convergence → adjust structural direction for PEI outliers → retry up to 3 times per language
  — `pei_profile`: `"homogeneous"` (PEI max 0.20) | `"moderate"` / `"cross_script"` (PEI max 0.35)
  — returns `{created, warnings, accepted_pei, accepted, note, langs, candidates_by_lang}` where `accepted=False` means convergence failed and best-of-N candidate was used as fallback
  — uses `gpt-5.5` as the translation model (hardcoded)

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
1a. (Optional) Bulk translate: `POST /studies/<id>/bulk-translate` → background thread calls `run_ai_translate()` per prompt → optionally runs MAGI Phase 1 + Phase 2 → optionally auto-approves best candidate
2. Compute MAGI Phase 1 scores → rank candidates → flag `magi_required`
3. Optionally: run Phase 2 LLM panel (modal in `translations/list.html`) → store judge verdicts
4. (Optional) MAGI repair: `POST /studies/<id>/regen-magi` → creates `[MAGI repair]` run, recomputes Phase 1 + Phase 2 for selected prompts
5. Check pre-run readiness semaphore (`/prompts/<id>` widget + `/experiments/new` table)
6. Run experiment (with `repetitions` param, default 3) → call LLM APIs `N` times per cell → snapshot translations → store token results (`repetition_index`, `attempt_index`) → compute PEI → post-process correctness + OLF + NEPR via queue items
7. (Optional) Stop run mid-flight: `POST /experiments/<id>/stop` cancels pending items; `POST /experiments/<id>/restart` re-queues cancelled/error items
8. Export dataset (CSV/JSON) with full enrichment (SFS, LER, PEI, MAGI, token efficiency, correctness, OLF, NEPR)
9. (Optional) Redo/Replace model — on completed/partial run: optionally archive results to `run_history`, delete model results, reset/swap queue items, re-queue under same or new model
10. (Optional) Add models — on completed/partial/stopped run: `POST /experiments/<id>/add-models`; builds payloads from frozen `run_translation_snapshot` via `build_llm_payloads_from_snapshot()`; skips models already present in the run
11. (Optional) Duplicate run: `GET /experiments/<id>/duplicate` → pre-fills new-experiment form with same study/models/settings

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

## Queue Operation Types

| `operation_type`         | Description                                                          | Timeout |
|--------------------------|----------------------------------------------------------------------|---------|
| `snapshot_translations`  | Freeze approved translations into `run_translation_snapshot`         | 60 s    |
| `llm_call`               | Single LLM API call for one (prompt × language × model × repetition) | varies  |
| `magi_phase2`            | MAGI Phase 2: 3-judge panel for one translation candidate            | 60 s    |
| `compute_pei`            | Compute PEI for one (run × prompt)                                   | 60 s    |
| `finalize_pei_groups`    | Compute per-script/morphology PEI group rows                         | 60 s    |
| `magi_answer_discovery`  | MAGI 3-judge panel to discover correct answer variants               | 60 s    |
| `magi_ne_labeling`       | MAGI 3-judge panel to label named entities for a (prompt, language)  | 60 s    |
| `tsf_classification`     | TSF 3-judge panel to classify translation strategy for TSF prompts   | 90 s    |

Post-`llm_call` pipeline (all enqueued automatically after each successful `llm_call`):

1. Correctness evaluation via `CorrectnessService.evaluate()` (uses static + MAGI-discovered variants)
2. OLF via `OLFService.compute_olf()`
3. NEPR via `NEService.compute_nepr()` (only if `ne_labeling_status="done"` for this prompt+language)
4. `magi_answer_discovery` item enqueued if `answer_correct is None`
5. `tsf_classification` item enqueued if `prompt.analysis_type="tsf"`

`magi_ne_labeling` items are enqueued during experiment creation for each (prompt, language) cell where `ne_labeling_status` is not yet `"done"`. After NE labeling completes, `update_answer_correct_by_row()` is called for all existing token_results of the same (prompt, language).

## External Dependencies

- sentence-transformers — local multilingual embeddings (paraphrase-multilingual-MiniLM-L12-v2)
- tiktoken — neutral tokenizer (cl100k_base) for PEI and visible_output_tokens
- openai, anthropic, google-generativeai, mistralai (LLM provider SDKs)
- Qwen uses the `openai` SDK pointed at DashScope endpoints (no separate SDK)
- xAI (Grok) uses the `openai` SDK pointed at `https://api.x.ai/v1` (no separate SDK)

## Files Agents Should Avoid Reading Unless Necessary

- instance/tokenscribe.db (binary SQLite)
- app/static/* (CSS/JS assets)
