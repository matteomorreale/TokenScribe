"""
TokenScribe — MAGI Service (Phase 2)
Author: Matteo Morreale

Implements the three-judge LLM panel: Balthasar, Caspar, Melchior.
Each judge independently evaluates a translation on three dimensions (1–5):
  semantic_fidelity, register_match, naturalness.
The panel score is the mean of normalized dimension scores ((v-1)/4 → 0–1).
"""

import json as _json
import logging
import re
import statistics

logger = logging.getLogger(__name__)

JUDGE_NAMES = ["balthasar", "caspar", "melchior"]
MAX_RETRIES = 3

_PROVIDER_KEY_MAP = {
    "openai":    "openai_api_key",
    "anthropic": "anthropic_api_key",
    "google":    "google_api_key",
    "deepseek":  "deepseek_api_key",
    "meta":      "meta_api_key",
    "qwen":      "qwen_api_key",
    "mistral":   "mistral_api_key",
}


def get_magi_status(settings: dict, em) -> dict:
    """
    Returns MAGI system status for display as a traffic light.

    status: 'green' = all 3 judges configured and API keys present
            'orange' = 1-2 judges OK
            'red'    = no judges configured or no API keys

    Requires settings dict (from SettingsModel.get_all()) and
    an ExperimentModel instance (for get_model_by_id).
    """
    judge_defs = [
        ("magi_judge_balthasar_id", "Balthasar"),
        ("magi_judge_caspar_id", "Caspar"),
        ("magi_judge_melchior_id", "Melchior"),
    ]
    judges = []
    for setting_key, name in judge_defs:
        mid = settings.get(setting_key)
        if not mid:
            judges.append({
                "name": name, "model_name": None, "provider": None,
                "api_key_ok": False, "configured": False,
                "reason": "Modello giudice non configurato",
            })
            continue
        model_info = em.get_model_by_id(int(mid))
        if not model_info:
            judges.append({
                "name": name, "model_name": f"ID:{mid} (non trovato)",
                "provider": None, "api_key_ok": False, "configured": False,
                "reason": f"Modello ID:{mid} non trovato nel DB",
            })
            continue
        provider = model_info.get("provider_name", "")
        api_key_setting = _PROVIDER_KEY_MAP.get(provider, f"{provider}_api_key")
        api_key_ok = bool((settings.get(api_key_setting) or "").strip())
        reason = "OK" if api_key_ok else f"API key {provider} non configurata"
        judges.append({
            "name": name,
            "model_name": model_info.get("name", ""),
            "provider": provider,
            "api_key_ok": api_key_ok,
            "configured": True,
            "reason": reason,
        })

    active = [j for j in judges if j["configured"] and j["api_key_ok"]]
    active_count = len(active)

    if active_count == 3:
        status = "green"
        tooltip = (
            "MAGI System online — tutti e 3 i giudici attivi: "
            + ", ".join(f"{j['name']} ({j['model_name']})" for j in judges)
        )
    elif active_count > 0:
        status = "orange"
        problems = [j["name"] + ": " + j["reason"] for j in judges if not (j["configured"] and j["api_key_ok"])]
        tooltip = "MAGI System parzialmente attivo — " + "; ".join(problems)
    else:
        status = "red"
        problems = [j["name"] + ": " + j["reason"] for j in judges]
        tooltip = "MAGI System offline — " + "; ".join(problems)

    return {"status": status, "judges": judges, "tooltip": tooltip, "active_count": active_count}

_JUDGE_PROMPT = """\
You are a translation quality evaluator for a scientific linguistic experiment.

## Input

Original text (English):
{original}

Target language: {language}
Translation:
{translation}

## Reference metrics (computed externally)

- Semantic Fidelity Score (SFS): {sfs:.4f}  [0 = unrelated, 1 = identical meaning]
- Length Expansion Ratio (LER):  {ler:.3f}  [1.0 = same length as original; typical range 0.8–1.5]

## Task

Evaluate the translation on three independent dimensions.
Score each dimension as an integer from 1 to 5:

1. **semantic_fidelity** — Does the translation preserve the full meaning of the original?
   1 = critical meaning lost  …  5 = meaning perfectly preserved

2. **register_match** — Is the formality/tone appropriate for the target language and context?
   1 = register completely wrong  …  5 = register perfectly appropriate

3. **naturalness** — Does the translation sound natural and idiomatic in the target language?
   1 = unnatural/broken  …  5 = fully natural and fluent

## Output format (MANDATORY)

Respond with a SINGLE JSON object containing exactly these three integer keys.
No extra fields, no explanation, no markdown fences.

Example of a valid response:
{{"semantic_fidelity": 4, "register_match": 5, "naturalness": 4}}\
"""


