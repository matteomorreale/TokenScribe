# TokenScribe — Task Tracker

```json
[
  {
    "task_id": "T001",
    "title": "Project scaffold and documentation",
    "status": "completed",
    "dependencies": [],
    "affected_modules": ["all"],
    "affected_files": ["agent.md", "claude.md", "agents/*", "config.py", "run.py", "requirements.txt"],
    "requires_db_changes": false,
    "notes_for_agent": "MVC structure, Flask MPA, SQLite, Vanilla JS, no Bootstrap"
  },
  {
    "task_id": "T002",
    "title": "Database schema and models",
    "status": "completed",
    "dependencies": ["T001"],
    "affected_modules": ["DatabaseManager", "StudyModel", "PromptModel", "TranslationModel", "ExperimentModel", "SettingsModel"],
    "affected_files": ["app/models/database.py", "app/models/*.py"],
    "requires_db_changes": false,
    "notes_for_agent": "Schema: writing_systems, languages, studies, prompts, translation_candidates, translation_scores, approved_translations, providers, models, experiment_runs, token_results, pei_results, settings. reset() excludes sqlite_* tables."
  },
  {
    "task_id": "T003",
    "title": "Flask controllers and routes",
    "status": "completed",
    "dependencies": ["T002"],
    "affected_modules": ["StudyController", "PromptController", "TranslationController", "ExperimentController", "SettingsController", "ReportController"],
    "affected_files": ["app/controllers/*.py", "app/__init__.py"],
    "requires_db_changes": false,
    "notes_for_agent": "All blueprints registered. Settings form fields: lang_name, lang_code, writing_system_id; model form fields: model_name (not 'name'), provider_id, context_window."
  },
  {
    "task_id": "T004",
    "title": "LLM provider integration",
    "status": "completed",
    "dependencies": ["T002"],
    "affected_modules": ["LLMService"],
    "affected_files": ["app/services/llm_service.py"],
    "requires_db_changes": false,
    "notes_for_agent": "7 providers: OpenAI, Anthropic, Google Gemini, DeepSeek, Meta/TogetherAI, Qwen/DashScope, Mistral. IMPORTANT: Mistral v2 SDK uses 'from mistralai.client.sdk import Mistral'."
  },
  {
    "task_id": "T005",
    "title": "SFS and PEI scoring services",
    "status": "completed",
    "dependencies": ["T002"],
    "affected_modules": ["ScoringService"],
    "affected_files": ["app/services/scoring_service.py"],
    "requires_db_changes": false,
    "notes_for_agent": "SFS = 0.7*DSF + 0.3*RTF. PEI = mean(CV_char, CV_word, CV_token). Model: paraphrase-multilingual-MiniLM-L12-v2 (lazy loaded)."
  },
  {
    "task_id": "T006",
    "title": "Frontend MPA templates",
    "status": "completed",
    "dependencies": ["T003"],
    "affected_modules": ["Views"],
    "affected_files": ["app/views/templates/**", "app/static/css/*", "app/static/js/*"],
    "requires_db_changes": false,
    "notes_for_agent": "Modern CSS design system with --ts-* CSS variables. Side-by-side comparison, score bars, modal for AI responses."
  },
  {
    "task_id": "T007",
    "title": "Integration testing and bug fixes",
    "status": "completed",
    "dependencies": ["T006"],
    "affected_modules": ["all"],
    "affected_files": ["app/models/database.py", "app/services/llm_service.py"],
    "requires_db_changes": false,
    "notes_for_agent": "Bugs fixed: (1) reset() SQLite table exclusion (sqlite_sequence), (2) Mistral SDK import path."
  },
  {
    "task_id": "T008",
    "title": "LER metric (Length Expansion Ratio)",
    "status": "completed",
    "dependencies": ["T005"],
    "affected_modules": ["ScoringService", "TranslationModel", "TranslationController", "ExportService"],
    "affected_files": [
      "app/models/database.py",
      "app/services/scoring_service.py",
      "app/models/translation_model.py",
      "app/controllers/translation_controller.py",
      "app/services/export_service.py",
      "app/controllers/report_controller.py",
      "app/views/templates/translations/list.html",
      "app/views/templates/translations/compare.html",
      "app/views/templates/prompts/detail.html"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "ler_char and ler_token added to translation_scores via migration. LER = len(translation)/len(original). Stored alongside SFS. Displayed in list/compare/detail templates and included in CSV/JSON exports."
  },
  {
    "task_id": "T009",
    "title": "Token efficiency metrics: visible_output_tokens, reasoning_tokens, ROR",
    "status": "completed",
    "dependencies": ["T007"],
    "affected_modules": ["ExperimentModel", "ExperimentController", "ExportService"],
    "affected_files": [
      "app/models/database.py",
      "app/models/experiment_model.py",
      "app/controllers/experiment_controller.py",
      "app/services/export_service.py",
      "app/views/templates/experiments/detail.html",
      "app/views/templates/reports/study_report.html",
      "app/views/templates/reports/scores.html"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "New DB columns: visible_output_tokens, normalized_output_tokens (alias), api_reported_output_tokens. Derived fields computed in get_results_by_run() Python loop (NOT stored): reasoning_tokens, cost_visible_only, ror, is_reasoning_model. Bug fixed: Jinja sum filter on NULL values — always replace None with 0 before appending to results list. Uses tiktoken cl100k_base for all models; note non-OpenAI models may show small non-zero reasoning_tokens due to tokenizer mismatch."
  },
  {
    "task_id": "T010",
    "title": "JSON/CSV export enrichment with translation_scores (DSF, RTF, SFS, LER)",
    "status": "completed",
    "dependencies": ["T008"],
    "affected_modules": ["ReportController", "ExperimentModel", "ExportService"],
    "affected_files": [
      "app/models/experiment_model.py",
      "app/controllers/report_controller.py",
      "app/services/export_service.py"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "get_translation_scores_by_run() joins through approved_translations to fetch DSF, RTF, SFS, LER per (prompt_id, language_id). Both export_csv() and export_json() now call this and pass translation_scores to ExportService."
  },
  {
    "task_id": "T011",
    "title": "MAGI Selection Score — Phase 1",
    "status": "completed",
    "dependencies": ["T008", "T009"],
    "affected_modules": ["ScoringService", "SelectionScoreModel", "ExperimentModel", "TranslationController", "ReportController"],
    "affected_files": [
      "app/models/database.py",
      "app/services/scoring_service.py",
      "app/models/selection_score_model.py",
      "app/models/__init__.py",
      "app/models/experiment_model.py",
      "app/controllers/translation_controller.py",
      "app/controllers/report_controller.py",
      "app/views/templates/translations/list.html",
      "app/views/templates/reports/scores.html"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "New table: selection_score_results. Formula: score_absolute = SFS − 0.5*PEI − 0.5*|LER_char−1|. Divergence: magi_required = rank > max(1, floor(n/4)). PEI used is the most recent from experiment_runs for that prompt (get_latest_pei_for_prompt). Endpoint: POST /prompts/{prompt_id}/selection-scores. Button 'Compute MAGI Scores' in translations/list.html topbar. Display in reports/scores.html after PEI section. Phase 2 (LLM panel: Balthasar/Casper/Melchior) not yet implemented."
  }
]
```
