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
GET  /prompts/<id>                    prompt detail with translation candidates
GET  /prompts/<id>/edit               edit form
POST /prompts/<id>/edit               update prompt
POST /prompts/<id>/delete             delete prompt
```

## Translations

```text
GET  /prompts/<id>/translations                   list candidates (with MAGI scores if computed)
GET  /prompts/<id>/translations/new               form to add candidate manually
POST /prompts/<id>/translations/new               create candidate
POST /prompts/<id>/translations/ai-translate      generate candidates via LLM (bulk AI flow)
GET  /prompts/<id>/translations/compare           side-by-side comparison view
POST /prompts/<id>/selection-scores               compute MAGI Phase 1 scores for all candidates

POST /translations/<id>/score                     compute SFS + LER for one candidate
POST /translations/<id>/approve                   approve candidate
POST /translations/<id>/reject                    reject candidate
POST /translations/<id>/delete                    delete candidate
POST /prompts/<id>/translations/bulk-approve      bulk approve selected candidate_ids
POST /prompts/<id>/translations/bulk-reject       bulk reject selected candidate_ids
POST /prompts/<id>/translations/bulk-delete       bulk delete selected candidate_ids
```

## Experiments

```text
GET  /experiments                     list all runs
GET  /studies/<id>/experiments/new    form to configure experiment run
POST /studies/<id>/experiments/run    execute experiment run (calls LLM APIs, stores token_results)
GET  /experiments/<id>                run detail — token results table with all efficiency metrics
GET  /experiments/<id>/pei            PEI results for run (global + per-group)
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
GET  /reports                         reports dashboard (all studies + runs)
GET  /reports/export/csv              export run as CSV (enriched with PEI, LER, MAGI)
GET  /reports/export/json             export run as JSON (enriched with all metrics)
GET  /reports/scores                  score visualization page (PEI + MAGI Selection Scores)
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
ler_char, ler_token
```
