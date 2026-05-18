# TokenScribe

Scientific platform for studying how language and writing systems affect token usage in Large Language Model APIs.

TokenScribe measures **SFS**, **LER**, **PEI**, and **MAGI Selection Scores** to ensure that observed token differences are attributable to language and tokenizer behavior, not to translation artifacts.

**Author:** Matteo Morreale

---

## What it measures

| Metric | Description |
|--------|-------------|
| **SFS** — Semantic Fidelity Score | Cosine similarity between original and translation embeddings (`0.7·DSF + 0.3·RTF`). Ensures translations are semantically equivalent before comparing token counts. |
| **LER** — Length Expansion Ratio | `len(translation) / len(original)` in characters and tiktoken tokens. Expected range: 1.0–1.3. |
| **PEI** — Prompt Equivalence Index | Mean coefficient of variation (char, word, token count) across all approved translations for a prompt. Lower = fairer cross-language comparison. |
| **MAGI Selection Score** | Composite ranking score: `SFS − 0.5·PEI − 0.5·|LER_char − 1|`. Flags candidates that need human-equivalent LLM review (Phase 2). |
| **MAGI Phase 2** | Three-judge LLM panel (Balthasar, Caspar, Melchior) scoring each translation on `semantic_fidelity`, `register_match`, `naturalness` (1–5), normalized to 0–1. |
| **Token efficiency** | `visible_output_tokens` (tiktoken), `api_reported_output_tokens`, `reasoning_tokens`, `ROR` (Reasoning Overhead Ratio), `cost_visible_only`. |

---

## Stack

- **Python 3.11** + **Flask 3.x** — MVC, Multi-Page Application
- **SQLite** — via `sqlite3` stdlib, raw SQL, schema migrations with `ALTER TABLE`
- **Jinja2** — server-side templating
- **Vanilla JS + CSS** — no Bootstrap, no heavy frameworks
- **sentence-transformers** — local multilingual embeddings (`paraphrase-multilingual-MiniLM-L12-v2`)
- **tiktoken** (`cl100k_base`) — neutral tokenizer for PEI and visible output token counts

---

## Supported LLM Providers

| Provider | Models (examples) |
|----------|-------------------|
| OpenAI | gpt-5, gpt-5-mini, gpt-4.1, gpt-4.1-mini, gpt-4o |
| Anthropic | claude-opus-4-5, claude-sonnet-4-5, claude-opus-4 |
| Google | gemini-2.5-pro, gemini-2.5-flash, gemini-2.0-flash |
| DeepSeek | deepseek-chat, deepseek-reasoner |
| Meta (via Together AI) | Llama-4-Scout, Llama-4-Maverick, Llama-3.1 |
| Qwen (via DashScope) | qwen-max, qwen3-235b-a22b, qwen3-30b-a3b |
| Mistral | mistral-large-latest, mistral-small-latest, codestral-latest |

---

## Installation

```bash
git clone https://github.com/matteomorreale/TokenScribe.git
cd TokenScribe

python3 --version
# se vedi 3.11.x OK, altrimenti installa Python 3.11 (vedi sotto)

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt

python run.py
```

Open `http://localhost:5000` in your browser.

The SQLite database is created automatically at `instance/tokenscribe.db` on first run.

---

## Configuration

Set the `TOKENSCRIBE_SECRET_KEY` environment variable in production:

```bash
export TOKENSCRIBE_SECRET_KEY="your-secret-key"
```

API keys for each LLM provider are configured from the **Settings** page inside the app — no `.env` file needed.

---

## Workflow

```
1. Create a Study
      └─ 2. Add Prompts  (template: [Instruction] <<< [Input] >>> [Expected Output])
               └─ 3. Generate translation candidates  (AI via gpt-5 or manually)
                        └─ 4. Score SFS + LER  →  Approve candidates
                                 └─ 5. Compute MAGI Phase 1  →  rank, flag magi_required
                                          └─ 6. (Optional) Run MAGI Phase 2 judge panel
                                                   └─ 7. Run Experiment  →  call LLM APIs
                                                            └─ 8. Export dataset (CSV / JSON)
```

**Pre-run readiness semaphore:** before launching an experiment, each prompt shows a status badge — green (ready), yellow (incomplete scoring or pending MAGI), red (no approved translations).

---

## Routes

| Route | Description |
|-------|-------------|
| `/studies` | Study list and management |
| `/prompts` | Prompt management, readiness status |
| `/translations` | Candidate management, SFS scoring, MAGI panel |
| `/experiments` | Run experiments, view token results and efficiency metrics |
| `/reports` | Export CSV/JSON, score visualizations, bulk delete runs |
| `/settings` | API keys, model configuration, DB reset |

---

## Export

Both **CSV** and **JSON** exports include full metric enrichment per row:

- Token counts: `visible_output_tokens`, `api_reported_output_tokens`, `reasoning_tokens`
- Efficiency: `ror`, `is_reasoning_model`, `cost_visible_only`, `cost`
- Translation quality: `dsf`, `rtf`, `sfs`, `ler_char`, `ler_token`
- PEI: `pei`, `pei_band`, per-script and per-morphology group breakdowns
- MAGI: `magi_score_absolute`, `magi_score_rank`, `magi_score`, `magi_disagreement`
- JSON only: full `magi_judges` breakdown per judge (dimensions + score + raw response)

---

## Project Structure

```
TokenScribe/
├── app/
│   ├── controllers/      # HTTP route handlers
│   ├── models/           # Data access layer (raw SQL)
│   ├── services/         # Business logic (LLM, scoring, MAGI, export)
│   └── views/templates/  # Jinja2 HTML templates
├── agents/               # AI agent documentation
├── instance/             # SQLite database (gitignored)
├── config.py
├── run.py
└── requirements.txt
```

---

## License

Copyright © Matteo Morreale. All rights reserved.

You may use, modify, and build upon this work, provided that you give appropriate credit to the original author (**Matteo Morreale**) in any derivative work or publication — including research papers, forks, and products built on top of TokenScribe.
