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
    "notes_for_agent": "New DB columns: visible_output_tokens, normalized_output_tokens (alias), api_reported_output_tokens. Derived fields computed in get_results_by_run() Python loop (NOT stored): reasoning_tokens, cost_visible_only, ror, is_reasoning_model. Uses tiktoken cl100k_base for all models."
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
    "notes_for_agent": "get_translation_scores_by_run() joins through run_translation_snapshot (not approved_translations) to fetch DSF, RTF, SFS, LER per (prompt_id, language_id). Both export_csv() and export_json() call this and pass translation_scores to ExportService."
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
    "notes_for_agent": "New table: selection_score_results (UNIQUE candidate_id). Formula: score_absolute = SFS − 0.5*PEI − 0.5*|LER_char−1|. magi_required = rank > max(1, floor(n/4)). PEI used: get_latest_pei_for_prompt(). upsert_scores() resets magi_score/magi_judges to NULL on recompute."
  },
  {
    "task_id": "T012",
    "title": "MAGI Phase 2 — LLM judge panel (Balthasar, Caspar, Melchior)",
    "status": "completed",
    "dependencies": ["T011"],
    "affected_modules": ["MAGIService", "SelectionScoreModel", "TranslationController", "ExportService", "ExperimentModel"],
    "affected_files": [
      "app/services/magi_service.py",
      "app/services/__init__.py",
      "app/models/database.py",
      "app/models/selection_score_model.py",
      "app/models/experiment_model.py",
      "app/controllers/translation_controller.py",
      "app/services/export_service.py",
      "app/views/templates/translations/list.html"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "New DB columns on selection_score_results: magi_score REAL, magi_disagreement INT, magi_judges TEXT (JSON). New service: MAGIService with evaluate() (3 retries), run_panel() (3 judges), _parse_score() (3-pass). Judge prompt uses structured sections + output examples to handle reasoning models. Per-judge verdict: {model_id, model_name, score, raw_response, error, attempts}. magi_judges deserialized in both get_by_prompt() and get_translation_scores_by_run() so templates and exports always get a dict. JSON export includes magi_judges as nested object. MAGI modal in translations/list.html: candidate checkboxes + filter buttons (All/Non-rejected/Approved) + Phase 2 toggle + 3 model selectors. MAGI Results card below candidates table with per-judge B/C/M columns and disagreement flag ↯."
  },
  {
    "task_id": "T013",
    "title": "Pre-run readiness semaphore",
    "status": "completed",
    "dependencies": ["T012"],
    "affected_modules": ["SelectionScoreModel", "PromptController", "ExperimentController"],
    "affected_files": [
      "app/models/selection_score_model.py",
      "app/controllers/prompt_controller.py",
      "app/controllers/experiment_controller.py",
      "app/views/templates/prompts/detail.html",
      "app/views/templates/experiments/new.html"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "get_readiness_by_prompts(prompt_ids) aggregates approved_count, scored_count, magi_count, magi_required_count, judge_count and computes status (green/yellow/red). prompts/detail.html shows a card with colored left border and stat row. experiments/new.html replaces static prompt list with a readiness table (Approved/SFS/MAGI/Judge↯/Status columns) and a red banner if any prompt has no approved translations."
  },
  {
    "task_id": "T014",
    "title": "Delete experiments + bulk delete reports",
    "status": "completed",
    "dependencies": ["T003"],
    "affected_modules": ["ExperimentController", "ReportController", "ExperimentModel"],
    "affected_files": [
      "app/models/experiment_model.py",
      "app/controllers/experiment_controller.py",
      "app/controllers/report_controller.py",
      "app/views/templates/experiments/list.html",
      "app/views/templates/reports/dashboard.html"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "POST /experiments/{run_id}/delete accepts optional 'next' form param for redirect. POST /reports/runs/bulk-delete accepts 'run_ids' (comma-separated). Bulk delete JS in dashboard.html is standalone (does not reuse data-ts-candidate-id mechanism) to avoid collision with translation bulk actions."
  },
  {
    "task_id": "T015",
    "title": "UX — loading states on action buttons",
    "status": "completed",
    "dependencies": ["T006"],
    "affected_modules": ["Views"],
    "affected_files": [
      "app/static/css/tokenscribe.css",
      "app/static/js/tokenscribe.js",
      "app/views/templates/experiments/new.html",
      "app/views/templates/translations/list.html",
      "app/views/templates/prompts/detail.html"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "Global form submit listener in tokenscribe.js finds button[data-loading] and applies: disabled=true, .ts-btn-loading class (CSS spinner via ::before), text=data-loading value. CSS: @keyframes ts-spin + .ts-btn-loading. Buttons annotated: Run Experiment, Calcola MAGI Scores, Score SFS, Genera traduzioni, Score."
  },
  {
    "task_id": "T016",
    "title": "MAGI judge tooltip with raw response",
    "status": "completed",
    "dependencies": ["T012"],
    "affected_modules": ["MAGIService", "Views"],
    "affected_files": [
      "app/services/magi_service.py",
      "app/static/css/tokenscribe.css",
      "app/views/templates/translations/list.html"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "MAGIService.evaluate() now stores raw_response (LLM response text) and attempts count in verdict dict. Three error cases: 'Parse failed: no valid 0–1 score found in response', 'API error: ...', 'Exception: ...'. CSS: .ts-judge-cell (position:relative) + .ts-judge-tooltip (position:absolute, display:none, shown on :hover). Tooltip content: judge name, model, score, attempts, error, raw_response (truncated 200 chars). Failed judge — shown as styled with underline dotted. Old records without raw_response show 'n/a (record predates raw logging)'."
  },
  {
    "task_id": "T017",
    "title": "MAGI retry logic and improved score parsing",
    "status": "completed",
    "dependencies": ["T016"],
    "affected_modules": ["MAGIService"],
    "affected_files": ["app/services/magi_service.py"],
    "requires_db_changes": false,
    "notes_for_agent": "evaluate() retries up to MAX_RETRIES=3 via _call_once(). Returns on first successful parse; on all failures returns last verdict. _parse_score() three-pass: (1) bare number as full response, (2) first 0.xx/1.0x decimal in text with (?<!/) lookbehind to skip denominators, (3) standalone 0 or 1. Judge prompt rewritten with structured sections (## Input, ## Task, ## Output format MANDATORY) and four valid-response examples. logging.getLogger(__name__) logs each verdict at INFO (success) or WARNING (failure) with raw response repr."
  },
  {
    "task_id": "T018",
    "title": "Reasoning model capability flag + 4-way reasoning_state classification",
    "status": "completed",
    "dependencies": ["T009"],
    "affected_modules": ["DatabaseManager", "ExperimentModel", "ExportService", "ReportController"],
    "affected_files": [
      "app/models/database.py",
      "app/models/experiment_model.py",
      "app/services/export_service.py",
      "app/views/templates/reports/study_report.html",
      "config.py"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "New column models.is_reasoning (INT 0/1). DEFAULT_MODELS in config.py now carries is_reasoning per entry. get_results_by_run() derives reasoning_state (active|capable_but_inactive|anomaly|non_reasoning) by crossing is_reasoning_capable (from DB) with reasoning_observed (runtime threshold). anomaly state logs WARNING. CSV export replaces is_reasoning_model with is_reasoning_capable + reasoning_observed + reasoning_state. study_report.html column renamed to 'Reasoning Active', uses reasoning_observed."
  },
  {
    "task_id": "T019",
    "title": "PEI snapshot on prompts + staleness indicator",
    "status": "completed",
    "dependencies": ["T011"],
    "affected_modules": ["DatabaseManager", "PromptModel", "PromptController", "TranslationController"],
    "affected_files": [
      "app/models/database.py",
      "app/models/prompt_model.py",
      "app/controllers/prompt_controller.py",
      "app/controllers/translation_controller.py",
      "app/views/templates/prompts/detail.html"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "New columns on prompts: pei_value, pei_cv_char, pei_cv_word, pei_cv_token, pei_saved_at. PromptModel.save_pei_snapshot() writes these. compute_selection_scores() now computes PEI fresh from approved translations (not ExperimentModel fallback first) and saves snapshot automatically. POST /prompts/<id>/pei/refresh is a standalone manual refresh endpoint. detail.html shows warning badge + message when pei_saved_at < MAX(approved_at) (pei_stale flag from controller)."
  },
  {
    "task_id": "T020",
    "title": "Prompt notes field",
    "status": "completed",
    "dependencies": ["T002"],
    "affected_modules": ["DatabaseManager", "PromptModel", "PromptController"],
    "affected_files": [
      "app/models/database.py",
      "app/models/prompt_model.py",
      "app/controllers/prompt_controller.py",
      "app/views/templates/prompts/form.html",
      "app/views/templates/prompts/detail.html"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "New column prompts.notes TEXT. create() and update() accept notes param. POST /prompts/<id>/notes is a quick inline save on the detail page. Notes are included in get_results_by_run() as prompt_notes and propagated to CSV export."
  },
  {
    "task_id": "T021",
    "title": "Translation candidate edit + per-prompt JSON export",
    "status": "completed",
    "dependencies": ["T003", "T008"],
    "affected_modules": ["TranslationModel", "TranslationController"],
    "affected_files": [
      "app/models/translation_model.py",
      "app/controllers/translation_controller.py",
      "app/views/templates/translations/form.html",
      "app/views/templates/prompts/detail.html"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "GET/POST /translations/<id>/edit reuses translations/form.html with editing=True; language is shown read-only. TranslationModel.update_candidate_text() updates text only. GET /prompts/<id>/translations/export.json returns a JSON attachment with study, prompt, and all candidates+scores+MAGI data via get_candidates_for_export(). View modal on detail.html uses data-ts-view-text / data-ts-view-title attributes."
  }
  ,
  {
    "task_id": "T022",
    "title": "Async run queue — QueueModel + QueueService",
    "status": "completed",
    "dependencies": ["T004", "T007"],
    "affected_modules": ["QueueModel", "QueueService", "ExperimentController"],
    "affected_files": [
      "app/models/queue_model.py",
      "app/services/queue_service.py",
      "app/models/database.py"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "New table: run_queue. QueueService is a daemon thread (ts-queue-worker) started in app factory. Dispatches: llm_call, magi_phase2, compute_pei, finalize_pei_groups, snapshot_translations. Each item runs in a ThreadPoolExecutor with per-type timeouts (_TIMEOUTS dict). Item payload embeds all data the worker needs (model_name, provider, text, etc.) so no DB join is needed at dequeue time. QueueModel.recompute_run_status() re-derives experiment_runs.status after each item completes."
  },
  {
    "task_id": "T023",
    "title": "LLM resilience: model_not_found fallback + Qwen region setting",
    "status": "completed",
    "dependencies": ["T022"],
    "affected_modules": ["LLMService", "QueueService", "SettingsController"],
    "affected_files": [
      "app/services/llm_service.py",
      "app/services/queue_service.py",
      "app/controllers/settings_controller.py",
      "app/views/templates/settings/dashboard.html",
      "config.py"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "TokenScribeCallResult gains model_not_found: bool. _is_model_not_found(str) detects 404/deprecation across all providers (not_found_error, error code: 404 + model, no longer available, startswith 404). QueueService._get_fallback_model(provider, exclude_id, original_name) selects same-tier replacement (flash→flash, sonnet→sonnet, turbo→turbo, etc.) from active models; updates model_id in token_results insert to avoid FK violation. Qwen region: new settings key qwen_region (china|international) selects between dashscope.aliyuncs.com and dashscope-intl.aliyuncs.com. Saved via save_api_keys route. Settings dashboard has a select dropdown. Removed invalid models: claude-sonnet-4 and claude-opus-4 (no version suffix). Deactivated: gemini-2.0-flash (deprecated by Google, no longer available to new users)."
  }
  ,
  {
    "task_id": "T024",
    "title": "Pricing unit migration: $/token → $/million tokens",
    "status": "completed",
    "dependencies": ["T022"],
    "affected_modules": ["DatabaseManager", "LLMService", "ExperimentModel", "SettingsController"],
    "affected_files": [
      "config.py",
      "app/models/database.py",
      "app/services/llm_service.py",
      "app/models/experiment_model.py",
      "app/views/templates/settings/dashboard.html"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "models.cost_per_input_token and cost_per_output_token now store USD per million tokens ($/M), not per single token. One-shot migration in _migrate_schema() multiplies all non-zero values × 1_000_000; guarded by settings key pricing_unit='per_million' so it never runs twice. config.py DEFAULT_MODELS updated to per-million values. Cost calculations in llm_service.py and experiment_model.get_results_by_run() divide by 1_000_000. Settings UI headers changed to '$/M input tokens' / '$/M output tokens'; step='0.001'. The stored token_results.cost column is not touched (was correct at insert time and is anyway overwritten by the dynamic recomputation)."
  }
  ,
  {
    "task_id": "T026",
    "title": "CryptoService — Fernet encryption for API keys at rest",
    "status": "completed",
    "dependencies": ["T003"],
    "affected_modules": ["CryptoService", "SettingsModel", "SettingsController"],
    "affected_files": [
      "app/services/crypto_service.py",
      "app/services/__init__.py",
      "app/models/settings_model.py",
      "app/controllers/settings_controller.py",
      "requirements.txt"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "New service: CryptoService wraps Fernet (AES-128-CBC + HMAC-SHA256). Key read from TOKENSCRIBE_ENCRYPTION_KEY env var; auto-generated and appended to .env on first run. SettingsModel accepts optional crypto param; _ENCRYPTED_KEYS frozenset lists all *_api_key keys. _enc()/_dec() called transparently in get/set/set_many/get_all. Transparent migration: decrypt() returns value unchanged on InvalidToken, allowing pre-encryption plain-text values to be read without error."
  }
  ,
  {
    "task_id": "T027",
    "title": "Repetition parameter + token_results schema updates (repetition_index, attempt_index, response_valid)",
    "status": "completed",
    "dependencies": ["T022"],
    "affected_modules": ["DatabaseManager", "ExperimentModel", "ExperimentController", "QueueService"],
    "affected_files": [
      "app/models/database.py",
      "app/models/experiment_model.py",
      "app/controllers/experiment_controller.py",
      "app/services/queue_service.py"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "New columns on token_results: repetition_index INT NOT NULL DEFAULT 0, attempt_index INT NOT NULL DEFAULT 0 (auto-incremented atomically via MAX+1 subquery in insert), attempt_status TEXT NOT NULL DEFAULT 'success', response_valid INT NOT NULL DEFAULT 1. Old 4-col unique index replaced by 6-col (run_id, prompt_id, language_id, model_id, repetition_index, attempt_index). ExperimentController reads 'repetitions' form field (1–10, default 3); enqueues N items per cell with repetition_index 0..N-1. insert_token_result() derives response_valid automatically. get_results_by_run() uses CTE to filter attempt_status='success' and MAX(attempt_index) per cell."
  }
  ,
  {
    "task_id": "T028",
    "title": "Run stop/restart functionality + revalidate-status",
    "status": "completed",
    "dependencies": ["T022"],
    "affected_modules": ["QueueModel", "RunController"],
    "affected_files": [
      "app/models/queue_model.py",
      "app/controllers/run_controller.py",
      "app/views/templates/experiments/detail.html"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "New run status: 'stopped'. New item status: 'cancelled'. New QueueModel methods: cancel_pending_items() marks all pending items cancelled; restart_stopped_run() resets cancelled/error/timeout/running items to pending; recover_stale_running() resets items stuck in 'running' after crash. New RunController endpoints: POST /experiments/<id>/stop (cancel_pending + set stopped), POST /experiments/<id>/restart (restart_stopped_run + set queued), POST /experiments/<id>/revalidate-status (recompute_run_status). detail.html shows Stop and Restart buttons based on run status."
  }
  ,
  {
    "task_id": "T029",
    "title": "MAGI repair — bulk regen-magi at study level",
    "status": "completed",
    "dependencies": ["T012", "T022"],
    "affected_modules": ["StudyController", "ExperimentModel", "SelectionScoreModel", "MAGIService"],
    "affected_files": [
      "app/controllers/study_controller.py",
      "app/views/templates/studies/detail.html"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "GET /studies/<id>/magi-repair-status returns JSON {active, run_id, run_status, progress} for the most recent run with notes='[MAGI repair]' and status in (queued, running). POST /studies/<id>/regen-magi creates a dedicated experiment_run with notes='[MAGI repair]', re-computes Phase 1 for all approved+scored candidates of the selected (or all) prompts, then enqueues Phase 2 magi_phase2 items if all 3 judges are configured. study detail.html shows a 'Rigenera MAGI' panel with prompt checkboxes, live progress bar polling magi-repair-status, and a Stop button."
  }
  ,
  {
    "task_id": "T025",
    "title": "Redo / Replace model calls on completed or partial runs",
    "status": "completed",
    "dependencies": ["T022"],
    "affected_modules": ["DatabaseManager", "ExperimentModel", "QueueModel", "RunController", "ExperimentController", "Views"],
    "affected_files": [
      "app/models/database.py",
      "app/models/experiment_model.py",
      "app/models/queue_model.py",
      "app/controllers/run_controller.py",
      "app/controllers/experiment_controller.py",
      "app/views/templates/experiments/detail.html"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "New table: run_history (run_id, model_id, model_name, reason, replaced_by_model_id, replaced_by_model_name, results_json). Created via CREATE TABLE IF NOT EXISTS in both _create_tables() and _migrate_schema() guard. New ExperimentModel methods: archive_model_results(), delete_model_results(), get_run_history(), reconstruct_llm_payloads(). New QueueModel methods: get_model_llm_payloads(), redo_model_items(), replace_model_items(). reconstruct_llm_payloads() handles legacy runs (no queue items) by rebuilding payloads from token_results + run_translation_snapshot. New controller endpoints: POST /experiments/<id>/redo-model, POST /experiments/<id>/replace-model — both accept save_history=1 checkbox. detail.html: 'Gestione Modelli' card (visible on completed/partial), per-model Rifai/Sostituisci buttons, modal-redo and modal-replace modals, 'Storico Archivi' card. all_models and run_history now passed to detail template. PEI is NOT recomputed on redo/replace (it is independent of model calls)."
  }
  ,
  {
    "task_id": "T030",
    "title": "xAI (Grok) provider + Responses API fallback + rate-limit requeue + add-models endpoint",
    "status": "completed",
    "dependencies": ["T023", "T022", "T025"],
    "affected_modules": ["LLMService", "QueueService", "QueueModel", "RunController", "ExperimentModel", "SettingsController", "Config"],
    "affected_files": [
      "app/services/llm_service.py",
      "app/services/queue_service.py",
      "app/models/queue_model.py",
      "app/models/experiment_model.py",
      "app/controllers/run_controller.py",
      "app/controllers/settings_controller.py",
      "config.py"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "1) xAI/Grok: 8th provider (PROVIDER_XAI='xai'); _call_xai() uses openai SDK at https://api.x.ai/v1; reasoning support (grok-3-mini); xai_api_key settings key. 2) Responses API fallback: _call_openai() catches 'not a chat model'/'v1/completions' error and retries via _call_openai_responses() (client.responses.create with reasoning.effort='high'/'medium'); handles gpt-5.4-pro. 3) Rate-limit handling: _is_rate_limited() added; TokenScribeCallResult.rate_limited field; QueueService raises RateLimitError on rate-limited results; worker catches it and calls QueueModel.requeue_at_end() (delete+reinsert with new auto-increment id so item goes to queue tail; max_retries=10). 4) add-models endpoint: POST /experiments/<id>/add-models on completed/partial/stopped runs; ExperimentModel.get_run_model_ids() and build_llm_payloads_from_snapshot(run_id, model_id, repetitions) build payloads from frozen run_translation_snapshot; QueueModel.get_run_repetitions() reads repetition count. 5) Model catalog update: OpenAI gpt-5.5, gpt-5.5-pro, gpt-5.4-pro, gpt-5.4, gpt-5.4-mini, gpt-5.4-nano, gpt-4.1, gpt-4.1-mini, gpt-4.1-nano; Anthropic claude-opus-4-7, claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5; Google gemini-2.5-pro, gemini-2.5-flash, gemini-2.5-flash-lite; DeepSeek deepseek-v4-pro/flash; Meta Llama-4 Scout/Maverick; Qwen qwen3 family; Mistral magistral-medium/small; xAI grok-3 family. force_magi param added to new experiment form."
  }
  ,
  {
    "task_id": "T031",
    "title": "Run notes — inline edit on experiment detail",
    "status": "completed",
    "dependencies": ["T022"],
    "affected_modules": ["ExperimentModel", "RunController", "ExportService", "Views"],
    "affected_files": [
      "app/models/experiment_model.py",
      "app/controllers/run_controller.py",
      "app/services/export_service.py",
      "app/views/templates/experiments/detail.html"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "ExperimentModel.update_run_notes(run_id, notes) updates experiment_runs.notes in place. New endpoint: POST /experiments/<id>/update-notes (JSON body {notes: str}; returns JSON {ok: true}). Inline editor in detail.html uses fetch() to save without a page reload. ExportService.export_json() accepts run_notes kwarg and emits 'run_notes' as a top-level field in the dataset envelope."
  }
  ,
  {
    "task_id": "T032",
    "title": "Inflated API token heuristic + retroactive recompute-tokens endpoint",
    "status": "completed",
    "dependencies": ["T027", "T022"],
    "affected_modules": ["QueueService", "ExperimentModel", "RunController", "Views"],
    "affected_files": [
      "app/services/queue_service.py",
      "app/models/experiment_model.py",
      "app/controllers/run_controller.py",
      "app/views/templates/experiments/detail.html"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "Some providers (notably Qwen reasoning models) bundle undisclosed reasoning tokens into completion_tokens. Detection: api_output / max(1, len(response_text)) > threshold. Thresholds: 1.5 for logographic scripts (zh/ja/ko + variants), 2.0 for all others. When triggered, visible_output_tokens is set to tiktoken cl100k_base count of response_text; reasoning_tokens recalculated as max(0, api_output - local_toks). Applied live in QueueService._exec_llm_call() and retroactively via ExperimentModel.recompute_visible_tokens(run_id) which returns {checked, updated, skipped, unchanged}. New endpoint: POST /experiments/<id>/recompute-tokens (returns JSON summary). Button added to detail.html for manual trigger."
  }
  ,
  {
    "task_id": "T033",
    "title": "Reasoning override per model in experiment creation",
    "status": "completed",
    "dependencies": ["T004", "T022"],
    "affected_modules": ["ExperimentController", "QueueService", "LLMService", "Views"],
    "affected_files": [
      "app/controllers/experiment_controller.py",
      "app/services/queue_service.py",
      "app/services/llm_service.py",
      "app/views/templates/experiments/new.html"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "New form fields: reasoning_override_<model_id> per model (''/on/off). ExperimentController reads them into reasoning_overrides dict and stores value in each llm_call payload as reasoning_override. QueueService._exec_llm_call() reads override from payload before calling LLM; 'on' sets is_reasoning=True, 'off' sets is_reasoning=False, '' leaves model default. LLMService: _openai_supports_reasoning_effort() detects o1/o3/o4/gpt-5* models; _openai_low_effort() returns 'low' (or 'medium' for gpt-5.5 which does not accept 'low'); reasoning_effort='high' when on, _openai_low_effort when off. UI: per-model select in new.html + global preset select that syncs all per-model selects at once."
  }
  ,
  {
    "task_id": "T034",
    "title": "CorrectnessService — factual response evaluation",
    "status": "completed",
    "dependencies": ["T004"],
    "affected_modules": ["CorrectnessService"],
    "affected_files": [
      "app/services/correctness_service.py"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "New service module (no class). evaluate(response_text, prompt_id, language_name, extra_any_variants, extra_target_variants) -> dict|None. Returns {correct, in_target_language, language_leakage} or None when prompt_id has no registered expected answers. correct = factual answer present in any recognised language form. in_target_language = answer uses the target language's surface form. language_leakage = correct AND NOT in_target_language. Matching is substring-based after _normalize() which: maps 8 non-ASCII numeral blocks (Arabic-Indic, Eastern Arabic, Devanagari, Thai, Bengali, Gurmukhi, Gujarati, Full-width) to ASCII digits; lowercases; strips punctuation; collapses whitespace. EXPECTED_ANSWERS dict keyed by prompt_id with any_language_variants + target_language_variants per language. Supports extra_any_variants / extra_target_variants for MAGI-discovered runtime variants. Currently registered: prompt 18 (capital of France), 19 (placeholder), 20 (HTTP acronym), 21 (boolean yes)."
  }
  ,
  {
    "task_id": "T035",
    "title": "MAGI answer discovery + NE labeling (3-judge panel, majority vote)",
    "status": "completed",
    "dependencies": ["T012", "T022", "T034"],
    "affected_modules": ["MAGIService", "ExperimentModel", "QueueService", "DatabaseManager"],
    "affected_files": [
      "app/services/magi_service.py",
      "app/models/experiment_model.py",
      "app/services/queue_service.py",
      "app/models/database.py"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "New MAGIService methods: discover_answer_variant(prompt_text, language, response_text, llm_service, judge_models) — 3-judge panel with majority vote (>=2/3), returns {is_correct, canonical_form, judges}; label_named_entities(prompt_text, language, llm_service, judge_models) — 3-judge panel per-entity majority vote, returns list[{entity_name, expected_form, allow_original}]. New JSON parsers: _parse_json_bool_response(), _parse_json_array_response(). New DB tables: magi_answer_variants (prompt_id, language_id nullable=any-lang, variant, judge_name, judge_model); ne_expectations (prompt_id, language_id, entity_name, expected_form, allow_original, UNIQUE(prompt_id, language_id, entity_name)); ne_labeling_status (prompt_id, language_id, status=pending|done|failed, PRIMARY KEY). New ExperimentModel methods: get_magi_answer_variants(), insert_magi_answer_variant(), update_answer_correct_by_row(), get_ne_expectations(), get_ne_labeling_status(), set_ne_labeling_status(), insert_ne_expectations(). New queue operations: magi_answer_discovery (timeout 60s) and magi_ne_labeling (timeout 60s). QueueModel: has_pending_running_of_type(), requeue_for_dependency(). Post-llm_call pipeline in QueueService: run correctness eval, OLF, NEPR, enqueue answer_discovery if answer_correct is None. magi_ne_labeling enqueued at experiment creation per (prompt, language) where status is not 'done'; after completion calls update_answer_correct_by_row() for all existing token_results of the same (prompt, language)."
  }
  ,
  {
    "task_id": "T036",
    "title": "NEService (NEPR) + OLFService (Output Language Fidelity)",
    "status": "completed",
    "dependencies": ["T034", "T035"],
    "affected_modules": ["NEService", "OLFService"],
    "affected_files": [
      "app/services/ne_service.py",
      "app/services/olf_service.py",
      "data/.gitkeep",
      "requirements.txt"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "ne_service.py: compute_nepr(response_text, expectations) -> float|None. expectations = list[{entity_name, expected_form, allow_original}]. Fraction of expected entities found (substring match via _normalize). Returns None if expectations is empty. olf_service.py: compute_olf(response_text, language_name) -> float|None. Splits response into sentence-level chunks (MIN_CHUNK_CHARS=15). Per-chunk fasttext lid.176 prediction. Weights by char count. Returns fraction of chars detected as target language. Model lazily loaded from data/lid.176.bin (130 MB, not bundled — user must download). LANG_TO_FT maps 12 TokenScribe language names to ISO 639-1 codes. Returns None on model unavailable, unknown language, or too-short text. Both services added to requirements.txt (fasttext). data/ directory created with .gitkeep."
  }
  ,
  {
    "task_id": "T037",
    "title": "New token_results columns: correctness metrics, OLF, NEPR, timing, reasoning_override_requested",
    "status": "completed",
    "dependencies": ["T027", "T035", "T036"],
    "affected_modules": ["DatabaseManager", "ExperimentModel", "ExportService"],
    "affected_files": [
      "app/models/database.py",
      "app/models/experiment_model.py",
      "app/services/export_service.py"
    ],
    "requires_db_changes": true,
    "notes_for_agent": "New columns on token_results (all added via _migrate_schema() guard): reasoning_override_requested TEXT ('on'/'off'/NULL); answer_correct INT, answer_in_target_language INT, language_leakage INT (0/1/NULL); olf_score REAL, nepr_score REAL; total_query_time_ms INT, time_to_first_token_ms INT, time_to_completion_ms INT. New ExperimentModel methods: update_correctness_metrics(token_result_id, metrics), update_olf_score(token_result_id, score), update_nepr_score(token_result_id, score), get_prompt_base_text(prompt_id). ExportService.export_csv() adds reasoning_override_requested to fieldnames. tokenizer_drift and cost_reasoning also added as CSV fields."
  }
  ,
  {
    "task_id": "T038",
    "title": "Bulk AI translation with PEI-aware refinement + run duplication",
    "status": "completed",
    "dependencies": ["T005", "T011", "T012", "T022"],
    "affected_modules": ["TranslationAIService", "StudyController", "ExperimentController", "Views"],
    "affected_files": [
      "app/services/translation_ai_service.py",
      "app/services/__init__.py",
      "app/controllers/study_controller.py",
      "app/controllers/experiment_controller.py",
      "app/views/templates/studies/detail.html",
      "app/views/templates/experiments/new.html",
      "app/views/templates/experiments/list.html",
      "app/views/templates/prompts/form.html"
    ],
    "requires_db_changes": false,
    "notes_for_agent": "New service: translation_ai_service.run_ai_translate(prompt, language_ids, sfs_min, pei_profile, pei_max, candidates_per_lang, db, settings, log_service) -> dict. Iterative loop: generate via gpt-5.5, score SFS+LER, check PEI convergence (max 3 retries per language), detect PEI outliers via _outlier_lang_ids(), adjust structural direction. pei_profile: 'homogeneous' (pei_max 0.20) | 'moderate'/'cross_script' (pei_max 0.35). Returns {created, warnings, accepted_pei, accepted, note, langs, candidates_by_lang}; accepted=False means fallback to best-of-N. New StudyController endpoints: POST /studies/<id>/bulk-translate (spawns _bulk_translate_worker daemon thread; in-memory tracker _bulk_translate_jobs[study_id]); GET /studies/<id>/bulk-translate-status (JSON {active, total, completed, current_prompt, error}). Form fields: prompt_ids, language_ids, bulk_sfs_min, bulk_pei_profile, bulk_candidates_per_lang, bulk_run_magi, bulk_run_phase2, bulk_auto_approve. After generating + scoring candidates, worker optionally runs MAGI Phase 1 + Phase 2, then optionally auto-approves best candidate. UI: bulk translate panel in studies/detail.html with prompt checkboxes, language multi-select, config fields, progress bar polling bulk-translate-status. Run duplication: GET /experiments/<id>/duplicate pre-fills new-experiment form (study, models, repetitions, reasoning_overrides) from an existing run."
  }
]
```
