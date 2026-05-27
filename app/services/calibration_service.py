"""
TokenScribe — Calibration Service
Author: Matteo Morreale

Baseline streaming-rate calibration for iRRT computation.

4 hardcoded calibration prompts (immutable across runs — cross-run comparability requires
identical stimuli). For each run, the prompts are translated into the same language set as
the experimental prompts using a single LLM call (no MAGI review needed).

Calibration trials run before experimental prompts (lower queue priority) so the baseline
rates are available before the main run begins.

Reasoning override rules (brief Run 19 §1.3):
  - OpenAI reasoning models (gpt-5.5 etc.): reasoning_effort='medium' (minimum for gpt-5.5)
    → handled automatically by LLMService when is_reasoning=False
  - DeepSeek-v4-pro: no toggle yet; runs normally, flagged baseline_quality='degraded'
  - Grok-reasoning models: swap to paired non-reasoning model (REASONING_MODEL_PAIRS)
  - All other reasoning models without toggle: run normally, flagged as 'degraded'

baseline_quality (auto-computed post-trial, §1.4):
  clean    — reasoning_tokens ≤ CLEAN_REASONING_THRESHOLD and/or reasoning explicitly off
  degraded — reasoning_tokens > threshold (baseline contaminated)
  invalid  — attempt_status != 'success'
"""

import logging
import statistics
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Calibration prompts (hardcoded — DO NOT MODIFY between runs)
# ---------------------------------------------------------------------------

CALIBRATION_PROMPTS = [
    {
        "slug": "cal_01_short",
        "text_en": (
            "Complete this sentence with one short factual statement:\n"
            "The chemical symbol for water is H2O, which is composed of two atoms of "
            "hydrogen and one of oxygen.\n"
            "Respond with one similar single-sentence factual statement about table salt."
        ),
        "target_tokens_min": 20,
        "target_tokens_max": 30,
    },
    {
        "slug": "cal_02_medium",
        "text_en": (
            "List the seven continents of the world, and for each one provide its name and "
            "a brief one-sentence description of its location. Use a simple list format, "
            "one continent per line."
        ),
        "target_tokens_min": 80,
        "target_tokens_max": 120,
    },
    {
        "slug": "cal_03_long",
        "text_en": (
            "Describe what the human respiratory system does, in 8 to 10 sentences. "
            "Focus only on widely known basic facts about how breathing works, the role "
            "of the lungs, and oxygen-carbon dioxide exchange. Do not include speculation "
            "or advanced topics."
        ),
        "target_tokens_min": 250,
        "target_tokens_max": 400,
    },
    {
        "slug": "cal_04_long_varied",
        "text_en": (
            "Describe the basic anatomy of a typical flowering plant, in 8 to 10 sentences. "
            "Focus only on widely known basic facts about roots, stem, leaves, and flower "
            "structure. Do not include speculation or advanced topics."
        ),
        "target_tokens_min": 250,
        "target_tokens_max": 400,
    },
]

# Slugs used for baseline_rates computation (long prompts only — more stable rate estimates)
BASELINE_RATE_SLUGS = {"cal_03_long", "cal_04_long_varied"}

# ---------------------------------------------------------------------------
# Reasoning model → non-reasoning variant mapping (§1.3, Grok rule)
# ---------------------------------------------------------------------------

# For reasoning models where the only way to disable reasoning is to use
# a different model endpoint, map to the non-reasoning sibling here.
# Key = model name as stored in DB, value = calibration model to use instead.
REASONING_TO_CALIBRATION_MODEL: dict[str, str] = {
    "grok-4.20-0309-reasoning":   "grok-4.20-0309-non-reasoning",
    "grok-4-1-fast-reasoning":    "grok-4-1-fast-non-reasoning",
    # Add future reasoning↔non-reasoning pairs here as they become available.
}

# Reasoning models that have a toggle supported by LLMService (is_reasoning=False suffices):
# OpenAI reasoning models: LLMService sets reasoning_effort to minimum when is_reasoning=False.
MODELS_WITH_REASONING_TOGGLE_PREFIX = ("o1", "o3", "o4", "gpt-5")

