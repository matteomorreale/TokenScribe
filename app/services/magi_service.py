"""
TokenScribe — MAGI Service (Phase 2)
Author: Matteo Morreale

Implements the three-judge LLM panel: Balthasar, Caspar, Melchior.
Each judge independently evaluates a translation candidate and returns a
quality score 0.0–1.0. The panel aggregates verdicts and flags disagreement.
"""

import re
import statistics


JUDGE_NAMES = ["balthasar", "caspar", "melchior"]

_JUDGE_PROMPT = """\
You are evaluating the quality of a translation for a scientific linguistic experiment.

Original text (English): "{original}"
Target language: {language}
Translation: "{translation}"

Reference metrics (computed externally):
  Semantic Fidelity Score (SFS): {sfs:.4f}   [0 = no similarity, 1 = identical meaning]
  Length Expansion Ratio  (LER): {ler:.3f}   [1.0 = same length as original; typical 1.0–1.3]

Rate the overall translation quality from 0.0 to 1.0, considering semantic accuracy,
fluency in the target language, and cultural appropriateness.

Respond with ONLY a single decimal number between 0.0 and 1.0. No explanation, no text.\
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
        """Call one judge and return its verdict dict."""
        prompt = _JUDGE_PROMPT.format(
            original=original,
            language=language,
            translation=translation,
            sfs=sfs or 0.0,
            ler=ler_char or 1.0,
        )
        try:
            result = llm_service.call(
                provider=model_info["provider_name"],
                model_name=model_info["name"],
                prompt_text=prompt,
                cost_per_input=0.0,
                cost_per_output=0.0,
            )
            if result.success:
                score = self._parse_score(result.response_text)
                return {
                    "model_id": model_info["id"],
                    "model_name": model_info["name"],
                    "score": score,
                    "error": None,
                }
            return {
                "model_id": model_info["id"],
                "model_name": model_info["name"],
                "score": None,
                "error": result.error,
            }
        except Exception as exc:
            return {
                "model_id": model_info.get("id"),
                "model_name": model_info.get("name"),
                "score": None,
                "error": str(exc),
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
            judges[name] = self.evaluate(
                original, translation, language, sfs, ler_char, llm_service, model_info
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
    def _parse_score(text: str):
        """Extract a float 0–1 from an LLM response, or None on failure."""
        if not text:
            return None
        m = re.search(r"\b(1\.0+|0?\.\d+|0|1)\b", text.strip())
        if m:
            return round(min(1.0, max(0.0, float(m.group()))), 6)
        return None
