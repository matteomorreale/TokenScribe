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
            "run_id", "prompt_id", "base_text", "category", "prompt_notes",
            "language_name", "language_code", "writing_system", "script_group", "morphology_group",
            "model_name", "provider_name",
            "input_tokens",
            "visible_output_tokens",
            "reasoning_tokens",
            "tokenizer_drift",
            "api_reported_output_tokens",
            "ror",
            "is_reasoning_capable",
            "reasoning_observed",
            "reasoning_state",
            "reasoning_override_requested",
            "cost_visible_only",
            "cost_reasoning",
            "cost",
            "visible_output_text_length",
            "token_accounting_mode",
            "source",
            "created_at",
            "total_query_time_ms",
            "time_to_first_token_ms",
            "time_to_completion_ms",
            "time_to_stream_close_ms",
            "irrt_relative",
            "irrt_absolute",
            "pei",
            "pei_band",
            "script_group_count",
            "morphology_group_count",
            "pei_groups_script_group",
            "pei_groups_morphology_group",
            "ler_char",
            "ler_token",
            "magi_score_absolute",
            "magi_score_rank",
            "magi_score_rank_pct",
            "magi_required",
            "magi_score",
            "magi_disagreement",
            "tsf_strategy",
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
            enriched["magi_score_absolute"] = (ts_row or {}).get("magi_score_absolute")
            enriched["magi_score_rank"] = (ts_row or {}).get("magi_score_rank")
            enriched["magi_score_rank_pct"] = (ts_row or {}).get("magi_score_rank_pct")
            enriched["magi_required"] = (ts_row or {}).get("magi_required")
            enriched["magi_score"] = (ts_row or {}).get("magi_score")
            enriched["magi_disagreement"] = (ts_row or {}).get("magi_disagreement")
            writer.writerow(enriched)
        return output.getvalue()

    @staticmethod
    def to_json(
        results: List[dict],
        pei_results: List[dict] = None,
        pei_group_results: List[dict] = None,
        translation_scores: List[dict] = None,
        run_notes: str = None,
        cell_completeness: dict = None,
    ) -> str:
        """Convert results to a structured JSON dataset."""
        cc = cell_completeness or {}
        expected_reps = cc.get("expected_reps", 1)
        cells = cc.get("cells", {})
        incomplete = cc.get("incomplete", [])

        completeness_block = {
            "expected_reps": expected_reps,
            "all_complete": len(incomplete) == 0,
            "incomplete_cells": [
                {"prompt_id": p, "language_id": l, "model_id": m, "actual_reps": a}
                for p, l, m, a in incomplete
            ],
        }

        enriched_results = []
        for row in results:
            key = (row.get("prompt_id"), row.get("language_id"), row.get("model_id"))
            actual = cells.get(key, expected_reps)
            enriched = dict(row)
            enriched["cell_expected_reps"] = expected_reps
            enriched["cell_actual_reps"] = actual
            enriched_results.append(enriched)

        dataset = {
            "_notes": {
                "pei": (
                    "PEI (Prompt Equivalence Index) is model-invariant: it is computed from the approved "
                    "translation candidate texts (CV of char_length, word_count, token_count across languages). "
                    "Identical PEI values across runs using different LLMs is expected and correct — "
                    "PEI changes only when the set of approved translations changes."
                ),
                "cell_completeness": (
                    "cell_expected_reps / cell_actual_reps on each token_result row indicate "
                    "how many successful repetitions the cell (prompt × language × model) has. "
                    "Cells with actual_reps < expected_reps are also listed in cell_completeness.incomplete_cells."
                ),
            },
            "run_notes": run_notes or "",
            "cell_completeness": completeness_block,
            "token_results": enriched_results,
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
