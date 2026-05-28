"""
TokenScribe — Calibration Service
Author: Matteo Morreale

Baseline streaming-rate calibration for iRRT computation.

4 hardcoded calibration prompts (immutable across runs — cross-run comparability requires
identical stimuli). For each run, the prompts are translated into the same language set as
the experimental prompts using a single LLM call (no MAGI review needed).

Calibration trials run before experimental prompts (lower queue priority) so the baseline
rates are available before the main run begins.

3-level cascade for baseline source (Run 20):
  Level 1 — real_companion   : reasoning model swapped to non-reasoning sibling (Grok rule)
  Level 2 — real_toggle      : reasoning disabled via internal API parameter (OpenAI, Mistral)
  Level 3 — estimated_pool   : always-reasoning model with no companion/toggle; cross-pool median used

baseline_quality (auto-computed post-trial):
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
# Reasoning model → non-reasoning variant mapping (Level 1 — companion model)
# ---------------------------------------------------------------------------

REASONING_TO_CALIBRATION_MODEL: dict[str, str] = {
    "grok-4.20-0309-reasoning":   "grok-4.20-0309-non-reasoning",
    "grok-4-1-fast-reasoning":    "grok-4-1-fast-non-reasoning",
    # Add future reasoning↔non-reasoning pairs here as they become available.
}

# Level 2: models whose reasoning can be disabled via an internal API parameter.
# These model name prefixes accept reasoning_effort='low' (or 'medium' for gpt-5.5).
MODELS_WITH_REASONING_TOGGLE_PREFIX = ("o1", "o3", "o4", "gpt-5")

# ---------------------------------------------------------------------------
# REASONING_DISABLE_STRATEGY — lookup table per provider
# ---------------------------------------------------------------------------

REASONING_DISABLE_STRATEGY: dict[str, str] = {
    "openai":    "reasoning_effort",   # set reasoning_effort='low'/'medium'
    "xai":       "companion_model",    # swap to non-reasoning sibling endpoint
    "mistral":   "reasoning_effort",   # magistral-* supports reasoning_effort parameter
    "deepseek":  "none",               # no toggle; always reasons (Level 3)
    "google":    "none",               # Gemini thinking models have no public toggle
    "anthropic": "none",               # Claude extended-thinking has no simple toggle
    "qwen":      "none",               # Qwen3 thinking mode can be disabled but not via standard toggle
    "meta":      "not_applicable",     # Meta Llama models in this project are non-reasoning
}

# ---------------------------------------------------------------------------
# no_reasoning_compliance — 5-value classification
# ---------------------------------------------------------------------------

# Values:
#   "not_required"   — non-reasoning model; calibration is direct (clean by definition)
#   "companion"      — reasoning model calibrated via non-reasoning sibling (Level 1)
#   "toggle"         — reasoning model calibrated via internal reasoning-disable toggle (Level 2)
#   "pool"           — always-reasoning model; no companion/toggle; uses estimated pool (Level 3)
#   "pool_eligible"  — non-reasoning model suitable as pool baseline provider

# threshold: reasoning_tokens below this → baseline considered clean
CLEAN_REASONING_THRESHOLD = 30

# ---------------------------------------------------------------------------
# Pool configuration (Level 3 — estimated baseline)
# ---------------------------------------------------------------------------

# Ordered priority list of 4 pool candidates.
# At run creation, 3 are selected (in order) based on which API keys are available.
# Claude-haiku may substitute for at most 1 slot (max_as_substitute=True).
POOL_CANDIDATES: list[dict] = [
    {
        "model_name": "grok-4.20-0309-non-reasoning",
        "provider":   "xai",
        "api_key":    "xai_api_key",
        "max_as_substitute": False,
    },
    {
        "model_name": "magistral-medium-latest",
        "provider":   "mistral",
        "api_key":    "mistral_api_key",
        "max_as_substitute": False,
    },
    {
        "model_name": "gemini-2.5-flash-lite",
        "provider":   "google",
        "api_key":    "google_api_key",
        "max_as_substitute": False,
    },
    {
        "model_name": "claude-haiku-4-5",
        "provider":   "anthropic",
        "api_key":    "anthropic_api_key",
        "max_as_substitute": True,   # allowed for at most 1 substitution
    },
]

_POOL_SIZE = 3
_POOL_MIN_FAMILIES = 3


def select_pool_models(settings: dict, db) -> list[dict]:
    """Select exactly 3 pool models from 4 candidates.

    Selection rules:
    - Try candidates in priority order (POOL_CANDIDATES list).
    - Skip candidates whose API key is missing from settings.
    - Claude-haiku (max_as_substitute=True) may fill at most 1 slot.
    - At least 3 distinct provider families must be represented.
    - Returns a list of model dicts {model_name, provider, model_id} (empty if requirements unmet).
    """
    selected: list[dict] = []
    substitute_used = False
    providers_in_pool: set[str] = set()

    conn = db.get_connection()
    try:
        for candidate in POOL_CANDIDATES:
            if len(selected) >= _POOL_SIZE:
                break
            if not settings.get(candidate["api_key"]):
                continue
            if candidate.get("max_as_substitute") and substitute_used:
                continue

            # Look up model_id from DB (model must be active)
            row = conn.execute(
                """SELECT m.id FROM models m
                   JOIN providers p ON p.id = m.provider_id
                   WHERE m.name = ? AND p.name = ? AND m.is_active = 1""",
                (candidate["model_name"], candidate["provider"]),
            ).fetchone()
            if not row:
                logger.warning(
                    "Pool candidate %s/%s not found in models table; skipping",
                    candidate["provider"], candidate["model_name"],
                )
                continue

            if candidate.get("max_as_substitute"):
                substitute_used = True

            selected.append({
                "model_name": candidate["model_name"],
                "provider":   candidate["provider"],
                "model_id":   row["id"],
                "api_key":    candidate["api_key"],
            })
            providers_in_pool.add(candidate["provider"])
    finally:
        conn.close()

    if len(selected) < _POOL_SIZE:
        logger.warning(
            "Pool selection failed: only %d of %d required models available",
            len(selected), _POOL_SIZE,
        )
        return []

    if len(providers_in_pool) < _POOL_MIN_FAMILIES:
        logger.warning(
            "Pool selection failed: only %d of %d required API families represented",
            len(providers_in_pool), _POOL_MIN_FAMILIES,
        )
        return []

    return selected


# ---------------------------------------------------------------------------
# no_reasoning_compliance computation
# ---------------------------------------------------------------------------


def compute_no_reasoning_compliance(
    model_name: str,
    is_reasoning: bool,
    provider: str,
) -> str:
    """Classify a model's ability to run without reasoning for calibration.

    Returns one of 5 values:
    - 'not_required'   — non-reasoning model; calibration is direct
    - 'companion'      — reasoning model; Level 1 (non-reasoning sibling)
    - 'toggle'         — reasoning model; Level 2 (internal toggle)
    - 'pool'           — reasoning model; Level 3 (no toggle; estimated via pool)
    - 'pool_eligible'  — non-reasoning model suitable as pool provider
    """
    if not is_reasoning:
        for c in POOL_CANDIDATES:
            if c["model_name"] == model_name and c["provider"] == provider:
                return "pool_eligible"
        return "not_required"

    if model_name in REASONING_TO_CALIBRATION_MODEL:
        return "companion"

    strategy = REASONING_DISABLE_STRATEGY.get(provider, "none")
    if strategy == "reasoning_effort":
        mn = model_name.lower()
        if any(mn.startswith(p) for p in MODELS_WITH_REASONING_TOGGLE_PREFIX):
            return "toggle"
        # Mistral magistral-* supports reasoning_effort
        if provider == "mistral" and mn.startswith("magistral"):
            return "toggle"

    return "pool"


# ---------------------------------------------------------------------------
# baseline_quality computation
# ---------------------------------------------------------------------------


def compute_baseline_quality(
    reasoning_tokens: int,
    attempt_status: str,
    reasoning_explicitly_disabled: bool,
) -> str:
    """Compute baseline_quality for a calibration result row.

    Returns 'clean' | 'degraded' | 'invalid'
    """
    if attempt_status != "success":
        return "invalid"
    if reasoning_explicitly_disabled and reasoning_tokens <= CLEAN_REASONING_THRESHOLD:
        return "clean"
    if reasoning_tokens <= CLEAN_REASONING_THRESHOLD:
        return "clean"
    return "degraded"


# ---------------------------------------------------------------------------
# Calibration model resolution — 3-level cascade
# ---------------------------------------------------------------------------


def resolve_calibration_model(
    model_name: str,
    is_reasoning: bool,
    provider: str,
) -> tuple[str, bool, bool, str]:
    """Return (effective_model_name, effective_is_reasoning, reasoning_explicitly_disabled, baseline_source).

    baseline_source values:
      'real_companion'  — model swapped to non-reasoning sibling (Level 1)
      'real_toggle'     — reasoning disabled via internal toggle (Level 2)
      'estimated_pool'  — always-reasoning; no companion/toggle (Level 3)
      'direct'          — model is already non-reasoning; measured directly

    For calibration we always want is_reasoning=False so reasoning models
    produce a baseline without hidden reasoning traces where possible.
    """
    # Non-reasoning models: measured directly — no cascade needed
    if not is_reasoning:
        return model_name, False, False, "direct"

    # Level 1: companion model swap (Grok-reasoning → Grok-non-reasoning)
    if model_name in REASONING_TO_CALIBRATION_MODEL:
        effective_model = REASONING_TO_CALIBRATION_MODEL[model_name]
        return effective_model, False, True, "real_companion"

    # Level 2: internal toggle (OpenAI reasoning_effort, Mistral reasoning_effort)
    strategy = REASONING_DISABLE_STRATEGY.get(provider, "none")
    if strategy == "reasoning_effort":
        mn = model_name.lower()
        is_toggle_model = (
            any(mn.startswith(p) for p in MODELS_WITH_REASONING_TOGGLE_PREFIX)
            or (provider == "mistral" and mn.startswith("magistral"))
        )
        if is_toggle_model:
            return model_name, False, True, "real_toggle"

    # Level 3: always-reasoning; pool will provide the estimated baseline
    # Run the model with is_reasoning=False as best-effort; baseline_quality may be degraded.
    # baseline_source='estimated_pool' flags that the final baseline rate will come from pool,
    # not from this model's own (possibly degraded) calibration data.
    return model_name, False, False, "estimated_pool"


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

    English (language_code='en') returns the original text directly.
    """
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
# Baseline rate computation — 3-level cascade
# ---------------------------------------------------------------------------


