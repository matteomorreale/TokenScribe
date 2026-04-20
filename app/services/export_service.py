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
    def to_csv(results: List[dict]) -> str:
        """Convert a list of token result dicts to CSV string."""
        if not results:
            return ""
        output = io.StringIO()
        fieldnames = [
            "run_id", "prompt_id", "base_text", "category",
            "language_name", "language_code", "writing_system",
            "model_name", "provider_name",
            "input_tokens", "output_tokens", "cost", "source", "created_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow(row)
        return output.getvalue()

    @staticmethod
    def to_json(results: List[dict], pei_results: List[dict] = None) -> str:
        """Convert results to a structured JSON dataset."""
        dataset = {
            "token_results": results,
            "pei_results": pei_results or [],
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
