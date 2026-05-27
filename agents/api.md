# TokenScribe — API Contracts

## Studies

```text
GET  /studies                         list all studies
GET  /studies/new                     form to create study
POST /studies/new                     create study
GET  /studies/<id>                    study detail
GET  /studies/<id>/edit               edit form
POST /studies/<id>/edit               update study
POST /studies/<id>/delete             delete study
GET  /studies/<id>/magi-repair-status    JSON — progress of the active MAGI repair run (if any)
POST /studies/<id>/regen-magi            bulk re-compute Phase 1 + Phase 2 for all (or selected) prompts
POST /studies/<id>/bulk-translate        start bulk AI translation job (background thread)
GET  /studies/<id>/bulk-translate-status JSON — progress of the active bulk translate job (if any)
```

### POST /studies/{study_id}/regen-magi — Form Fields

```text
prompt_ids   list[int]  (optional) subset of prompt IDs to regenerate; omit to regenerate all
```

Creates a dedicated `experiment_run` with `notes='[MAGI repair]'`, recomputes MAGI Phase 1
for all approved+scored candidates, then enqueues Phase 2 items if judges are configured.

### POST /studies/{study_id}/bulk-translate — Form Fields

```text
prompt_ids           list[int]  (optional) subset of prompt IDs; omit to translate all
language_ids         list[int]  languages to generate candidates for
bulk_sfs_min         float      minimum SFS threshold (default 0.85)
bulk_pei_profile     str        "homogeneous" | "moderate" | "cross_script" (default "homogeneous")
bulk_candidates_per_lang  int   candidates to generate per language (default 2)
bulk_run_magi        "1"        run MAGI Phase 1 after generating candidates
bulk_run_phase2      "1"        run MAGI Phase 2 after Phase 1 (requires bulk_run_magi=1 and 3 judges configured)
bulk_auto_approve    "1"        auto-approve the best candidate per language after scoring
```

Runs in a daemon thread; poll `GET /<id>/bulk-translate-status` for progress.
Returns JSON `{active, total, completed, current_prompt, error}`.

## Prompts

```text
GET  /studies/<id>/prompts            list prompts for study
GET  /studies/<id>/prompts/new        form to add prompt
POST /studies/<id>/prompts/new        create prompt
GET  /prompts/<id>                    prompt detail — includes readiness semaphore widget
GET  /prompts/<id>/edit               edit form
POST /prompts/<id>/edit               update prompt
POST /prompts/<id>/delete             delete prompt
POST /prompts/<id>/pei/refresh        recompute PEI from current approved translations and save snapshot
POST /prompts/<id>/notes              save prompt notes field (inline form on detail page)
POST /prompts/migrate-delimiters      bulk-replace prompt delimiters (e.g. <<< >>> → <input> </input>)
```

### POST /prompts/migrate-delimiters — Form Fields

```text
old_open   str  opening delimiter to replace (default "<<<")
old_close  str  closing delimiter to replace (default ">>>")
new_open   str  new opening delimiter (default "<input>")
new_close  str  new closing delimiter (default "</input>")
```

## Translations

```text
GET  /prompts/<id>/translations                   list candidates (MAGI scores + results card if computed)
GET  /prompts/<id>/translations/new               form to add candidate manually
POST /prompts/<id>/translations/new               create candidate
POST /prompts/<id>/translations/ai-translate      generate candidates via LLM (bulk AI flow)
GET  /prompts/<id>/translations/compare           side-by-side comparison view
POST /prompts/<id>/selection-scores               compute MAGI Phase 1 + optional Phase 2

POST /translations/<id>/score                     compute SFS + LER for one candidate
POST /translations/<id>/approve                   approve candidate
POST /translations/<id>/reject                    reject candidate
POST /translations/<id>/delete                    delete candidate
POST /prompts/<id>/translations/bulk-approve      bulk approve selected candidate_ids
POST /prompts/<id>/translations/bulk-reject       bulk reject selected candidate_ids
POST /prompts/<id>/translations/bulk-delete       bulk delete selected candidate_ids
GET  /translations/<id>/edit                      edit form for existing candidate (language read-only)
POST /translations/<id>/edit                      update candidate text
GET  /prompts/<id>/translations/export.json       download all candidates + scores as JSON attachment
```