class MAGIService:
    DISAGREEMENT_THRESHOLD = 0.15  # stdev above which judges are considered to disagree

    def evaluate(
        self,
        original: str,
        translation: str,
        language: str,
        sfs: float,
        ler_char: float,
        llm_service,
        model_info: dict,
        log_service=None,
        context_ref: dict | None = None,
    ) -> dict:
        """Call one judge with up to MAX_RETRIES attempts. Returns the first successful parse."""
        prompt = _JUDGE_PROMPT.format(
            original=original,
            language=language,
            translation=translation,
            sfs=sfs or 0.0,
            ler=ler_char or 1.0,
        )
        last_verdict = None
        for attempt in range(1, MAX_RETRIES + 1):
            if log_service:
                log_service.log(
                    operation_type="magi",
                    event="judge_attempt",
                    level="DEBUG",
                    provider=model_info.get("provider_name"),
                    model=model_info.get("name"),
                    message=(
                        f"[MAGI] {model_info.get('name')} attempt {attempt}/{MAX_RETRIES}"
                    ),
                    context_ref=context_ref,
                    payload={
                        "attempt": attempt,
                        "prompt_preview": prompt[:300],
                        "language": language,
                        "sfs": sfs,
                        "ler_char": ler_char,
                    },
                )

            verdict = self._call_once(prompt, model_info, llm_service, attempt)
            last_verdict = verdict

            if verdict["score"] is not None:
                if attempt > 1:
                    logger.info(
                        "[MAGI] %s (%s) succeeded on attempt %d/3",
                        model_info["name"], model_info["name"], attempt,
                    )
                if log_service:
                    log_service.log(
                        operation_type="magi",
                        event="judge_success",
                        level="INFO",
                        provider=model_info.get("provider_name"),
                        model=model_info.get("name"),
                        message=(
                            f"[MAGI] {model_info.get('name')} → score={verdict['score']:.4f} "
                            f"(sf={verdict.get('semantic_fidelity')} "
                            f"rm={verdict.get('register_match')} "
                            f"na={verdict.get('naturalness')}) "
                            f"after {attempt} attempt(s)"
                        ),
                        context_ref=context_ref,
                        payload={
                            "attempt": attempt,
                            "score": verdict["score"],
                            "semantic_fidelity": verdict.get("semantic_fidelity"),
                            "register_match": verdict.get("register_match"),
                            "naturalness": verdict.get("naturalness"),
                            "raw_response": (verdict.get("raw_response") or "")[:500],
                            "parse_error": verdict.get("error"),
                        },
                    )
                return verdict

            logger.warning(
                "[MAGI] (%s) attempt %d/%d failed — error: %s | raw: %r — retrying",
                model_info["name"], attempt, MAX_RETRIES,
                verdict.get("error"), verdict.get("raw_response"),
            )
            if log_service:
                log_service.log(
                    operation_type="magi",
                    event="judge_retry" if attempt < MAX_RETRIES else "judge_failed",
                    level="WARNING",
                    provider=model_info.get("provider_name"),
                    model=model_info.get("name"),
                    message=(
                        f"[MAGI] {model_info.get('name')} attempt {attempt}/{MAX_RETRIES} failed: "
                        f"{verdict.get('error')}"
                    ),
                    context_ref=context_ref,
                    payload={
                        "attempt": attempt,
                        "error": verdict.get("error"),
                        "raw_response": (verdict.get("raw_response") or "")[:500],
                    },
                )

        return last_verdict

    def _call_once(self, prompt: str, model_info: dict, llm_service, attempt: int) -> dict:
        """Single LLM call attempt. Returns verdict dict."""
        try:
            result = llm_service.call(
                provider=model_info["provider_name"],
                model_name=model_info["name"],
                prompt_text=prompt,
                cost_per_input=0.0,
                cost_per_output=0.0,
                is_reasoning=bool(model_info.get("is_reasoning", 0)),
            )
            if result.success:
                raw = result.response_text or ""
                verdict = self._parse_verdict(raw)
                return {
                    "model_id": model_info["id"],
                    "model_name": model_info["name"],
                    "semantic_fidelity": verdict["semantic_fidelity"],
                    "register_match": verdict["register_match"],
                    "naturalness": verdict["naturalness"],
                    "score": verdict["score"],
                    "raw_response": raw,
                    "error": verdict["error"],
                    "attempts": attempt,
                }
            return {
                "model_id": model_info["id"],
                "model_name": model_info["name"],
                "semantic_fidelity": None,
                "register_match": None,
                "naturalness": None,
                "score": None,
                "raw_response": None,
                "error": f"API error: {result.error}",
                "attempts": attempt,
            }
        except Exception as exc:
            return {
                "model_id": model_info.get("id"),
                "model_name": model_info.get("name"),
                "semantic_fidelity": None,
                "register_match": None,
                "naturalness": None,
                "score": None,
                "raw_response": None,
                "error": f"Exception: {exc}",
                "attempts": attempt,
            }

    def run_panel(
        self,
        original: str,
        translation: str,
        language: str,
        sfs: float,
        ler_char: float,
        llm_service,
        judge_models: list,
        log_service=None,
        context_ref: dict | None = None,
    ) -> dict:
        """
        Call three judges sequentially and aggregate results.
        judge_models: list of exactly 3 model_info dicts (Balthasar, Caspar, Melchior).
        Returns: {judges: {name: verdict}, magi_score, magi_disagreement}
        """
        if log_service:
            log_service.log(
                operation_type="magi",
                event="panel_start",
                level="INFO",
                message=f"[MAGI] Panel started — language={language} sfs={sfs:.4f} ler={ler_char:.3f}",
                context_ref=context_ref,
                payload={
                    "language": language,
                    "sfs": sfs,
                    "ler_char": ler_char,
                    "judges": [m.get("name") for m in judge_models[:3]],
                    "original_preview": (original or "")[:200],
                    "translation_preview": (translation or "")[:200],
                },
            )

        judges = {}
        for name, model_info in zip(JUDGE_NAMES, judge_models[:3]):
            judge_ctx = {**(context_ref or {}), "judge_name": name}
            verdict = self.evaluate(
                original, translation, language, sfs, ler_char,
                llm_service, model_info,
                log_service=log_service,
                context_ref=judge_ctx,
            )
            judges[name] = verdict
            if verdict["score"] is not None:
                dims = (
                    f"sf={verdict['semantic_fidelity']} rm={verdict['register_match']} na={verdict['naturalness']}"
                    if verdict.get("semantic_fidelity") is not None
                    else "holistic fallback"
                )
                logger.info(
                    "[MAGI] %s (%s) → %.4f [%s] after %d attempt(s) | raw: %r",
                    name, model_info["name"], verdict["score"], dims,
                    verdict.get("attempts", 1), verdict.get("raw_response"),
                )
            else:
                offline_reason = (
                    f"Judge {name} ({model_info.get('name', '')}) "
                    f"failed after {MAX_RETRIES} attempt(s): {verdict.get('error', 'unknown error')}"
                )
                logger.error("[MAGI] %s — panel aborted: %s", name, offline_reason)
                if log_service:
                    log_service.log(
                        operation_type="magi",
                        event="panel_aborted",
                        level="ERROR",
                        provider=model_info.get("provider_name"),
                        model=model_info.get("name"),
                        message=f"[MAGI] Panel aborted — {offline_reason}",
                        context_ref=context_ref,
                        payload={
                            "judge_name": name,
                            "error": verdict.get("error"),
                            "judges_evaluated": list(judges.keys()),
                        },
                    )
                return {
                    "judges": judges,
                    "magi_score": None,
                    "magi_disagreement": False,
                    "magi_offline": True,
                    "magi_offline_reason": offline_reason,
                }

        valid = [v["score"] for v in judges.values() if v["score"] is not None]
        magi_score = round(statistics.mean(valid), 6) if valid else None
        magi_disagreement = (
            statistics.stdev(valid) > self.DISAGREEMENT_THRESHOLD
            if len(valid) >= 2
            else False
        )

        if log_service:
            log_service.log(
                operation_type="magi",
                event="panel_complete",
                level="INFO" if magi_score is not None else "WARNING",
                message=(
                    f"[MAGI] Panel complete — score={magi_score:.4f}" if magi_score is not None
                    else "[MAGI] Panel complete — all judges failed"
                )
                + (" (DISAGREEMENT)" if magi_disagreement else ""),
                context_ref=context_ref,
                payload={
                    "magi_score": magi_score,
                    "magi_disagreement": magi_disagreement,
                    "valid_judge_count": len(valid),
                    "judge_scores": {
                        judge_name: v.get("score")
                        for judge_name, v in judges.items()
                    },
                    "judge_details": {
                        judge_name: {
                            "semantic_fidelity": v.get("semantic_fidelity"),
                            "register_match": v.get("register_match"),
                            "naturalness": v.get("naturalness"),
                            "attempts": v.get("attempts"),
                            "error": v.get("error"),
                        }
                        for judge_name, v in judges.items()
                    },
                },
            )

        return {
            "judges": judges,
            "magi_score": magi_score,
            "magi_disagreement": magi_disagreement,
            "magi_offline": False,
            "magi_offline_reason": None,
        }

    # ------------------------------------------------------------------
    # Answer discovery — 3-judge panel, majority vote (≥2/3)
    # ------------------------------------------------------------------

    _ANSWER_DISCOVERY_PROMPT = """\
You are a fact-checking assistant for a scientific linguistic experiment.

Prompt given to the model (in {language}):
{prompt_text}

Model response:
{response_text}

Task: Determine whether the response contains the correct factual answer to the prompt.
If it does, extract the minimal canonical surface form of the answer exactly as it appears.

Respond with a SINGLE JSON object — no explanation, no markdown fences:
{{"is_correct": true or false, "canonical_form": "the answer text" or null}}
"""

    def _call_discovery_once(
        self, prompt: str, model_info: dict, llm_service, judge_name: str
    ) -> dict:
        """Single judge attempt for answer discovery. Returns parsed result or failure."""
        for attempt in range(1, MAX_RETRIES + 1):
            result = self._call_once(prompt, model_info, llm_service, attempt)
            raw = result.get("raw_response") or ""
            parsed = self._parse_json_bool_response(raw)
            if parsed is not None:
                return {
                    "judge_name":     judge_name,
                    "judge_model":    model_info.get("name", ""),
                    "is_correct":     parsed["is_correct"],
                    "canonical_form": parsed.get("canonical_form"),
                    "error":          None,
                }
            logger.warning(
                "[MAGI:discovery:%s] attempt %d/%d parse failed — raw: %r",
                judge_name, attempt, MAX_RETRIES, raw[:200],
            )
        return {
            "judge_name": judge_name, "judge_model": model_info.get("name", ""),
            "is_correct": False, "canonical_form": None,
            "error": f"All {MAX_RETRIES} parse attempts failed",
        }

    def discover_answer_variant(
        self,
        prompt_text: str,
        language: str,
        response_text: str,
        llm_service,
        judge_models: list[dict],
        log_service=None,
        context_ref: dict | None = None,
    ) -> dict:
        """
        3-judge panel with majority vote (≥2 of 3) for answer correctness.

        Returns:
          is_correct     — True if ≥2 judges agree the answer is correct
          canonical_form — surface form from the first judge who said True (or None)
          judges         — per-judge breakdown dict
        """
        prompt = self._ANSWER_DISCOVERY_PROMPT.format(
            language=language,
            prompt_text=prompt_text,
            response_text=response_text,
        )
        judges = {}
        for name, model_info in zip(JUDGE_NAMES, judge_models[:3]):
            verdict = self._call_discovery_once(prompt, model_info, llm_service, name)
            judges[name] = verdict

        positive = [v for v in judges.values() if v["is_correct"]]
        is_correct = len(positive) >= 2

        # Canonical form: first positive judge's extraction (or None)
        canonical_form = next(
            (v["canonical_form"] for v in positive if v["canonical_form"]),
            None,
        )

        logger.info(
            "[MAGI:discovery] panel result: is_correct=%s (%d/3 agree) canonical='%s'",
            is_correct, len(positive), canonical_form,
        )
        return {"is_correct": is_correct, "canonical_form": canonical_form, "judges": judges}

    # ------------------------------------------------------------------
    # Named-entity labeling — 3-judge panel, majority vote per entity
    # ------------------------------------------------------------------

    _NE_LABELING_PROMPT = """\
You are annotating named entities for a linguistic experiment on model output fidelity.

Prompt (English original):
{prompt_text}

Target language: {language}

Task: List every named entity in the prompt: places, proper names, technical terms, acronyms.
For each entity, provide the standard localized form a native {language} speaker would write.

Respond with a JSON array — no explanation, no markdown fences:
[{{"entity": "English form", "expected_form": "form in {language}", "allow_original": true or false}}]

- "entity":         the entity as it appears in the English prompt
- "expected_form":  the expected localized form in {language}
- "allow_original": true if the English form is also acceptable in {language} responses

If the prompt contains no named entities, respond with an empty array: []
"""

    def _call_ne_labeling_once(
        self, prompt: str, model_info: dict, llm_service, judge_name: str
    ) -> list[dict]:
        """Single judge attempt for NE labeling. Returns cleaned list or []."""
        for attempt in range(1, MAX_RETRIES + 1):
            result = self._call_once(prompt, model_info, llm_service, attempt)
            raw = result.get("raw_response") or ""
            parsed = self._parse_json_array_response(raw)
            if parsed is not None:
                cleaned = []
                for item in parsed:
                    if isinstance(item, dict) and item.get("entity") and item.get("expected_form"):
                        cleaned.append({
                            "entity":        str(item["entity"]).strip(),
                            "expected_form": str(item["expected_form"]).strip(),
                            "allow_original": bool(item.get("allow_original", False)),
                        })
                return cleaned
            logger.warning(
                "[MAGI:ne_labeling:%s] attempt %d/%d parse failed — raw: %r",
                judge_name, attempt, MAX_RETRIES, raw[:200],
            )
        return []

    def label_named_entities(
        self,
        prompt_text: str,
        language: str,
        llm_service,
        judge_models: list[dict],
        log_service=None,
        context_ref: dict | None = None,
    ) -> list[dict]:
        """
        3-judge panel with per-entity majority vote (≥2 of 3) for NE expectations.

        An entity is included in the result only if ≥2 judges independently identify it.
        expected_form: most common form among agreeing judges (first if tie).
        allow_original: True if ≥2 of the agreeing judges say True.
        """
        prompt = self._NE_LABELING_PROMPT.format(
            prompt_text=prompt_text,
            language=language,
        )
        # Collect per-judge entity lists
        all_judge_results: list[list[dict]] = []
        for name, model_info in zip(JUDGE_NAMES, judge_models[:3]):
            entities = self._call_ne_labeling_once(prompt, model_info, llm_service, name)
            all_judge_results.append(entities)

        # Group by normalised entity name, count votes
        from collections import Counter, defaultdict
        # entity_key → list of {expected_form, allow_original} from each judge that named it
        votes: dict[str, list[dict]] = defaultdict(list)
        entity_display: dict[str, str] = {}  # normalised key → display form (first seen)
        for judge_entities in all_judge_results:
            seen_in_this_judge: set[str] = set()
            for e in judge_entities:
                key = e["entity"].lower().strip()
                if key in seen_in_this_judge:
                    continue  # deduplicate within one judge's response
                seen_in_this_judge.add(key)
                votes[key].append({
                    "expected_form": e["expected_form"],
                    "allow_original": e["allow_original"],
                })
                if key not in entity_display:
                    entity_display[key] = e["entity"]

        result = []
        for key, judge_votes in votes.items():
            if len(judge_votes) < 2:
                continue  # majority not reached
            # expected_form: most common; ties broken by first occurrence
            form_counts = Counter(v["expected_form"] for v in judge_votes)
            best_form = form_counts.most_common(1)[0][0]
            # allow_original: True if majority of agreeing judges say so
            allow_count = sum(1 for v in judge_votes if v["allow_original"])
            allow = allow_count >= (len(judge_votes) / 2)
            result.append({
                "entity":        entity_display[key],
                "expected_form": best_form,
                "allow_original": allow,
            })

        logger.info(
            "[MAGI:ne_labeling] panel result: %d/%d entities passed majority vote for lang=%s",
            len(result),
            len(votes),
            language,
        )
        return result

    # ------------------------------------------------------------------
    # JSON parse helpers for structured single-judge outputs
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_bool_response(text: str) -> dict | None:
        """Extract {"is_correct": bool, "canonical_form": str|None} from judge output."""
        m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if not m:
            return None
        try:
            data = _json.loads(m.group())
            if "is_correct" not in data:
                return None
            return {
                "is_correct":     bool(data["is_correct"]),
                "canonical_form": data.get("canonical_form") or None,
            }
        except (_json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _parse_json_array_response(text: str) -> list | None:
        """Extract a JSON array from judge output."""
        m = re.search(r'\[.*?\]', text, re.DOTALL)
        if not m:
            return None
        try:
            data = _json.loads(m.group())
            return data if isinstance(data, list) else None
        except (_json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _parse_verdict(text: str) -> dict:
        """
        Parse a judge response into three 1–5 dimension scores.

        Tries to extract a JSON object with semantic_fidelity, register_match, naturalness.
        Each dimension is an integer 1–5; the aggregate score is mean((v-1)/4) → [0, 1].
        Falls back to _parse_score if the model returned a bare holistic float instead.
        """
        _NULL = {"semantic_fidelity": None, "register_match": None, "naturalness": None}

        if not text:
            return {**_NULL, "score": None, "error": "Empty response"}

        # Extract first JSON object from response (handles markdown fences, leading text)
        m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if m:
            try:
                data = _json.loads(m.group())
                dims = []
                for key in ("semantic_fidelity", "register_match", "naturalness"):
                    val = data.get(key)
                    if val is None:
                        raise ValueError(f"Missing key: {key}")
                    v = float(val)
                    if not (1 <= v <= 5):
                        raise ValueError(f"{key}={v} outside 1–5 range")
                    dims.append(v)
                score = round(sum((v - 1) / 4 for v in dims) / 3, 6)
                return {
                    "semantic_fidelity": int(dims[0]),
                    "register_match": int(dims[1]),
                    "naturalness": int(dims[2]),
                    "score": score,
                    "error": None,
                }
            except (ValueError, KeyError, _json.JSONDecodeError) as exc:
                logger.debug("[MAGI] JSON parse failed (%s), trying holistic fallback", exc)

        # Fallback: model returned a plain 0–1 float
        score = MAGIService._parse_score(text)
        if score is not None:
            return {**_NULL, "score": score, "error": "Holistic fallback (no valid JSON dimensions)"}

        return {**_NULL, "score": None, "error": "Parse failed: no JSON dimensions or 0–1 score found"}

    @staticmethod
    def _parse_score(text: str):
        """
        Extract a float 0–1 from an LLM response.

        Pass 1 — the whole trimmed response is a bare number.
        Pass 2 — find any 0.xx or 1.0x decimal anywhere in the text.
        Pass 3 — bare "0" or "1" as a standalone word.
        Returns None only when all passes fail.
        """
        if not text:
            return None
        t = text.strip()

        # Pass 1: bare number (possibly with leading/trailing whitespace or a period)
        m = re.match(r'^([01](?:\.\d+)?)\.?$', t)
        if m:
            return round(min(1.0, max(0.0, float(m.group(1)))), 6)

        # Pass 2: any "0.xx…" or "1.0…" decimal embedded in text
        # Negative lookbehind on "/" excludes denominators like the "1.0" in "0.92/1.0"
        candidates = re.findall(r'(?<!/)\b(1(?:\.0+)?|0\.\d+)\b', t)
        if candidates:
            # take the first match — models typically put the score before any explanation
            return round(float(candidates[0]), 6)

        # Pass 3: standalone "0" or "1"
        m = re.search(r'(?<!\d)([01])(?!\d)', t)
        if m:
            return float(m.group(1))

        return None