def compute_baseline_rates(
    calibration_results: list[dict],
    pool_model_names: Optional[list[str]] = None,
) -> dict:
    """Compute per-model baseline streaming rate using the 3-level cascade.

    Level 1 & 2 models: rate from their own clean calibration trials.
    Level 3 models (estimated_pool): rate = cross-pool median from pool models' clean trials.

    Uses only cal_03_long and cal_04_long_varied (stable output length) and only
    baseline_quality='clean' trials.

    Rate = visible_output_tokens / (time_to_completion_ms / 1000)  [tok/sec]

    Args:
        calibration_results: list of calibration result dicts from get_calibration_results_by_run()
        pool_model_names:    names of the 3 selected pool models for this run (used to
                             compute cross-pool median for Level 3 models)

    Returns per-model dict:
        {
            "model_name": {
                "baseline_source": "real_companion" | "real_toggle" | "estimated_pool" | "direct",
                "languages": {
                    "en": {
                        "rate_tok_per_sec_median": 56.3,
                        "rate_tok_per_sec_p25":    52.1,
                        "rate_tok_per_sec_p75":    61.8,
                        "baseline_ttft_ms_median": 1842,
                        "n_clean_trials":          16,
                        "quality":                 "clean",
                        # only present for estimated_pool:
                        "cross_pool_median": 56.3,
                        "rate_per_model": {"pool_model_1": 55.0, ...},
                        "n_pool_models":   3,
                    }
                }
            }
        }
    """
    pool_names = set(pool_model_names or [])

    # Collect per-(model_name, language_code, baseline_source) clean rates and TTFTs
    rate_store:  dict[tuple, list[float]] = {}
    ttft_store:  dict[tuple, list[int]]   = {}
    source_map:  dict[str, str]           = {}  # model_name → baseline_source

    for r in calibration_results:
        if r.get("baseline_quality") != "clean":
            continue
        if r.get("attempt_status") != "success":
            continue
        slug = r.get("cal_prompt_slug", "")
        if slug not in BASELINE_RATE_SLUGS:
            continue

        vot           = r.get("visible_output_tokens") or 0
        completion_ms = r.get("time_to_completion_ms") or 0
        ttft_ms       = r.get("time_to_first_token_ms")

        if vot <= 0 or completion_ms <= 0:
            continue

        rate      = vot / (completion_ms / 1000.0)
        model_name = r.get("model_name", "")
        lang_code  = r.get("language_code", "")
        bsource    = r.get("baseline_source") or "direct"

        key = (model_name, lang_code)
        rate_store.setdefault(key, []).append(rate)
        if ttft_ms is not None:
            ttft_store.setdefault(key, []).append(ttft_ms)
        if model_name not in source_map:
            source_map[model_name] = bsource

    # Build per-model language rate dicts for Level 1/2/direct models
    result: dict = {}
    for (model_name, lang_code), rates in rate_store.items():
        if not rates:
            continue
        bsource = source_map.get(model_name, "direct")
        sorted_rates = sorted(rates)
        n = len(sorted_rates)
        p25_idx = max(0, int(n * 0.25) - 1)
        p75_idx = min(n - 1, int(n * 0.75))

        ttft_list   = ttft_store.get((model_name, lang_code), [])
        ttft_median = round(statistics.median(ttft_list), 1) if ttft_list else None

        lang_entry = {
            "rate_tok_per_sec_median": round(statistics.median(sorted_rates), 2),
            "rate_tok_per_sec_p25":    round(sorted_rates[p25_idx], 2),
            "rate_tok_per_sec_p75":    round(sorted_rates[p75_idx], 2),
            "baseline_ttft_ms_median": ttft_median,
            "n_clean_trials":          n,
            "quality":                 "clean",
        }
        result.setdefault(model_name, {"baseline_source": bsource, "languages": {}})
        result[model_name]["languages"][lang_code] = lang_entry

    # Compute cross-pool median for each language (using pool models' direct/toggle rates)
    # This is used as the estimated baseline for Level 3 models.
    pool_rates_by_lang: dict[str, dict[str, list[float]]] = {}
    if pool_names:
        for r in calibration_results:
            if r.get("baseline_quality") != "clean":
                continue
            if r.get("attempt_status") != "success":
                continue
            slug = r.get("cal_prompt_slug", "")
            if slug not in BASELINE_RATE_SLUGS:
                continue
            model_name = r.get("model_name", "")
            if model_name not in pool_names:
                continue
            vot           = r.get("visible_output_tokens") or 0
            completion_ms = r.get("time_to_completion_ms") or 0
            if vot <= 0 or completion_ms <= 0:
                continue
            rate      = vot / (completion_ms / 1000.0)
            lang_code = r.get("language_code", "")
            pool_rates_by_lang.setdefault(lang_code, {}).setdefault(model_name, []).append(rate)

    # For Level 3 models (estimated_pool), inject cross-pool median.
    # These models are NOT in rate_store (they have degraded/no clean data of their own);
    # instead, scan all calibration_results for rows with baseline_source='estimated_pool'.
    level3_langs: dict[str, set[str]] = {}  # model_name → set of lang_codes
    for r in calibration_results:
        if r.get("baseline_source") == "estimated_pool":
            mn = r.get("model_name", "")
            lc = r.get("language_code", "")
            if mn and lc:
                level3_langs.setdefault(mn, set()).add(lc)

    for model_name, lang_codes in level3_langs.items():
        for lang_code in lang_codes:
            if lang_code not in pool_rates_by_lang:
                continue

            per_model = {
                mn: round(statistics.median(rates), 2)
                for mn, rates in pool_rates_by_lang[lang_code].items()
                if rates
            }
            if not per_model:
                continue

            all_pool_rates = [v for rates in pool_rates_by_lang[lang_code].values() for v in rates]
            cross_median   = round(statistics.median(all_pool_rates), 2) if all_pool_rates else None

            result.setdefault(model_name, {"baseline_source": "estimated_pool", "languages": {}})
            result[model_name]["baseline_source"] = "estimated_pool"
            result[model_name]["languages"][lang_code] = {
                "rate_tok_per_sec_median": cross_median,
                "cross_pool_median":       cross_median,
                "rate_per_model":          per_model,
                "n_pool_models":           len(per_model),
                "quality":                 "estimated",
            }

    # Fill in degraded entries for models that had no clean trials
    degraded_models: set[str] = set()
    for r in calibration_results:
        if r.get("baseline_quality") == "degraded":
            degraded_models.add(r.get("model_name", ""))

    for model_name in degraded_models:
        if model_name in result:
            continue
        bsource = source_map.get(model_name, "direct")
        langs = {
            r.get("language_code", "")
            for r in calibration_results
            if r.get("model_name") == model_name
        }
        result[model_name] = {
            "baseline_source": bsource,
            "languages": {
                lc: {
                    "rate_tok_per_sec_median": None,
                    "rate_tok_per_sec_p25":    None,
                    "rate_tok_per_sec_p75":    None,
                    "baseline_ttft_ms_median": None,
                    "n_clean_trials":           0,
                    "quality":                 "degraded",
                }
                for lc in langs
            },
        }

    return result


# ---------------------------------------------------------------------------
# Prefix-caching evidence computation
# ---------------------------------------------------------------------------


def compute_prefix_caching_evidence(token_results: list[dict]) -> dict:
    """Detect potential server-side prefix caching from TTFT patterns.

    For each (model, prompt, language) cell, computes median TTFT of first
    repetition vs last. A positive delta (first > last) suggests caching warmup.

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
    cell_data: dict[tuple, list[tuple[int, int]]] = {}

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

    model_deltas: dict[str, list[float]] = {}
    for (model_name, pid, lid), vals in cell_data.items():
        if len(vals) < 2:
            continue
        vals.sort(key=lambda x: x[0])
        first_ttft = vals[0][1]
        last_ttft  = vals[-1][1]
        delta = first_ttft - last_ttft
        model_deltas.setdefault(model_name, []).append(delta)

    result: dict = {}
    for model_name, deltas in model_deltas.items():
        if not deltas:
            continue
        med = statistics.median(deltas)
        result[model_name] = {
            "delta_ttft_first_vs_last_ms_median": round(med, 2),
            "n_cells_analysed":                   len(deltas),
            "caching_likely":                     med > 50,
        }

    return result
