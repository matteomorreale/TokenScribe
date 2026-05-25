# TokenScribe — Data Structure

## Database Schema

```text
writing_systems
  id, name

languages
  id, name, code, writing_system_id → writing_systems.id,
  script_group TEXT,          -- "alphabetic" | "logographic_mixed"
  morphology_group TEXT       -- "agglutinative" | NULL

studies
  id, name, description, config (JSON), created_at

prompts
  id, study_id → studies.id, base_text, category,
  notes         TEXT DEFAULT '',    -- methodological notes, included in JSON exports
  analysis_type TEXT DEFAULT 'standard', -- "standard" | "tsf" (TSF probes trigger post-run strategy classification)
  pei_value  REAL,              -- snapshot: last confirmed PEI
  pei_cv_char REAL,
  pei_cv_word REAL,
  pei_cv_token REAL,
  pei_saved_at TEXT,            -- ISO timestamp of last save_pei_snapshot() call
  created_at

translation_candidates
  id, prompt_id → prompts.id, language_id → languages.id,
  text, status (pending|approved|rejected), version, created_at

translation_scores
  id, candidate_id → translation_candidates.id UNIQUE,
  dsf (REAL), rtf (REAL), sfs (REAL),
  ler_char (REAL),            -- len(translation)/len(original) chars
  ler_token (REAL),           -- tiktoken(translation)/tiktoken(original)
  computed_at

approved_translations
  id, prompt_id → prompts.id, language_id → languages.id,
  candidate_id → translation_candidates.id,
  approved_at
  UNIQUE(prompt_id, language_id)

providers
  id, name

models
  id, provider_id → providers.id, name, context_window,
  cost_per_input_token  REAL,   -- USD per million input tokens ($/M)
  cost_per_output_token REAL,   -- USD per million output tokens ($/M)
  is_active,
  is_reasoning INTEGER NOT NULL DEFAULT 0  -- 1 = model exposes hidden reasoning tokens

experiment_runs
  id, study_id → studies.id, timestamp, notes

token_results                 -- INSERT + retry; immutable per (run, cell, repetition, attempt)
  id, run_id → experiment_runs.id, prompt_id → prompts.id,
  language_id → languages.id, model_id → models.id,
  input_tokens (INT), output_tokens (INT),
  visible_output_text_length (INT),   -- len() of response text in chars
  api_reported_output_tokens (INT),   -- tokens as reported by provider API
  visible_output_tokens (INT),        -- tiktoken count of response text
  normalized_output_tokens (INT),     -- legacy alias for visible_output_tokens
  cost (REAL),                        -- total API cost (includes reasoning)
  source (api_reported|estimated),
  token_accounting_mode TEXT,
  response_text TEXT,
  response_valid INTEGER NOT NULL DEFAULT 1,  -- 0 if response text is empty/blank
  repetition_index INTEGER NOT NULL DEFAULT 0,-- 0-based repetition within the cell
  attempt_index INTEGER NOT NULL DEFAULT 0,   -- auto-incremented atomically on retry
  attempt_status TEXT NOT NULL DEFAULT 'success',  -- "success" | "retry"
  reasoning_override_requested TEXT,          -- 'on' | 'off' | NULL (from llm_call payload)
  answer_correct INTEGER,                     -- 0/1/NULL — factual answer present (CorrectnessService)
  answer_in_target_language INTEGER,          -- 0/1/NULL — answer in requested language
  language_leakage INTEGER,                   -- 0/1/NULL — correct but wrong language
  olf_score REAL,                             -- 0.0–1.0 | NULL (OLFService, fasttext)
  nepr_score REAL,                            -- 0.0–1.0 | NULL (NEService, requires NE labeling)
  tsf_strategy TEXT,                          -- NULL | "keep_latin" | "transliterate" | "translate_semantic" | "mistranslate" (TSFService, 3-judge majority vote, only for prompts.analysis_type='tsf')
  tsf_judges TEXT,                            -- JSON {balthasar:{model_id,model_name,strategy,raw_response,error,attempts}, caspar:{…}, melchior:{…}} | NULL
  total_query_time_ms INTEGER,                -- wall-clock time for full LLM call (ms)
  time_to_first_token_ms INTEGER,             -- time to first token / streaming start (ms)
  time_to_completion_ms INTEGER,              -- time from first token to last token (ms)
  created_at

  UNIQUE(run_id, prompt_id, language_id, model_id, repetition_index, attempt_index)

  -- Derived in Python by get_results_by_run() (NOT stored):
  -- reasoning_tokens = max(0, api_reported_output_tokens - visible_output_tokens)
  -- cost_visible_only = visible_output_tokens × cost_per_output_token / 1_000_000
  -- cost = (input_tokens × cost_per_input_token + api_reported_output_tokens × cost_per_output_token) / 1_000_000
  -- ror = reasoning_tokens / visible_output_tokens
  -- reasoning_observed = reasoning_tokens > REASONING_THRESHOLD (10)
  -- reasoning_state = "active"               (is_reasoning=1 AND reasoning_observed)
  --                 | "capable_but_inactive"  (is_reasoning=1 AND NOT reasoning_observed)
  --                 | "anomaly"               (is_reasoning=0 AND reasoning_observed) → WARNING logged
  --                 | "non_reasoning"         (is_reasoning=0 AND NOT reasoning_observed)

  -- get_results_by_run() filters to attempt_status='success' rows only,
  -- selecting the MAX(attempt_index) per (run, prompt, language, model, repetition_index).

pei_results
  id, run_id → experiment_runs.id, prompt_id → prompts.id,
  cv_char_length (REAL), cv_word_count (REAL), cv_token_count (REAL),
  pei (REAL),
  script_group_count (INT),
  morphology_group_count (INT),
  pei_band TEXT,              -- "ottimo" | "plausibile" | "alto"
  computed_at

pei_group_results
  id, run_id → experiment_runs.id, prompt_id → prompts.id,
  group_type TEXT,            -- "script_group" | "morphology_group"
  group_value TEXT,
  language_count (INT),
  cv_char_length, cv_word_count, cv_token_count,
  pei (REAL),
  pei_delta_vs_global (REAL),
  baseline_pei (REAL),
  pei_delta_vs_group (REAL),
  pei_band TEXT,
  computed_at

selection_score_results       -- MAGI Phase 1 + Phase 2 (per candidate)
  id, candidate_id → translation_candidates.id UNIQUE,
  prompt_id → prompts.id,
  score_absolute (REAL),      -- SFS − λ·PEI − ν·|LER_char−1|
  score_rank (INT),           -- 1 = best
  score_rank_pct (REAL),      -- 1.0 = best, 0.0 = worst
  magi_required (INT 0/1),    -- rank > max(1, floor(n/4))
  lambda_used (REAL),         -- 0.5
  nu_used (REAL),             -- 0.5
  magi_score (REAL),          -- mean of valid Phase 2 judge scores (NULL until Phase 2 run)
  magi_disagreement (INT 0/1),-- stdev(valid_scores) > 0.15
  magi_judges (TEXT JSON),    -- {balthasar: {model_id, model_name, semantic_fidelity, register_match, naturalness, score, raw_response, error, attempts},
                              --  caspar:    {…},
                              --  melchior:  {…}}
                              -- NULL until Phase 2 run; deserialized in model layer before use
  computed_at

run_translation_snapshot
  id, run_id → experiment_runs.id, prompt_id → prompts.id,
  language_id → languages.id, candidate_id → translation_candidates.id,
  snapshotted_at
  UNIQUE(run_id, prompt_id, language_id)

run_queue                     -- async work items for QueueService daemon thread
  id, run_id → experiment_runs.id,
  operation_type TEXT,        -- "llm_call" | "magi_phase2" | "compute_pei" | "finalize_pei_groups" | "snapshot_translations"
  item_key TEXT,              -- unique key per run: e.g. "llm:p1:l3:m7:r0"  (r=repetition_index)
  payload TEXT (JSON),        -- all data the worker needs (model_name, provider, prompt text, etc.)
  status TEXT,                -- "pending" | "running" | "done" | "error" | "timeout" | "cancelled"
  priority INT DEFAULT 0,
  retry_count INT DEFAULT 0,
  error_message TEXT,
  created_at, started_at, completed_at
  UNIQUE(run_id, operation_type, item_key)

run_history                   -- archivio storico per redo/replace (snapshot JSON dei token_results)
  id, run_id → experiment_runs.id,
  model_id    INT NOT NULL,            -- ID del modello archiviato
  model_name  TEXT NOT NULL,
  archived_at TEXT NOT NULL DEFAULT now,
  reason      TEXT NOT NULL,           -- "redo" | "replace"
  replaced_by_model_id   INT,          -- solo per reason="replace"
  replaced_by_model_name TEXT,
  results_json TEXT NOT NULL DEFAULT '[]'  -- snapshot completo dei token_results (array JSON)

magi_answer_variants          -- MAGI-discovered answer variants (dynamically extended by answer discovery)
  id, prompt_id → prompts.id,
  language_id → languages.id NULL,  -- NULL = valid in any language
  variant TEXT NOT NULL,
  judge_name TEXT,              -- e.g. "balthasar"
  judge_model TEXT,             -- model name used by this judge
  created_at
  INDEX idx_mav_prompt(prompt_id)

ne_expectations               -- Named entity localized forms labeled by MAGI (per prompt × language)
  id, prompt_id → prompts.id, language_id → languages.id,
  entity_name TEXT NOT NULL,    -- English form (e.g. "France")
  expected_form TEXT NOT NULL,  -- localized form (e.g. "Francia")
  allow_original INTEGER NOT NULL DEFAULT 0,  -- 1 if English form also acceptable
  judge_name TEXT,
  judge_model TEXT,
  computed_at
  UNIQUE(prompt_id, language_id, entity_name)
  INDEX idx_ne_prompt_lang(prompt_id, language_id)

ne_labeling_status            -- completion tracker for MAGI NE labeling per (prompt, language)
  prompt_id → prompts.id,
  language_id → languages.id,
  status TEXT NOT NULL DEFAULT 'pending',  -- "pending" | "done" | "failed"
  computed_at
  PRIMARY KEY (prompt_id, language_id)

settings
  id, key (UNIQUE), value, updated_at

  -- Notable settings keys:
  -- {provider}_api_key   — API key per provider (openai, anthropic, google, deepseek, meta, qwen, mistral, xai)
  --                        values for _ENCRYPTED_KEYS are stored Fernet-encrypted by CryptoService
  -- qwen_region          — "china" (dashscope.aliyuncs.com) | "international" (dashscope-intl.aliyuncs.com)
  -- magi_judge_{name}_id — model_id for Balthasar / Caspar / Melchior
  -- pricing_unit         — "per_million" (set by one-shot migration; guards against double-multiplying costs)
```

