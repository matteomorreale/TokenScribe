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
│   │   ├── database.py          # DatabaseManager — connection + schema bootstrap
│   │   ├── study_model.py
│   │   ├── prompt_model.py
│   │   ├── translation_model.py
│   │   ├── experiment_model.py
│   │   └── settings_model.py
│   ├── services/                # Business logic layer
│   │   ├── llm_service.py       # Unified LLM provider interface
│   │   ├── scoring_service.py   # SFS (DSF+RTF) and PEI computation
│   │   ├── translation_service.py  # Translation candidate generation
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

**Study Management**
- controllers/study_controller.py
- models/study_model.py

**Prompt Management**
- controllers/prompt_controller.py
- models/prompt_model.py

**Translation Pipeline**
- controllers/translation_controller.py
- models/translation_model.py
- services/translation_service.py
- services/scoring_service.py

**Experiment Execution**
- controllers/experiment_controller.py
- models/experiment_model.py
- services/llm_service.py

**Settings & Configuration**
- controllers/settings_controller.py
- models/settings_model.py

**Reporting & Export**
- controllers/report_controller.py
- services/export_service.py

## Main Entry Points
- `run.py` — starts Flask dev server
- `app/__init__.py` — Flask app factory, registers all blueprints

## Primary Application Flows
1. Create study → add prompts → generate translation candidates → score (SFS) → approve
2. Run experiment → call LLM APIs → store token results (immutable)
3. Compute PEI across approved translations → visualize → export dataset

## External Dependencies
- sentence-transformers (local embeddings)
- tiktoken (neutral tokenizer for PEI)
- openai, anthropic, google-generativeai, mistralai (LLM providers)

## Files Agents Should Avoid Reading Unless Necessary
- instance/tokenscribe.db (binary)
- app/static/* (CSS/JS assets)
