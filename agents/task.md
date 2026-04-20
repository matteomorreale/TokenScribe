[
  {
    "task_id": "T001",
    "title": "Project scaffold and documentation",
    "status": "completed",
    "dependencies": [],
    "affected_modules": ["all"],
    "affected_files": ["agent.md", "claude.md", "agents/*", "config.py", "run.py", "requirements.txt"],
    "requires_db_changes": false,
    "requires_api_changes": false,
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
    "requires_api_changes": false,
    "notes_for_agent": "Schema: writing_systems, languages, studies, prompts, translation_candidates, translation_scores, approved_translations, providers, models, experiment_runs, token_results, pei_results, settings. Fix applied: reset() now excludes sqlite_* tables."
  },
  {
    "task_id": "T003",
    "title": "Flask controllers and routes",
    "status": "completed",
    "dependencies": ["T002"],
    "affected_modules": ["StudyController", "PromptController", "TranslationController", "ExperimentController", "SettingsController", "ReportController"],
    "affected_files": ["app/controllers/*.py", "app/__init__.py"],
    "requires_db_changes": false,
    "requires_api_changes": false,
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
    "requires_api_changes": false,
    "notes_for_agent": "7 providers: OpenAI, Anthropic, Google Gemini, DeepSeek, Meta/TogetherAI, Qwen/DashScope, Mistral. IMPORTANT: Mistral v2 SDK uses 'from mistralai.client.sdk import Mistral' (not 'from mistralai import Mistral')."
  },
  {
    "task_id": "T005",
    "title": "SFS and PEI scoring services",
    "status": "completed",
    "dependencies": ["T002"],
    "affected_modules": ["ScoringService"],
    "affected_files": ["app/services/scoring_service.py"],
    "requires_db_changes": false,
    "requires_api_changes": false,
    "notes_for_agent": "SFS = 0.7*DSF + 0.3*RTF. PEI = CV across char_length, word_count, tiktoken count. Model: paraphrase-multilingual-MiniLM-L12-v2 (lazy loaded). Tested and working."
  },
  {
    "task_id": "T006",
    "title": "Frontend MPA templates",
    "status": "completed",
    "dependencies": ["T003"],
    "affected_modules": ["Views"],
    "affected_files": ["app/views/templates/**", "app/static/css/*", "app/static/js/*"],
    "requires_db_changes": false,
    "requires_api_changes": false,
    "notes_for_agent": "Modern CSS design system with --ts-* CSS variables. Side-by-side translation comparison. Score visualizations. All templates tested."
  },
  {
    "task_id": "T007",
    "title": "Integration testing and bug fixes",
    "status": "completed",
    "dependencies": ["T006"],
    "affected_modules": ["all"],
    "affected_files": ["app/models/database.py", "app/services/llm_service.py", "requirements.txt"],
    "requires_db_changes": false,
    "requires_api_changes": false,
    "notes_for_agent": "Bugs fixed: (1) reset() SQLite table exclusion (sqlite_sequence), (2) Mistral SDK import path. All core flows tested and passing."
  }
]
