# TokenScribe — Data Structure

## Database Schema

```
writing_systems
  id, name

languages
  id, name, code, writing_system_id → writing_systems.id

studies
  id, name, description, config (JSON), created_at

prompts
  id, study_id → studies.id, base_text, category, created_at

translation_candidates
  id, prompt_id → prompts.id, language_id → languages.id,
  text, status (pending|approved|rejected), version, created_at

translation_scores
  id, candidate_id → translation_candidates.id,
  dsf (REAL), rtf (REAL), sfs (REAL), computed_at

approved_translations
  id, prompt_id → prompts.id, language_id → languages.id,
  candidate_id → translation_candidates.id, approved_at

providers
  id, name

models
  id, provider_id → providers.id, name, context_window, cost_per_input_token, cost_per_output_token

experiment_runs
  id, study_id → studies.id, timestamp, notes

token_results
  id, run_id → experiment_runs.id, prompt_id → prompts.id,
  language_id → languages.id, model_id → models.id,
  input_tokens (INT), output_tokens (INT), cost (REAL),
  source (api_reported|estimated), created_at

settings
  id, key (UNIQUE), value, updated_at

pei_results
  id, run_id → experiment_runs.id, prompt_id → prompts.id,
  cv_char_length (REAL), cv_word_count (REAL), cv_token_count (REAL),
  pei (REAL), computed_at
```

## Relationships

```
studies → (many) prompts
studies → (many) experiment_runs
prompts → (many) translation_candidates
prompts → (many) approved_translations
translation_candidates → (one) translation_scores
translation_candidates → approved_translations
languages → writing_systems
experiment_runs → (many) token_results
experiment_runs → (many) pei_results
token_results → models → providers
```

## Naming Conventions
- Table names: snake_case, plural
- Column names: snake_case
- Foreign keys: {table_singular}_id
- Status fields: string enum stored as TEXT
- Timestamps: TEXT in ISO 8601 format (YYYY-MM-DDTHH:MM:SS)
- JSON fields: TEXT column storing valid JSON

## Key Constraints
- token_results: INSERT only, no UPDATE (immutable runs)
- approved_translations: one per (prompt_id, language_id) — UNIQUE constraint
- settings: key is UNIQUE
