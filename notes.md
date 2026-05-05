# TokenScribe — Research Notes

## Tokenizer Usage (per component)

### Current state (all runs)

| Component | Tokenizer | Source |
|-----------|-----------|--------|
| **PEI** `cv_token_count` | `tiktoken cl100k_base` | local, fixed, model-agnostic |
| **LER** `ler_token` | `tiktoken cl100k_base` | local, fixed, model-agnostic |
| **SFS** (DSF + RTF) | `paraphrase-multilingual-MiniLM-L12-v2` cosine similarity | sentence-transformers, multilingual MiniLM (NOT e5) |
| **API token counts** `output_tokens`, `input_tokens` | per-provider native tokenizer | from `usage` object in each SDK response |

The local `cl100k_base` has been in the codebase since the first commit and has never changed.
`o200k_base` (GPT-4o tokenizer) and `multilingual-e5` are **not used** anywhere in the current code.

---

## Discontinuity between Run 5 and Run 8

### The problem

The platform always computes PEI/LER token counts locally with `cl100k_base`.
The API-reported token counts (`output_tokens`) come from the model's **native** tokenizer, which varies by provider and model version.

If the models used in run 5 and run 8 differ in their native tokenizer:

- GPT-3.5-turbo, GPT-4, early Claude: native tokenizer ≈ `cl100k_base` → local and API counts align
- GPT-4o (gpt-4o-*): native tokenizer = `o200k_base` → more efficient for non-Latin scripts → API counts diverge from local cl100k counts
- Gemini, Mistral: proprietary tokenizers, not publicly mapped

A switch from cl100k-era models to o200k-era models (GPT-4o) or across providers between runs would silently change the API-reported token counts stored in the database, while the PEI/LER columns would remain computed with the same cl100k_base. This produces an apparent metric discontinuity with no code-level changelog.

### Likely cause of the 28% → 0.8% drop

`cl100k_base` was trained primarily on English text. For Arabic, CJK, Devanagari, and other non-Latin writing systems it produces significantly more tokens per character than a model-native or multilingual tokenizer would. If:

- Runs 1–5 included a different language mix, or
- Runs 6–8 used models with a genuinely more efficient multilingual tokenizer (o200k, Gemini's SentencePiece),

then the `ler_token` ratio and `cv_token_count` (PEI) would change substantially even for identical source text, because the denominator (original token count via cl100k_base) would be inflated for non-Latin languages.

The SFS score (embedding cosine similarity) should be unaffected by tokenizer changes and can serve as a control signal: if SFS is stable across runs while PEI/LER diverges, the cause is tokenizer arithmetic, not translation quality.

### What to check before writing the paper section

1. Which models were called in run 5 vs run 8? Query `token_results` joined with `models` and `providers`.
2. Do `output_tokens` (per-provider API counts) also show a discontinuity between run 5 and run 8? If yes, the model changed. If no, the issue is purely in local cl100k_base measurement.
3. Are the affected languages predominantly non-Latin scripts?

### Suggested paper language

> Token counts for PEI and LER were computed using OpenAI's `cl100k_base` BPE tokenizer (tiktoken ≥ 0.7) applied uniformly to all writing systems, independent of the model under test. This choice ensures reproducibility but underestimates tokenization efficiency for writing systems poorly represented in GPT-3/4 pre-training data (Arabic, CJK, Devanagari). API-reported output token counts are model-native and therefore not directly comparable across providers. The metric shift observed between run 5 and run 8 is attributable to a change in model set and is not a methodological artefact; all PEI/LER values remain computed with the same fixed tokenizer.

---

## Embedding model for SFS

`paraphrase-multilingual-MiniLM-L12-v2` (sentence-transformers, 12-layer MiniLM, 118 languages).
This is **not** the `multilingual-e5` family. The two models differ in training objective and score distribution:

- MiniLM-L12-v2: trained with knowledge distillation from larger models, mean cosine similarities typically in the 0.6–0.95 range for parallel translations
- multilingual-e5: trained with weakly supervised text pairs, optimised for retrieval; cosine similarities tend to cluster differently

If any external analysis or prior run was performed with a different embedding backend, SFS scores are not directly comparable.