### POST /prompts/{prompt_id}/selection-scores — Form Fields

```text
magi_candidate_ids   CSV of candidate IDs to score (from MAGI modal checkboxes)
force_magi           "1" to run Phase 2 judge panel
judge_balthasar      model_id for Balthasar (required if force_magi=1)
judge_caspar         model_id for Caspar    (required if force_magi=1)
judge_melchior       model_id for Melchior  (required if force_magi=1)
```

## Experiments

```text
GET  /experiments                             list all runs
GET  /studies/<id>/experiments/new            form + readiness table (GET fetches readiness per prompt)
POST /studies/<id>/experiments/new            execute experiment run (calls LLM APIs, stores results)
POST /experiments/<id>/delete                 delete a run (cascade); accepts ?next= redirect
GET  /experiments/<id>                        run detail — token results + efficiency metrics
GET  /experiments/<id>/pei                    PEI results for run (global + per script/morphology group)
GET  /experiments/<id>/queue-status           JSON live progress + per-model error summary
POST /experiments/<id>/stop                   cancel all pending items → run status = stopped
POST /experiments/<id>/restart                reset cancelled/error/timeout items → re-queue
POST /experiments/<id>/resume                 reset error/timeout items → re-queue (alias for no-stop flow)
POST /experiments/<id>/retry-models           retry errors for specific model_ids (form: model_ids list)
POST /experiments/<id>/retry-errors           retry all error/timeout items
POST /experiments/<id>/redo-model             redo all calls for one model (form: model_id, save_history)
POST /experiments/<id>/replace-model          swap one model for another (form: old_model_id, new_model_id, save_history)
POST /experiments/<id>/revalidate-status      recompute run status from DB state (fixes stuck runs)
POST /experiments/<id>/add-models             add new models to a completed/partial/stopped run
GET  /experiments/<id>/duplicate              pre-fill new-experiment form with same study/models/settings as an existing run
POST /experiments/<id>/update-notes           update run notes (JSON body: {notes: str}); returns JSON
POST /experiments/<id>/recompute-tokens       retroactively fix inflated visible_output_tokens via tiktoken heuristic
```

### POST /studies/{study_id}/experiments/new — Form Fields

```text
model_ids                  list[int]  models to call
repetitions                int        repetitions per cell (default 3, range 1–10)
force_magi                 "1"        force MAGI Phase 1 recomputation even if already computed
reasoning_override_<id>    ""         per-model reasoning override: "" = use model config,
                                       "on" = force reasoning ON, "off" = force reasoning OFF
                                       (one field per model_id; absent = use default)
```

Each (prompt × model × language) cell generates `repetitions` queue items with `repetition_index` 0..N−1.

### POST /experiments/{run_id}/add-models — Form Fields

```text
model_ids      list[int]  new model IDs to add (already-present models are silently skipped)
```

Only available when run status is `completed`, `partial`, or `stopped`. Builds payloads from the
frozen `run_translation_snapshot`; uses the same repetitions count as the original run.
PEI is not recomputed (it is independent of model calls).

## Settings

```text
GET  /settings                        settings dashboard
POST /settings/api-keys               save API keys
POST /settings/models                 update model list / cost config
POST /settings/reset-db               reset database (with confirmation)
```

## Reports

```text
GET  /reports                         reports dashboard (all studies + runs; bulk delete runs)
POST /reports/runs/bulk-delete        delete multiple runs (form field: run_ids CSV)
GET  /reports/export/csv              export run as CSV
GET  /reports/export/json             export run as JSON
GET  /reports/scores                  score visualization (PEI + MAGI Selection Scores)
GET  /reports/studies/<id>            per-study report (model efficiency summary + run list)
```

## Key Query Parameters

```text
/reports/export/csv?run_id=<id>
/reports/export/json?run_id=<id>
/reports/scores?run_id=<id>
```

## CSV Export Fields

