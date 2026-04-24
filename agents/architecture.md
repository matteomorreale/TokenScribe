# TokenScribe — Architecture

## Folder Structure

```
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
│   │   ├── selection_score_model.py  # MAGI Selection Scores
│   │   └── settings_model.py
│   ├── services/                # Business logic layer
│   │   ├── llm_service.py       # Unified LLM provider interface (7 providers)
│   │   ├── scoring_service.py   # SFS (DSF+RTF), LER, PEI, MAGI computation
│   │   ├── translation_service.py  # AI translation candidate generation
│   │   └── export_service.py    # Dataset export (CSV, JSON)
│   ├── views/
│   │   └── templates/           # Jinja2 HTML templates (MVC Views)
│   │       ├── base.html
│   │       ├── index.html
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
├── tests/                       # Unit and integration tests
├── run.py                       # Entry point
├── config.py                    # Configuration classes
├── requirements.txt
├── agent.md
├── claude.md
└── README.md
```

## Core Modules

### Study Management

- controllers/study_controller.py
- models/study_model.py

### Prompt Management

- controllers/prompt_controller.py
- models/prompt_model.py

### Translation Pipeline

- controllers/translation_controller.py
- models/translation_model.py
- models/selection_score_model.py
- services/translation_service.py
- services/scoring_service.py

### Experiment Execution

- controllers/experiment_controller.py
- models/experiment_model.py
- services/llm_service.py

### Settings & Configuration

- controllers/settings_controller.py
- models/settings_model.py

### Reporting & Export

- controllers/report_controller.py
- services/export_service.py

## Key Service Methods

### ScoringService

- `score_translation(original, translation, back_translation)` → `{dsf, rtf, sfs, ler_char, ler_token}`
- `compute_ler(original, translation)` → `{ler_char, ler_token}`
- `compute_pei(texts)` → `{cv_char_length, cv_word_count, cv_token_count, pei}`
- `compute_selection_scores(candidates)` → mutates list, adds `score_absolute`, `score_rank`, `score_rank_pct`, `magi_required`
- `compute_structural_metrics(text)` → `{char_length, word_count, token_count}`
- `pei_band(pei)` → `"ottimo" | "plausibile" | "alto"`

### ExperimentModel

- `get_results_by_run(run_id)` — returns rows enriched with derived fields:
  `reasoning_tokens`, `cost_visible_only`, `ror`, `is_reasoning_model`
- `get_latest_pei_for_prompt(prompt_id)` — most recent PEI from any run (used by MAGI)

### SelectionScoreModel

- `upsert_scores(candidates)` — persists MAGI Phase 1 scores (ON CONFLICT UPDATE)
- `get_by_prompt(prompt_id)` → ranked list for one prompt
- `get_by_prompt_multi(prompt_ids)` → `{prompt_id: [candidates]}` for multiple prompts

## Main Entry Points

- `run.py` — starts Flask dev server
- `app/__init__.py` — Flask app factory, registers all blueprints

## Primary Application Flows

1. Create study → add prompts → generate candidates (AI or manual) → score SFS+LER → approve
2. Compute MAGI Selection Scores → rank candidates → flag `magi_required` for borderline cases
3. Run experiment → call LLM APIs → store token results (immutable) → compute PEI
4. Export dataset (CSV/JSON) with full enrichment (SFS, LER, PEI, MAGI, token efficiency metrics)

## External Dependencies

- sentence-transformers — local multilingual embeddings (paraphrase-multilingual-MiniLM-L12-v2)
- tiktoken — neutral tokenizer (cl100k_base) for PEI and visible_output_tokens
- openai, anthropic, google-generativeai, mistralai, dashscope (LLM providers)

## Files Agents Should Avoid Reading Unless Necessary

- instance/tokenscribe.db (binary SQLite)
- app/static/* (CSS/JS assets)