# threshold: reasoning_tokens below this → baseline considered clean
CLEAN_REASONING_THRESHOLD = 30

# ---------------------------------------------------------------------------
# baseline_quality computation
# ---------------------------------------------------------------------------


def compute_baseline_quality(
    reasoning_tokens: int,
    attempt_status: str,
    reasoning_explicitly_disabled: bool,
) -> str:
    """Compute baseline_quality for a calibration result row.

    Args:
        reasoning_tokens:            reported reasoning tokens for the trial.
        attempt_status:              'success' | 'failed' | other.
        reasoning_explicitly_disabled: True if reasoning was turned off via a
                                      model toggle (e.g. LLMService used
                                      is_reasoning=False on a reasoning-capable model
                                      that honours the flag, or model was swapped to
                                      the non-reasoning sibling).
    Returns:
        'clean' | 'degraded' | 'invalid'
    """
    if attempt_status != "success":
        return "invalid"
    if reasoning_explicitly_disabled and reasoning_tokens <= CLEAN_REASONING_THRESHOLD:
        return "clean"
    if reasoning_tokens <= CLEAN_REASONING_THRESHOLD:
        return "clean"
    return "degraded"


# ---------------------------------------------------------------------------
# Calibration model resolution
# ---------------------------------------------------------------------------


def resolve_calibration_model(
    model_name: str,
    is_reasoning: bool,
    provider: str,
) -> tuple[str, bool, bool]:
    """Return (effective_model_name, effective_is_reasoning, reasoning_explicitly_disabled).

    For calibration, we always want is_reasoning=False so that reasoning models
    produce a baseline without internal reasoning traces.

    - Grok-reasoning: swap model name to non-reasoning sibling.
    - OpenAI reasoning: set is_reasoning=False (LLMService will use minimum effort).
    - DeepSeek / other without toggle: use is_reasoning=False (LLMService passes
      through), reasoning_explicitly_disabled=False so the trial is later flagged
      as 'degraded' if reasoning_tokens > threshold.
    """
    # Swap Grok-reasoning to non-reasoning sibling
    if model_name in REASONING_TO_CALIBRATION_MODEL:
        effective_model = REASONING_TO_CALIBRATION_MODEL[model_name]
        return effective_model, False, True

    # OpenAI reasoning models: is_reasoning=False sets minimum reasoning_effort
    if provider == "openai" and is_reasoning:
        mn_lower = model_name.lower()
        if any(mn_lower.startswith(p) for p in MODELS_WITH_REASONING_TOGGLE_PREFIX):
            return model_name, False, True

    # All other models: pass is_reasoning=False as best-effort; flag disabled if is_reasoning was True
    # For models that ignore the flag (e.g. DeepSeek-v4-pro), reasoning_explicitly_disabled=False
    # so the quality check will catch contaminated baseline via reasoning_tokens count.
    reasoning_explicitly_disabled = is_reasoning  # best-effort; may not actually disable
    return model_name, False, reasoning_explicitly_disabled


# ---------------------------------------------------------------------------
# Calibration translation (auto, no MAGI)
# ---------------------------------------------------------------------------

_TRANSLATION_PROMPT_TEMPLATE = """You are a professional translator.
Translate the following text from English into {language_name}.
Produce only the translation — no explanations, no notes, no preamble.
The translation must preserve the original meaning, register, and tone exactly.
Output only the translated text.

TEXT TO TRANSLATE:
{text_en}"""


