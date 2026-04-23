"""
TokenScribe — Export Service
Author: Matteo Morreale

Handles dataset export to CSV and JSON formats.
"""

import csv
import json
import io
from typing import List


class ExportService:
    """Generates exportable datasets from TokenScribe experiment results."""

    @staticmethod
    def to_csv(
        results: List[dict],
        pei_results: List[dict] = None,
        pei_group_results: List[dict] = None,
        translation_scores: List[dict] = None,
    ) -> str:
        """Convert a list of token result dicts to CSV string (optionally enriched with PEI and LER metrics)."""
        if not results:
            return ""

        pei_by_prompt = {int(p["prompt_id"]): p for p in (pei_results or []) if p.get("prompt_id") is not None}

        group_by_prompt = {}
        for g in pei_group_results or []:
            pid = g.get("prompt_id")
            if pid is None:
                continue
            pid = int(pid)
            gt = (g.get("group_type") or "").strip()
            gv = (g.get("group_value") or "").strip()
            if not gt or not gv:
                continue
            group_by_prompt.setdefault(pid, {}).setdefault(gt, {})[gv] = {
                "pei": g.get("pei"),
                "pei_delta_vs_global": g.get("pei_delta_vs_global"),
                "baseline_pei": g.get("baseline_pei"),
                "pei_delta_vs_group": g.get("pei_delta_vs_group"),
                "language_count": g.get("language_count"),
                "pei_band": g.get("pei_band"),
            }

        scores_by_prompt_lang = {}
        for s in (translation_scores or []):
            pid = s.get("prompt_id")
            lid = s.get("language_id")
            if pid is not None and lid is not None:
                scores_by_prompt_lang[(int(pid), int(lid))] = s

        output = io.StringIO()
        fieldnames = [
            "run_id", "prompt_id", "base_text", "category",
            "language_name", "language_code", "writing_system", "script_group", "morphology_group",
            "model_name", "provider_name",
            "input_tokens",
            "visible_output_tokens",
            "reasoning_tokens",
            "api_reported_output_tokens",
            "ror",
            "cost_visible_only",
            "cost",
            "visible_output_text_length",
            "token_accounting_mode",
            "source",
            "created_at",
            "pei",
            "pei_band",
            "script_group_count",
            "morphology_group_count",
            "pei_groups_script_group",
            "pei_groups_morphology_group",
            "ler_char",
            "ler_token",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            pid = row.get("prompt_id")
            lid = row.get("language_id")
            pei_row = pei_by_prompt.get(int(pid)) if pid is not None else None
            groups = group_by_prompt.get(int(pid)) if pid is not None else {}
            ts_row = scores_by_prompt_lang.get((int(pid), int(lid))) if pid is not None and lid is not None else {}
            enriched = dict(row)
            enriched["pei"] = (pei_row or {}).get("pei")
            enriched["pei_band"] = (pei_row or {}).get("pei_band")
            enriched["script_group_count"] = (pei_row or {}).get("script_group_count")
            enriched["morphology_group_count"] = (pei_row or {}).get("morphology_group_count")
            enriched["pei_groups_script_group"] = json.dumps(
                groups.get("script_group", {}), ensure_ascii=False
            )
            enriched["pei_groups_morphology_group"] = json.dumps(
                groups.get("morphology_group", {}), ensure_ascii=False
            )
            enriched["ler_char"] = (ts_row or {}).get("ler_char")
            enriched["ler_token"] = (ts_row or {}).get("ler_token")
            writer.writerow(enriched)
        return output.getvalue()

    @staticmethod
    def to_json(
        results: List[dict],
        pei_results: List[dict] = None,
        pei_group_results: List[dict] = None,
        translation_scores: List[dict] = None,
    ) -> str:
        """Convert results to a structured JSON dataset."""
        dataset = {
            "token_results": results,
            "pei_results": pei_results or [],
            "pei_group_results": pei_group_results or [],
            "translation_scores": translation_scores or [],
        }
        return json.dumps(dataset, indent=2, ensure_ascii=False)

    @staticmethod
    def study_summary(
        study: dict,
        prompts: List[dict],
        runs: List[dict],
        token_results: List[dict],
    ) -> dict:
        """Build a full study summary dict for JSON export."""
        return {
            "study": study,
            "prompts": prompts,
            "experiment_runs": runs,
            "token_results": token_results,
        }
