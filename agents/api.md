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
```

## Prompts

```text
GET  /studies/<id>/prompts            list prompts for study
GET  /studies/<id>/prompts/new        form to add prompt
POST /studies/<id>/prompts/new        create prompt
GET  /prompts/<id>                    prompt detail — includes readiness semaphore widget
GET  /prompts/<id>/edit               edit form
POST /prompts/<id>/edit               update prompt
POST /prompts/<id>/delete             delete prompt
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
GET  /experiments                          list all runs
GET  /studies/<id>/experiments/new         form + readiness table (GET fetches readiness per prompt)
POST /studies/<id>/experiments/new         execute experiment run (calls LLM APIs, stores results)
POST /experiments/<id>/delete              delete a run (cascade); accepts ?next= redirect
GET  /experiments/<id>                     run detail — token results + efficiency metrics
GET  /experiments/<id>/pei                 PEI results for run (global + per script/morphology group)
```

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
run_id, prompt_id, base_text, category,
language_name, language_code, writing_system, script_group, morphology_group,
model_name, provider_name,
input_tokens, visible_output_tokens, reasoning_tokens,
api_reported_output_tokens, ror, is_reasoning_model,
cost_visible_only, cost, visible_output_text_length,
token_accounting_mode, source, created_at,
pei, pei_band, script_group_count, morphology_group_count,
pei_groups_script_group (JSON), pei_groups_morphology_group (JSON),
ler_char, ler_token,
magi_score_absolute, magi_score_rank, magi_score_rank_pct,
magi_required, magi_score, magi_disagreement
```

Note: `magi_judges` per-judge breakdown is available in JSON export only (nested object).

## JSON Export Structure

```json
{
  "token_results": [ /* one row per run×prompt×language×model */ ],
  "pei_results": [ /* one row per run×prompt */ ],
  "pei_group_results": [ /* one row per run×prompt×group */ ],
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