## Relationships

```text
studies ──< prompts
studies ──< experiment_runs
prompts ──< translation_candidates
prompts ──< approved_translations
prompts ──< pei_results          (via run)
prompts ──< pei_group_results    (via run)
prompts ──< selection_score_results (via candidate)
prompts ──< magi_answer_variants
prompts ──< ne_expectations
prompts ──< ne_labeling_status
translation_candidates ──1 translation_scores
translation_candidates ──1 selection_score_results
translation_candidates ──> approved_translations
languages ──> writing_systems
languages ──> magi_answer_variants (nullable — NULL = any language)
languages ──> ne_expectations
languages ──> ne_labeling_status
experiment_runs ──< token_results
experiment_runs ──< pei_results
experiment_runs ──< pei_group_results
experiment_runs ──< run_history
token_results ──> models ──> providers
```

## Naming Conventions

- Table names: snake_case, plural
- Column names: snake_case
- Foreign keys: `{table_singular}_id`
- Status fields: string enum stored as TEXT
- Timestamps: TEXT in ISO 8601 format (`YYYY-MM-DDTHH:MM:SS`)
- JSON fields: TEXT column storing valid JSON
- Boolean fields: INT 0/1 (SQLite has no BOOLEAN type)

## Key Constraints

- `token_results`: INSERT-only within a single (repetition_index, attempt_index) slot; retries append a new row with incremented `attempt_index`; `get_results_by_run()` surfaces only the latest `attempt_status='success'` row per cell+repetition. The redo/replace flow first archives rows to `run_history` then deletes them for the target model before re-queueing.
- `run_history`: INSERT-only archive; one row per (run_id, model_id, operation); `results_json` is a snapshot of all token_results rows for that model at the moment of archival
- `run_translation_snapshot`: written once at run start via `snapshot_translations(run_id, study_id)`;
  `get_translation_scores_by_run` JOINs this table, not `approved_translations`, so historical
  reports are immune to re-approvals
