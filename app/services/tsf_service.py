"""
TokenScribe — TSF Service (Translation Strategy Fingerprint)
Author: Matteo Morreale

Implements a three-judge LLM panel to classify the translation strategy
adopted by a model for probe prompts tagged with analysis_type='tsf'.

Each judge independently classifies the response into one of four strategies:
  keep_latin        — original Latin/ASCII form preserved unchanged
  transliterate     — term phonetically transcribed into the target script
  translate_semantic — established semantic or conventional translation used
  mistranslate      — incorrect, meaningless, or unrelated rendering

Majority vote (≥ 2/3) determines the final strategy.
When all three judges disagree (1-1-1 split), strategy is None (no consensus).
"""

import json as _json
import logging
import re
from collections import Counter

logger = logging.getLogger(__name__)

JUDGE_NAMES = ["balthasar", "caspar", "melchior"]
MAX_RETRIES = 3

VALID_STRATEGIES = frozenset({"keep_latin", "transliterate", "translate_semantic", "mistranslate"})

_TSF_JUDGE_PROMPT = """\
You are a linguistic analyst evaluating translation strategy for a scientific experiment on LLM tokenization behaviour.

## Probe prompt given to the model (in {language})

{prompt_text}

## Model response

{response_text}

## Task

Classify the translation strategy the model applied to the term(s) under investigation in the probe prompt.
Choose exactly ONE strategy from the list below:

- keep_latin        — The model preserved the original Latin/ASCII form unchanged (e.g. left an English technical term as-is)
- transliterate     — The model phonetically transcribed the term into the target script without semantic translation
- translate_semantic — The model used an established semantic or conventional translation recognised by native speakers
- mistranslate      — The model produced an incorrect, meaningless, or otherwise wrong rendering

## Output format (MANDATORY)

Respond with a SINGLE JSON object — no explanation, no markdown fences, no extra fields:
{{"strategy": "keep_latin"}}

Valid values for "strategy": "keep_latin", "transliterate", "translate_semantic", "mistranslate".\
"""


class TSFService:

    def classify_once(
        self,
        prompt: str,
        model_info: dict,
        llm_service,
        judge_name: str,
    ) -> dict:
        """Single judge attempt with up to MAX_RETRIES. Returns per-judge verdict dict."""
        last = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = llm_service.call(
                    provider=model_info["provider_name"],
                    model_name=model_info["name"],
                    prompt_text=prompt,
                    cost_per_input=0.0,
                    cost_per_output=0.0,
                    is_reasoning=bool(model_info.get("is_reasoning", 0)),
                )
                if not result.success:
                    last = self._failure(model_info, judge_name, attempt, error=f"API error: {result.error}")
                    continue
                raw = result.response_text or ""
                strategy = self._parse_strategy(raw)
                if strategy is not None:
                    logger.info(
                        "[TSF:%s] %s → strategy=%s after %d attempt(s)",
                        judge_name, model_info["name"], strategy, attempt,
                    )
                    return {
                        "model_id":   model_info["id"],
                        "model_name": model_info["name"],
                        "strategy":   strategy,
                        "raw_response": raw,
                        "error":      None,
                        "attempts":   attempt,
                    }
                logger.warning(
                    "[TSF:%s] %s attempt %d/%d parse failed — raw: %r",
                    judge_name, model_info["name"], attempt, MAX_RETRIES, raw[:200],
                )
                last = self._failure(
                    model_info, judge_name, attempt,
                    error=f"Parse failed: no valid strategy in response",
                    raw=raw,
                )
            except Exception as exc:
                last = self._failure(model_info, judge_name, attempt, error=f"Exception: {exc}")
        return last

    def run_panel(
        self,
        prompt_text: str,
        language: str,
        response_text: str,
        llm_service,
        judge_models: list,
    ) -> dict:
        """
        Call three judges and aggregate by majority vote (≥ 2/3).

        Returns:
          strategy  — winning strategy string, or None if no majority
          judges    — per-judge breakdown dict keyed by judge name
        """
        built_prompt = _TSF_JUDGE_PROMPT.format(
            language=language,
            prompt_text=prompt_text,
            response_text=response_text,
        )
        judges = {}
        for name, model_info in zip(JUDGE_NAMES, judge_models[:3]):
            verdict = self.classify_once(built_prompt, model_info, llm_service, name)
            judges[name] = verdict

        # Majority vote
        votes = [v["strategy"] for v in judges.values() if v["strategy"] is not None]
        if not votes:
            strategy = None
        else:
            counts = Counter(votes)
            top_strategy, top_count = counts.most_common(1)[0]
            strategy = top_strategy if top_count >= 2 else None

        logger.info(
            "[TSF] Panel result: strategy=%s (votes: %s)",
            strategy,
            {s: c for s, c in Counter(votes).items()} if votes else "none",
        )
        return {"strategy": strategy, "judges": judges}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_strategy(text: str) -> str | None:
        """Extract the strategy value from a JSON response."""
        if not text:
            return None
        m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if m:
            try:
                data = _json.loads(m.group())
                val = data.get("strategy", "")
                if val in VALID_STRATEGIES:
                    return val
            except (_json.JSONDecodeError, TypeError):
                pass
        # Fallback: bare strategy keyword anywhere in the text
        for strategy in VALID_STRATEGIES:
            if re.search(r'\b' + re.escape(strategy) + r'\b', text):
                return strategy
        return None

    @staticmethod
    def _failure(model_info: dict, judge_name: str, attempt: int, error: str, raw: str = None) -> dict:
        return {
            "model_id":     model_info.get("id"),
            "model_name":   model_info.get("name"),
            "strategy":     None,
            "raw_response": raw,
            "error":        error,
            "attempts":     attempt,
        }