```text
run_id, prompt_id, base_text, category, prompt_notes,
language_name, language_code, writing_system, script_group, morphology_group,
model_name, provider_name,
input_tokens, visible_output_tokens, reasoning_tokens,
tokenizer_drift, api_reported_output_tokens, ror,
is_reasoning_capable, reasoning_observed, reasoning_state,
reasoning_override_requested,
cost_visible_only, cost_reasoning, cost, visible_output_text_length,
token_accounting_mode, source, created_at,
pei, pei_band, script_group_count, morphology_group_count,
pei_groups_script_group (JSON), pei_groups_morphology_group (JSON),
ler_char, ler_token,
magi_score_absolute, magi_score_rank, magi_score_rank_pct,
magi_required, magi_score, magi_disagreement,
tsf_strategy
```

Note: `is_reasoning_model` has been replaced by three fields:

- `is_reasoning_capable` — from `models.is_reasoning` (static, per model definition)
- `reasoning_observed` — `reasoning_tokens > REASONING_THRESHOLD` (dynamic, per run result)
- `reasoning_state` — 4-way classification: `active` | `capable_but_inactive` | `anomaly` | `non_reasoning`

Note: `reasoning_override_requested` reflects the override stored in `token_results` (`"on"`, `"off"`, or NULL).

Note: `magi_judges` per-judge breakdown is available in JSON export only (nested object).

Note: `answer_correct`, `answer_in_target_language`, `language_leakage`, `olf_score`, `nepr_score` are stored in `token_results` but not yet included in the CSV export (available via direct DB query or JSON export).

Note: `tsf_strategy` is NULL for `analysis_type='standard'` prompts; populated only for `analysis_type='tsf'` prompts after the 3-judge panel runs. `tsf_judges` (per-judge audit trail JSON) is available in JSON export only (via `token_results` rows).

## JSON Export Structure

```json
{
  "run_notes": "",
  "token_results": [ /* one row per run×prompt×language×model */ ],
  "pei_results": [ /* one row per run×prompt */ ],
  "pei_group_results": [ /* one row per run×prompt×group */ ],
  "calibration_results": [ /* one row per run×calibration_prompt×language×model */ ],
  "baseline_rates": { /* per (model_name, language_id): token rate from clean long-prompt calibration trials */ },
  "prefix_caching_evidence": { /* per model cell: delta_ttft_first_vs_last */ },
  "timing_anomalies_count": { /* per model_name: count of timing_anomaly=True rows */ },
  "translation_scores": [
    {
      "prompt_id": 1,
      "language_id": 5,
      "language_name": "French",
      "language_code": "fr",
      "base_text": "…",
      "dsf": 0.97, "rtf": 0.96, "sfs": 0.968,
      "ler_char": 1.012, "ler_token": 1.024,
      "magi_score_absolute": 0.863,
      "magi_score_rank": 3,
      "magi_score_rank_pct": 0.78,
      "magi_required": 1,
      "magi_score": 0.973,
      "magi_disagreement": 0,
      "magi_judges": {
        "balthasar": { "model_name": "gpt-4o-mini", "semantic_fidelity": 5, "register_match": 4, "naturalness": 5, "score": 0.9167, "raw_response": "{...}", "error": null, "attempts": 1 },
        "caspar":    { "model_name": "gpt-4o-mini", "semantic_fidelity": 4, "register_match": 5, "naturalness": 5, "score": 0.9583, "raw_response": "{...}", "error": null, "attempts": 1 },
        "melchior":  { "model_name": "gpt-4o-mini", "semantic_fidelity": 5, "register_match": 5, "naturalness": 4, "score": 0.9167, "raw_response": "{...}", "error": null, "attempts": 1 }
      }
    }
  ]
}
```

Note: `calibration_results`, `baseline_rates`, `prefix_caching_evidence`, `timing_anomalies_count` are always present (empty when no calibration data).
`token_results` rows also include: `stream_close_source`, `had_retry_after`, `retry_after_sleep_ms`, `retry_count`, `request_timestamp_utc`, `cell_sequential_index`, `irrt_relative`, `irrt_absolute`.