- `approved_translations`: UNIQUE(prompt_id, language_id) — one approved per language per prompt
- `translation_scores`: UNIQUE(candidate_id) — one score row per candidate, upserted
- `selection_score_results`: UNIQUE(candidate_id) — one MAGI score per candidate, upserted;
  `magi_score`, `magi_disagreement`, `magi_judges` are reset to NULL when Phase 1 is recomputed
- `settings`: key is UNIQUE

## magi_judges JSON Structure

```json
{
  "balthasar": {
    "model_id": 3,
    "model_name": "gpt-4o-mini",
    "semantic_fidelity": 5,
    "register_match": 4,
    "naturalness": 5,
    "score": 0.916667,
    "raw_response": "{\"semantic_fidelity\": 5, \"register_match\": 4, \"naturalness\": 5}",
    "error": null,
    "attempts": 1
  },
  "caspar": {
    "model_id": 3,
    "model_name": "gpt-4o-mini",
    "semantic_fidelity": null,
    "register_match": null,
    "naturalness": null,
    "score": null,
    "raw_response": "I believe this translation is excellent and captures...",
    "error": "Parse failed: no JSON dimensions or 0–1 score found",
    "attempts": 3
  },
  "melchior": {
    "model_id": 3,
    "model_name": "gpt-4o-mini",
    "semantic_fidelity": null,
    "register_match": null,
    "naturalness": null,
    "score": null,
    "raw_response": null,
    "error": "API error: Connection timeout",
    "attempts": 3
  }
}
```

`raw_response` is NULL for API-level failures; always a string (possibly empty) for API successes.
Records stored before `raw_response` was introduced will have no `raw_response` key — treat as NULL.

## Migration Strategy

New columns are added via `_migrate_schema()` in `DatabaseManager` using:

```python
cur = conn.execute("PRAGMA table_info(table_name)")
columns = [row[1] for row in cur.fetchall()]
if "new_column" not in columns:
    conn.execute("ALTER TABLE table_name ADD COLUMN new_column TYPE")
```

New tables are added directly to `_create_tables()` using `CREATE TABLE IF NOT EXISTS`.
