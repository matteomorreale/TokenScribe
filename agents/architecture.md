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
│   │   ├── selection_score_model.py  # MAGI Phase 1 + readiness semaphore
│   │   └── settings_model.py
│   ├── services/                # Business logic layer
│   │   ├── llm_service.py       # Unified LLM provider interface (7 providers)
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

- controllers/translation_controller.py — includes `ai_translate()` for AI candidate generation (uses gpt-5)
- models/translation_model.py
- models/selection_score_model.py
- services/scoring_service.py
- services/magi_service.py

### Experiment Execution

- controllers/experiment_controller.py — create/delete runs; readiness check on GET /new
- models/experiment_model.py
- services/llm_service.py

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

### SelectionScoreModel

- `upsert_scores(candidates)` — persists MAGI Phase 1 scores; resets magi_score/magi_judges on recompute
- `update_magi_result(candidate_id, magi_score, magi_disagreement, magi_judges)` — persists Phase 2
- `get_by_prompt(prompt_id)` → ranked list; `magi_judges` JSON deserialized to dict
- `get_by_prompt_multi(prompt_ids)` → `{prompt_id: [candidates]}`; `magi_judges` deserialized
- `get_readiness_by_prompts(prompt_ids)` → `{prompt_id: {approved_count, scored_count, magi_count, magi_required_count, judge_count, status}}`
  — `status`: `"green"` | `"yellow"` | `"red"` (see agent.md for logic)

### ExperimentModel

- `get_results_by_run(run_id)` — rows enriched with: `reasoning_tokens`, `cost_visible_only`, `ror`, `is_reasoning_model`
- `get_translation_scores_by_run(run_id)` — joins `run_translation_snapshot` → immune to re-approvals;
  includes all MAGI fields; `magi_judges` deserialized to dict before returning
- `get_latest_pei_for_prompt(prompt_id)` — most recent PEI from any run (used by MAGI Phase 1)
- `snapshot_translations(run_id, study_id)` — freezes approved translations at run start
- `delete_run(run_id)` / `delete_runs_bulk(run_ids)` — cascade-deletes token_results

## UX Patterns

### Loading States

`data-loading="…"` on any `<button type="submit">` triggers automatic loading feedback on form
submit: button is disabled, `.ts-btn-loading` CSS class adds a spinning border-circle via `::before`,
text changes to the `data-loading` value. Implemented in `tokenscribe.js` as a global form listener.

### Judge Tooltips

`.ts-judge-cell` + `.ts-judge-tooltip` CSS pattern in `translations/list.html`.
On hover, shows: judge name, model name, score, attempt count, error reason, raw LLM response.
`magi_judges` JSON must be deserialized before reaching the template (done in model layer).

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

## External Dependencies

- sentence-transformers — local multilingual embeddings (paraphrase-multilingual-MiniLM-L12-v2)
- tiktoken — neutral tokenizer (cl100k_base) for PEI and visible_output_tokens
- openai, anthropic, google-generativeai, mistralai, dashscope (LLM providers)

## Files Agents Should Avoid Reading Unless Necessary

- instance/tokenscribe.db (binary SQLite)
- app/static/* (CSS/JS assets)