def get_or_create_calibration_translation(
    db,
    calibration_prompt_id: int,
    language_id: int,
    language_code: str,
    language_name: str,
    text_en: str,
    llm_service,
    settings: dict,
) -> Optional[str]:
    """Return existing translation or create a new one via LLM.

    Uses a cheap/fast model for translation since these are simple factual texts.
    Translation quality is less critical than for experimental prompts (no MAGI review).
    English (language_code='en') returns the original text directly without translating.
    """
    # English: no translation needed
    if language_code == "en":
        return text_en

    conn = db.get_connection()
    try:
        row = conn.execute(
            """SELECT text FROM calibration_translations
               WHERE calibration_prompt_id=? AND language_id=?""",
            (calibration_prompt_id, language_id),
        ).fetchone()
        if row:
            return row["text"]
    finally:
        conn.close()

    # Translation not found — generate via LLM
    # Use the fastest available provider (cheapest suitable model)
    translation = _translate_calibration_prompt(
        text_en=text_en,
        language_name=language_name,
        llm_service=llm_service,
        settings=settings,
    )
    if not translation:
        logger.error(
            "Calibration translation failed for prompt_id=%d lang=%s",
            calibration_prompt_id, language_name,
        )
        return None

    # Store for reuse
    conn = db.get_connection()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO calibration_translations
               (calibration_prompt_id, language_id, text)
               VALUES (?, ?, ?)""",
            (calibration_prompt_id, language_id, translation),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(
        "Calibration translation created: prompt_id=%d lang=%s (%d chars)",
        calibration_prompt_id, language_name, len(translation),
    )
    return translation


def _translate_calibration_prompt(
    text_en: str,
    language_name: str,
    llm_service,
    settings: dict,
) -> Optional[str]:
    """Translate a calibration prompt using the best available provider.

    Priority: OpenAI gpt-4.1-nano → Google gemini-2.5-flash-lite → Anthropic claude-haiku-4-5.
    Falls back to next provider if the API key is missing or the call fails.
    """
    from app.services.llm_service import LLMService

    prompt_text = _TRANSLATION_PROMPT_TEMPLATE.format(
        language_name=language_name,
        text_en=text_en,
    )

    candidates = [
        (LLMService.PROVIDER_OPENAI,    "gpt-4.1-nano",          "openai_api_key"),
        (LLMService.PROVIDER_GOOGLE,     "gemini-2.5-flash-lite", "google_api_key"),
        (LLMService.PROVIDER_ANTHROPIC,  "claude-haiku-4-5",      "anthropic_api_key"),
        (LLMService.PROVIDER_DEEPSEEK,   "deepseek-v4-flash",     "deepseek_api_key"),
    ]

    for provider, model_name, key_name in candidates:
        if not settings.get(key_name):
            continue
        try:
            result = llm_service.call(
                provider=provider,
                model_name=model_name,
                prompt_text=prompt_text,
                cost_per_input=0.0,
                cost_per_output=0.0,
                is_reasoning=False,
            )
            if result.success and (result.response_text or "").strip():
                return result.response_text.strip()
            logger.warning(
                "Calibration translation via %s/%s failed: %s",
                provider, model_name, result.error,
            )
        except Exception as exc:
            logger.warning(
                "Calibration translation via %s/%s exception: %s",
                provider, model_name, exc,
            )

    return None


# ---------------------------------------------------------------------------
# Baseline rate computation (for export)
# ---------------------------------------------------------------------------


def compute_baseline_rates(calibration_results: list[dict]) -> dict:
    """Compute per-(model, language) streaming rate from calibration results.

    Uses only cal_03_long and cal_04_long_varied (stable output length)
    and only baseline_quality='clean' trials.

    Rate = visible_output_tokens / (time_to_completion_ms / 1000)  [tok/sec]

    Returns:
        {
            "deepseek-v4-pro": {
                "en": {
                    "rate_tok_per_sec_median": 56.3,
                    "rate_tok_per_sec_p25": 52.1,
                    "rate_tok_per_sec_p75": 61.8,
                    "baseline_ttft_ms_median": 1842,
                    "n_clean_trials": 16,
                    "quality": "clean"
                },
                ...
            },
            ...
        }
    """
    # Collect rates per (model_name, language_code)
    rate_store: dict[tuple, list[float]] = {}
    ttft_store: dict[tuple, list[int]] = {}

    for r in calibration_results:
        if r.get("baseline_quality") != "clean":
            continue
        if r.get("attempt_status") != "success":
            continue
        slug = r.get("cal_prompt_slug", "")
        if slug not in BASELINE_RATE_SLUGS:
            continue

        vot          = r.get("visible_output_tokens") or 0
        completion_ms = r.get("time_to_completion_ms") or 0
        ttft_ms       = r.get("time_to_first_token_ms")

        if vot <= 0 or completion_ms <= 0:
            continue

        rate = vot / (completion_ms / 1000.0)
        key  = (r.get("model_name", ""), r.get("language_code", ""))
        rate_store.setdefault(key, []).append(rate)
        if ttft_ms is not None:
            ttft_store.setdefault(key, []).append(ttft_ms)

    result: dict = {}
    for (model_name, lang_code), rates in rate_store.items():
        if not rates:
            continue
        sorted_rates = sorted(rates)
        n = len(sorted_rates)
        p25_idx = max(0, int(n * 0.25) - 1)
        p75_idx = min(n - 1, int(n * 0.75))

        ttft_list = ttft_store.get((model_name, lang_code), [])
        ttft_median = round(statistics.median(ttft_list), 1) if ttft_list else None

        result.setdefault(model_name, {})[lang_code] = {
            "rate_tok_per_sec_median": round(statistics.median(sorted_rates), 2),
            "rate_tok_per_sec_p25":   round(sorted_rates[p25_idx], 2),
            "rate_tok_per_sec_p75":   round(sorted_rates[p75_idx], 2),
            "baseline_ttft_ms_median": ttft_median,
            "n_clean_trials":          n,
            "quality":                 "clean",
        }

    # Fill in degraded entries for models that had no clean trials
    degraded_models: set = set()
    for r in calibration_results:
        if r.get("baseline_quality") == "degraded":
            degraded_models.add(r.get("model_name", ""))

    for model_name in degraded_models:
        if model_name not in result:
            result[model_name] = {}
        for lang_code in {r.get("language_code", "") for r in calibration_results
                          if r.get("model_name") == model_name}:
            if lang_code not in result.get(model_name, {}):
                result.setdefault(model_name, {})[lang_code] = {
                    "rate_tok_per_sec_median": None,
                    "rate_tok_per_sec_p25":    None,
                    "rate_tok_per_sec_p75":    None,
                    "baseline_ttft_ms_median": None,
                    "n_clean_trials":           0,
                    "quality":                 "degraded",
                }

    return result


# ---------------------------------------------------------------------------
# Prefix-caching evidence computation (P4)
# ---------------------------------------------------------------------------


def compute_prefix_caching_evidence(token_results: list[dict]) -> dict:
    """Detect potential server-side prefix caching from TTFT patterns.

    For each (model, prompt, language) cell, computes median TTFT of first
    repetition vs last. A positive delta (first > last) suggests caching warmup.

    Uses repetition_index as a proxy for execution order.

    Returns:
        {
            "model_name": {
                "delta_ttft_first_vs_last_ms_median": 42.3,
                "n_cells_analysed": 17,
                "caching_likely": True
            },
            ...
        }
    """
    # Group TTFT values by (model_name, prompt_id, language_id)
    # Keyed to first (rep=0) and last (rep=max) repetition TTFT per cell
    cell_data: dict[tuple, list[tuple[int, int]]] = {}  # key → [(rep_idx, ttft), ...]

    for r in token_results:
        ttft  = r.get("time_to_first_token_ms")
        rep   = r.get("repetition_index")
        model = r.get("model_name", "")
        pid   = r.get("prompt_id")
        lid   = r.get("language_id")

        if ttft is None or rep is None or not model or pid is None or lid is None:
            continue
        key = (model, pid, lid)
        cell_data.setdefault(key, []).append((rep, ttft))

    # Compute per-model deltas
    model_deltas: dict[str, list[float]] = {}
    for (model_name, pid, lid), vals in cell_data.items():
        if len(vals) < 2:
            continue
        vals.sort(key=lambda x: x[0])
        first_ttft = vals[0][1]
        last_ttft  = vals[-1][1]
        delta = first_ttft - last_ttft   # positive = first was slower = caching active
        model_deltas.setdefault(model_name, []).append(delta)

    result: dict = {}
    for model_name, deltas in model_deltas.items():
        if not deltas:
            continue
        med = statistics.median(deltas)
        result[model_name] = {
            "delta_ttft_first_vs_last_ms_median": round(med, 2),
            "n_cells_analysed":                   len(deltas),
            "caching_likely":                     med > 50,  # heuristic: >50ms → likely caching
        }

    return result
