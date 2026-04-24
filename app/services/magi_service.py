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
            verdict = self._call_once(prompt, model_info, llm_service, attempt)
            last_verdict = verdict
            if verdict["score"] is not None:
                if attempt > 1:
                    logger.info(
                        "[MAGI] %s (%s) succeeded on attempt %d/3",
                        model_info["name"], model_info["name"], attempt,
                    )
                return verdict
            if attempt < MAX_RETRIES:
                logger.warning(
                    "[MAGI] (%s) attempt %d/%d failed — error: %s | raw: %r — retrying",
                    model_info["name"], attempt, MAX_RETRIES,
                    verdict.get("error"), verdict.get("raw_response"),
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
    ) -> dict:
        """
        Call three judges sequentially and aggregate results.
        judge_models: list of exactly 3 model_info dicts (Balthasar, Caspar, Melchior).
        Returns: {judges: {name: verdict}, magi_score, magi_disagreement}
        """
        judges = {}
        for name, model_info in zip(JUDGE_NAMES, judge_models[:3]):
            verdict = self.evaluate(
                original, translation, language, sfs, ler_char, llm_service, model_info
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
                logger.warning(
                    "[MAGI] %s (%s) → FAILED after %d attempt(s) | error: %s | raw: %r",
                    name, model_info["name"], verdict.get("attempts", MAX_RETRIES),
                    verdict.get("error"), verdict.get("raw_response"),
                )

        valid = [v["score"] for v in judges.values() if v["score"] is not None]
        magi_score = round(statistics.mean(valid), 6) if valid else None
        magi_disagreement = (
            statistics.stdev(valid) > self.DISAGREEMENT_THRESHOLD
            if len(valid) >= 2
            else False
        )

        return {
            "judges": judges,
            "magi_score": magi_score,
            "magi_disagreement": magi_disagreement,
        }

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
