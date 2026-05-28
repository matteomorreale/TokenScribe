"""
TokenScribe — Experiment Model
Author: Matteo Morreale
"""

import logging
import statistics
from dataclasses import dataclass, field

from .database import DatabaseManager
from config import TokenScribeConfig

_log = logging.getLogger(__name__)

_REASONING_THRESHOLD = TokenScribeConfig.REASONING_THRESHOLD
_IRRT_ABS_MIN_OBS = 3  # minimum non-reasoning rows needed for OLS calibration


def _compute_irrt(results: list) -> None:
    """Mutates results in-place, adding irrt_relative and irrt_absolute to each row.

    irrt_relative = TTFT / median(TTFT for this model in this run).
                    1.0 = typical, >1 = slower than model's own baseline.
                    NULL when TTFT is unavailable or all TTFT for the model are NULL.

    irrt_absolute = TTFT / TTFT_expected, where TTFT_expected = α·input_tokens + β·visible_output_tokens
                    (+ intercept) from OLS calibrated on is_reasoning=0 rows in this run.
                    NULL when TTFT is unavailable or OLS cannot be fit (< _IRRT_ABS_MIN_OBS rows).
    """
    # --- iRRT-relativa: per-model median TTFT ---
    model_ttft: dict = {}
    for d in results:
        ttft = d.get("time_to_first_token_ms")
        if ttft is not None:
            model_ttft.setdefault(d["model_id"], []).append(ttft)

    model_median: dict = {
        mid: statistics.median(vals)
        for mid, vals in model_ttft.items()
        if vals
    }

    for d in results:
        ttft = d.get("time_to_first_token_ms")
        median = model_median.get(d["model_id"])
        if ttft is not None and median and median > 0:
            d["irrt_relative"] = round(ttft / median, 4)
        else:
            d["irrt_relative"] = None

    # --- iRRT-assoluta: OLS on non-reasoning rows ---
    calib = [
        d for d in results
        if not d.get("is_reasoning_capable")
        and d.get("time_to_first_token_ms") is not None
        and d.get("input_tokens") is not None
        and d.get("visible_output_tokens") is not None
    ]

    intercept = alpha = beta_out = None
    if len(calib) >= _IRRT_ABS_MIN_OBS:
        try:
            import numpy as np
            X = np.array(
                [[1.0, float(d["input_tokens"]), float(d["visible_output_tokens"])] for d in calib]
            )
            y = np.array([float(d["time_to_first_token_ms"]) for d in calib])
            coefs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
            intercept, alpha, beta_out = float(coefs[0]), float(coefs[1]), float(coefs[2])
        except Exception:
            pass

    for d in results:
        ttft = d.get("time_to_first_token_ms")
        inp = d.get("input_tokens")
        vot = d.get("visible_output_tokens")
        if alpha is not None and ttft is not None and inp is not None and vot is not None:
            ttft_expected = intercept + alpha * inp + beta_out * vot
            d["irrt_absolute"] = round(ttft / ttft_expected, 4) if ttft_expected > 0 else None
        else:
            d["irrt_absolute"] = None


class ExperimentModel:
    def __init__(self, db: DatabaseManager):
        self.db = db

    # --- Runs ---

    def get_all_runs(self):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT er.*, s.name as study_name,
                          COUNT(CASE WHEN tr.attempt_status = 'success' THEN 1 END) as result_count
                   FROM experiment_runs er
                   JOIN studies s ON s.id = er.study_id
                   LEFT JOIN token_results tr ON tr.run_id = er.id
                   GROUP BY er.id
                   ORDER BY er.timestamp DESC""",
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_runs_by_study(self, study_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT er.*,
                          COUNT(CASE WHEN tr.attempt_status = 'success' THEN 1 END) as result_count
                   FROM experiment_runs er
                   LEFT JOIN token_results tr ON tr.run_id = er.id
                   WHERE er.study_id=?
                   GROUP BY er.id
                   ORDER BY er.timestamp DESC""",
                (study_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_run_by_id(self, run_id: int):
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                """SELECT er.*, s.name as study_name
                   FROM experiment_runs er
                   JOIN studies s ON s.id = er.study_id
                   WHERE er.id=?""",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def create_run(self, study_id: int, notes: str = "") -> int:
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO experiment_runs (study_id, notes) VALUES (?, ?)",
                (study_id, notes),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def update_run_notes(self, run_id: int, notes: str) -> None:
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE experiment_runs SET notes=? WHERE id=?",
                (notes, run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def snapshot_translations(self, run_id: int, study_id: int):
        """Freeze the currently approved translations for this run.

        Must be called before any LLM calls so the snapshot reflects exactly
        which candidate was approved at run time, immune to future re-approvals.
        """
        conn = self.db.get_connection()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO run_translation_snapshot
                          (run_id, prompt_id, language_id, candidate_id)
                   SELECT ?, at.prompt_id, at.language_id, at.candidate_id
                   FROM approved_translations at
                   JOIN prompts p ON p.id = at.prompt_id
                   WHERE p.study_id = ?""",
                (run_id, study_id),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_token_result(
        self,
        run_id: int,
        prompt_id: int,
        language_id: int,
        model_id: int,
        repetition_index: int = 0,
    ) -> None:
        """Delete all attempt rows for this (run, prompt, language, model, repetition) key."""
        conn = self.db.get_connection()
        try:
            conn.execute(
                """DELETE FROM token_results
                   WHERE run_id=? AND prompt_id=? AND language_id=? AND model_id=?
                     AND repetition_index=?""",
                (run_id, prompt_id, language_id, model_id, repetition_index),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_run(self, run_id: int):
        conn = self.db.get_connection()
        try:
            conn.execute("DELETE FROM experiment_runs WHERE id=?", (run_id,))
            conn.commit()
        finally:
            conn.close()

    def delete_runs_bulk(self, run_ids: list):
        if not run_ids:
            return
        conn = self.db.get_connection()
        try:
            placeholders = ",".join("?" * len(run_ids))
            conn.execute(f"DELETE FROM experiment_runs WHERE id IN ({placeholders})", run_ids)
            conn.commit()
        finally:
            conn.close()

    # --- Token Results (immutable) ---

    def insert_token_result(
        self,
        run_id: int,
        prompt_id: int,
        language_id: int,
        model_id: int,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        source: str = "api_reported",
        response_text: str = None,
        visible_output_text_length: int = None,
        api_reported_output_tokens: int = None,
        token_accounting_mode: str = None,
        normalized_output_tokens: int = None,
        visible_output_tokens: int = None,
        response_valid: bool = None,
        repetition_index: int = 0,
        attempt_status: str = "success",
        reasoning_override_requested: str = None,
        total_query_time_ms: int = None,
        time_to_first_token_ms: int = None,
        time_to_completion_ms: int = None,
        time_to_stream_close_ms: int = None,
        # Run 19 new fields
        timing_anomaly: bool = False,
        stream_close_source: str = "native",
        had_retry_after: bool = False,
        retry_after_sleep_ms: int = 0,
        retry_count: int = 0,
        request_timestamp_utc: str = None,
        cell_sequential_index: int = None,
    ) -> int:
        """Insert a token result row. attempt_index is computed atomically via a
        MAX+1 subquery so that concurrent retries never collide on the unique key."""
        conn = self.db.get_connection()
        try:
            if visible_output_text_length is None:
                visible_output_text_length = len(response_text or "")
            if token_accounting_mode is None:
                token_accounting_mode = source
            if api_reported_output_tokens is None and source == "api_reported":
                api_reported_output_tokens = output_tokens
            vot = visible_output_tokens if visible_output_tokens is not None else normalized_output_tokens
            if response_valid is None:
                rv = 1 if (response_text or "").strip() and (vot is None or vot > 0) else 0
            else:
                rv = 1 if response_valid else 0

            # cell_sequential_index defaults to repetition_index (approximation;
            # actual execution order may differ with parallel workers).
            if cell_sequential_index is None:
                cell_sequential_index = repetition_index

            cur = conn.execute(
                """INSERT INTO token_results
                   (run_id, prompt_id, language_id, model_id,
                    input_tokens, output_tokens,
                    visible_output_text_length, api_reported_output_tokens,
                    cost, source, token_accounting_mode, response_text,
                    normalized_output_tokens, visible_output_tokens, response_valid,
                    repetition_index, attempt_index, attempt_status,
                    reasoning_override_requested,
                    total_query_time_ms, time_to_first_token_ms, time_to_completion_ms,
                    time_to_stream_close_ms,
                    timing_anomaly, stream_close_source,
                    had_retry_after, retry_after_sleep_ms, retry_count,
                    request_timestamp_utc, cell_sequential_index)
                   SELECT ?, ?, ?, ?,
                          ?, ?,
                          ?, ?,
                          ?, ?, ?, ?,
                          ?, ?, ?,
                          ?,
                          COALESCE((SELECT MAX(t2.attempt_index) + 1
                                    FROM token_results t2
                                    WHERE t2.run_id=? AND t2.prompt_id=? AND t2.language_id=?
                                      AND t2.model_id=? AND t2.repetition_index=?), 0),
                          ?,
                          ?,
                          ?, ?, ?,
                          ?,
                          ?, ?,
                          ?, ?, ?,
                          ?, ?""",
                (run_id, prompt_id, language_id, model_id,
                 input_tokens, output_tokens,
                 visible_output_text_length, api_reported_output_tokens,
                 cost, source, token_accounting_mode, response_text,
                 vot, vot, rv,
                 repetition_index,
                 run_id, prompt_id, language_id, model_id, repetition_index,
                 attempt_status,
                 reasoning_override_requested,
                 total_query_time_ms, time_to_first_token_ms, time_to_completion_ms,
                 time_to_stream_close_ms,
                 1 if timing_anomaly else 0, stream_close_source,
                 1 if had_retry_after else 0, retry_after_sleep_ms, retry_count,
                 request_timestamp_utc, cell_sequential_index),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def update_correctness_metrics(self, token_result_id: int, metrics: dict) -> None:
        """Stamp answer_correct / answer_in_target_language / language_leakage on a row."""
        conn = self.db.get_connection()
        try:
            conn.execute(
                """UPDATE token_results
                   SET answer_correct = ?,
                       answer_in_target_language = ?,
                       language_leakage = ?
                   WHERE id = ?""",
                (
                    1 if metrics["correct"] else 0,
                    1 if metrics["in_target_language"] else 0,
                    1 if metrics["language_leakage"] else 0,
                    token_result_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def update_olf_score(self, token_result_id: int, score: float) -> None:
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE token_results SET olf_score=? WHERE id=?",
                (score, token_result_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_nepr_score(self, token_result_id: int, score: float) -> None:
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE token_results SET nepr_score=? WHERE id=?",
                (score, token_result_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_tsf(self, token_result_id: int, strategy: str | None, judges_json: str) -> None:
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE token_results SET tsf_strategy=?, tsf_judges=? WHERE id=?",
                (strategy, judges_json, token_result_id),
            )
            conn.commit()
        finally:
            conn.close()

    # --- Calibration results ---

    def insert_calibration_result(
        self,
        run_id: int,
        calibration_prompt_id: int,
        language_id: int,
        model_id: int,
        input_tokens: int,
        output_tokens: int,
        visible_output_tokens: int = None,
        api_reported_output_tokens: int = None,
        reasoning_tokens: int = 0,
        time_to_first_token_ms: int = None,
        time_to_completion_ms: int = None,
        total_query_time_ms: int = None,
        time_to_stream_close_ms: int = None,
        stream_close_source: str = "native",
        timing_anomaly: bool = False,
        response_text: str = None,
        baseline_quality: str = "clean",
        attempt_status: str = "success",
        had_retry_after: bool = False,
        retry_after_sleep_ms: int = 0,
        retry_count: int = 0,
        request_timestamp_utc: str = None,
        cell_sequential_index: int = None,
        repetition_index: int = 0,
        baseline_source: str = None,
    ) -> int:
        """Insert a calibration result row. attempt_index computed atomically."""
        conn = self.db.get_connection()
        try:
            if cell_sequential_index is None:
                cell_sequential_index = repetition_index
            if api_reported_output_tokens is None:
                api_reported_output_tokens = output_tokens
            if visible_output_tokens is None:
                visible_output_tokens = max(0, output_tokens - reasoning_tokens)

            cur = conn.execute(
                """INSERT INTO calibration_results
                   (run_id, calibration_prompt_id, language_id, model_id,
                    repetition_index, attempt_index, attempt_status,
                    input_tokens, output_tokens,
                    visible_output_tokens, api_reported_output_tokens, reasoning_tokens,
                    time_to_first_token_ms, time_to_completion_ms,
                    total_query_time_ms, time_to_stream_close_ms,
                    stream_close_source, timing_anomaly, response_text,
                    baseline_quality,
                    had_retry_after, retry_after_sleep_ms, retry_count,
                    request_timestamp_utc, cell_sequential_index,
                    baseline_source)
                   SELECT ?, ?, ?, ?,
                          ?,
                          COALESCE((SELECT MAX(c2.attempt_index) + 1
                                    FROM calibration_results c2
                                    WHERE c2.run_id=? AND c2.calibration_prompt_id=?
                                      AND c2.language_id=? AND c2.model_id=?
                                      AND c2.repetition_index=?), 0),
                          ?,
                          ?, ?,
                          ?, ?, ?,
                          ?, ?,
                          ?, ?,
                          ?, ?, ?,
                          ?,
                          ?, ?, ?,
                          ?, ?,
                          ?""",
                (run_id, calibration_prompt_id, language_id, model_id,
                 repetition_index,
                 run_id, calibration_prompt_id, language_id, model_id, repetition_index,
                 attempt_status,
                 input_tokens, output_tokens,
                 visible_output_tokens, api_reported_output_tokens, reasoning_tokens,
                 time_to_first_token_ms, time_to_completion_ms,
                 total_query_time_ms, time_to_stream_close_ms,
                 stream_close_source, 1 if timing_anomaly else 0, response_text,
                 baseline_quality,
                 1 if had_retry_after else 0, retry_after_sleep_ms, retry_count,
                 request_timestamp_utc, cell_sequential_index,
                 baseline_source),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_calibration_results_by_run(self, run_id: int) -> list[dict]:
        """Return all calibration results for a run, enriched with model/language/prompt metadata."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT
                       cr.*,
                       cp.slug      AS cal_prompt_slug,
                       cp.text_en   AS cal_prompt_text_en,
                       cp.target_tokens_min,
                       cp.target_tokens_max,
                       l.name       AS language_name,
                       l.code       AS language_code,
                       l.script_group,
                       l.morphology_group,
                       ws.name      AS writing_system,
                       m.name       AS model_name,
                       m.is_reasoning AS is_reasoning_capable,
                       p.name       AS provider_name
                   FROM calibration_results cr
                   JOIN calibration_prompts cp ON cp.id = cr.calibration_prompt_id
                   JOIN languages l            ON l.id  = cr.language_id
                   JOIN writing_systems ws     ON ws.id = l.writing_system_id
                   JOIN models m               ON m.id  = cr.model_id
                   JOIN providers p            ON p.id  = m.provider_id
                   WHERE cr.run_id = ? AND cr.attempt_status = 'success'
                   ORDER BY cp.id, l.name, m.name, cr.repetition_index""",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_calibration_translation(
        self, calibration_prompt_id: int, language_id: int
    ) -> str | None:
        """Return stored calibration translation text, or None if not yet translated."""
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                """SELECT text FROM calibration_translations
                   WHERE calibration_prompt_id=? AND language_id=?""",
                (calibration_prompt_id, language_id),
            ).fetchone()
            return row["text"] if row else None
        finally:
            conn.close()

    def get_all_calibration_prompts(self) -> list[dict]:
        """Return all calibration prompts ordered by id."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM calibration_prompts ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # --- Prompt access (needed by queue workers) ---

    def get_prompt_base_text(self, prompt_id: int) -> str | None:
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT base_text FROM prompts WHERE id=?", (prompt_id,)
            ).fetchone()
            return row["base_text"] if row else None
        finally:
            conn.close()

    def get_prompt_analysis_type(self, prompt_id: int) -> str:
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT analysis_type FROM prompts WHERE id=?", (prompt_id,)
            ).fetchone()
            return (row["analysis_type"] if row and row["analysis_type"] else "standard")
        finally:
            conn.close()

    # --- MAGI answer variants ---

    def get_magi_answer_variants(self, prompt_id: int, language_id: int | None) -> list[str]:
        """Return variant strings for this prompt scoped to language_id (or cross-language if None)."""
        conn = self.db.get_connection()
        try:
            if language_id is None:
                rows = conn.execute(
                    "SELECT variant FROM magi_answer_variants WHERE prompt_id=? AND language_id IS NULL",
                    (prompt_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT variant FROM magi_answer_variants WHERE prompt_id=? AND language_id=?",
                    (prompt_id, language_id),
                ).fetchall()
            return [r["variant"] for r in rows]
        finally:
            conn.close()

    def insert_magi_answer_variant(
        self,
        prompt_id: int,
        language_id: int | None,
        variant: str,
        judge_name: str = "",
        judge_model: str = "",
    ) -> bool:
        """Insert a MAGI-discovered variant. Returns True if newly inserted, False if duplicate."""
        conn = self.db.get_connection()
        try:
            existing = conn.execute(
                """SELECT id FROM magi_answer_variants
                   WHERE prompt_id=?
                     AND (language_id IS ? OR language_id=?)
                     AND LOWER(variant)=LOWER(?)""",
                (prompt_id, language_id, language_id, variant),
            ).fetchone()
            if existing:
                return False
            conn.execute(
                """INSERT INTO magi_answer_variants
                   (prompt_id, language_id, variant, judge_name, judge_model)
                   VALUES (?, ?, ?, ?, ?)""",
                (prompt_id, language_id, variant, judge_name, judge_model),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def update_answer_correct_by_row(self, token_result_id: int) -> None:
        """Retroactively mark a specific token_result row as answer_correct=1."""
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE token_results SET answer_correct=1, language_leakage=0 WHERE id=?",
                (token_result_id,),
            )
            conn.commit()
        finally:
            conn.close()

    # --- Named entity expectations ---

    def get_ne_expectations(self, prompt_id: int, language_id: int) -> list[dict]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT entity_name, expected_form, allow_original
                   FROM ne_expectations
                   WHERE prompt_id=? AND language_id=?""",
                (prompt_id, language_id),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_ne_labeling_status(self, prompt_id: int, language_id: int) -> str | None:
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT status FROM ne_labeling_status WHERE prompt_id=? AND language_id=?",
                (prompt_id, language_id),
            ).fetchone()
            return row["status"] if row else None
        finally:
            conn.close()

    def set_ne_labeling_status(self, prompt_id: int, language_id: int, status: str) -> None:
        import datetime
        conn = self.db.get_connection()
        try:
            conn.execute(
                """INSERT INTO ne_labeling_status (prompt_id, language_id, status, computed_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(prompt_id, language_id) DO UPDATE SET status=excluded.status, computed_at=excluded.computed_at""",
                (prompt_id, language_id, status,
                 datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")),
            )
            conn.commit()
        finally:
            conn.close()

    def insert_ne_expectations(
        self,
        prompt_id: int,
        language_id: int,
        expectations: list[dict],
        judge_name: str = "",
        judge_model: str = "",
    ) -> None:
        if not expectations:
            return
        conn = self.db.get_connection()
        try:
            conn.executemany(
                """INSERT OR REPLACE INTO ne_expectations
                   (prompt_id, language_id, entity_name, expected_form, allow_original, judge_name, judge_model)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (prompt_id, language_id,
                     e["entity"], e["expected_form"], 1 if e.get("allow_original") else 0,
                     judge_name, judge_model)
                    for e in expectations
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def get_results_by_run(self, run_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """WITH latest_success AS (
                       SELECT run_id, prompt_id, language_id, model_id, repetition_index,
                              MAX(attempt_index) AS max_attempt
                       FROM token_results
                       WHERE run_id = ? AND attempt_status = 'success'
                       GROUP BY run_id, prompt_id, language_id, model_id, repetition_index
                   )
                   SELECT
                          tr.id,
                          tr.run_id,
                          tr.prompt_id,
                          tr.language_id,
                          tr.model_id,
                          tr.repetition_index,
                          tr.attempt_index,
                          tr.attempt_status,
                          tr.input_tokens,
                          tr.output_tokens,
                          COALESCE(tr.visible_output_text_length, LENGTH(COALESCE(tr.response_text, ''))) AS visible_output_text_length,
                          COALESCE(
                              tr.api_reported_output_tokens,
                              CASE WHEN tr.source = 'api_reported' THEN tr.output_tokens ELSE NULL END
                          ) AS api_reported_output_tokens,
                          tr.cost,
                          tr.source,
                          COALESCE(tr.token_accounting_mode, tr.source) AS token_accounting_mode,
                          tr.response_text,
                          COALESCE(tr.visible_output_tokens, tr.normalized_output_tokens) AS visible_output_tokens,
                          COALESCE(tr.response_valid, CASE WHEN COALESCE(tr.response_text, '') = '' THEN 0 ELSE 1 END) AS response_valid,
                          tr.reasoning_override_requested,
                          tr.created_at,
                          tr.total_query_time_ms,
                          tr.time_to_first_token_ms,
                          tr.time_to_completion_ms,
                          tr.time_to_stream_close_ms,
                          p.base_text, p.category, p.notes as prompt_notes,
                          l.name as language_name, l.code as language_code,
                          l.script_group as script_group,
                          l.morphology_group as morphology_group,
                          ws.name as writing_system,
                          m.name as model_name,
                          m.cost_per_input_token,
                          m.cost_per_output_token,
                          m.is_reasoning as is_reasoning_capable,
                          pr.name as provider_name
                   FROM token_results tr
                   JOIN latest_success ls
                        ON ls.run_id = tr.run_id
                       AND ls.prompt_id = tr.prompt_id
                       AND ls.language_id = tr.language_id
                       AND ls.model_id = tr.model_id
                       AND ls.repetition_index = tr.repetition_index
                       AND ls.max_attempt = tr.attempt_index
                   JOIN prompts p ON p.id = tr.prompt_id
                   JOIN languages l ON l.id = tr.language_id
                   JOIN writing_systems ws ON ws.id = l.writing_system_id
                   JOIN models m ON m.id = tr.model_id
                   JOIN providers pr ON pr.id = m.provider_id
                   ORDER BY p.id, l.name, m.name""",
                (run_id,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                vot = d.get("visible_output_tokens") or 0
                arot = d.get("api_reported_output_tokens") or 0
                cpi = d.get("cost_per_input_token") or 0.0
                cpo = d.get("cost_per_output_token") or 0.0
                d["visible_output_tokens"] = vot
                d["reasoning_tokens"] = max(0, arot - vot)
                d["tokenizer_drift"] = max(0, vot - arot)
                d["cost_visible_only"] = round(vot * cpo / 1_000_000, 8)
                d["cost_reasoning"] = round(d["reasoning_tokens"] * cpo / 1_000_000, 8)
                d["cost"] = round(((d.get("input_tokens") or 0) * cpi + arot * cpo) / 1_000_000, 8)
                d["ror"] = round(d["reasoning_tokens"] / vot, 3) if vot > 0 else 0.0
                is_capable = bool(d.get("is_reasoning_capable"))
                reasoning_observed = d["reasoning_tokens"] > _REASONING_THRESHOLD
                d["reasoning_observed"] = reasoning_observed
                if is_capable and reasoning_observed:
                    d["reasoning_state"] = "active"
                elif is_capable and not reasoning_observed:
                    d["reasoning_state"] = "capable_but_inactive"
                elif not is_capable and reasoning_observed:
                    d["reasoning_state"] = "anomaly"
                    _log.warning("reasoning anomaly: model=%s provider=%s run_id=%s hidden_tokens=%d",
                                 d.get("model_name"), d.get("provider_name"), run_id, d["reasoning_tokens"])
                else:
                    d["reasoning_state"] = "non_reasoning"
                results.append(d)

            # --- iRRT second pass (requires all rows per model to be collected first) ---
            _compute_irrt(results)

            return results
        finally:
            conn.close()

    # --- PEI Results ---

    def insert_pei_result(
        self,
        run_id: int,
        prompt_id: int,
        cv_char: float,
        cv_word: float,
        cv_token: float,
        pei: float,
        script_group_count: int = None,
        morphology_group_count: int = None,
        pei_band: str = None,
    ) -> int:
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                """INSERT INTO pei_results
                   (run_id, prompt_id, cv_char_length, cv_word_count, cv_token_count, pei,
                    script_group_count, morphology_group_count, pei_band)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    prompt_id,
                    cv_char,
                    cv_word,
                    cv_token,
                    pei,
                    script_group_count,
                    morphology_group_count,
                    pei_band,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_latest_pei_for_prompt(self, prompt_id: int):
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                """SELECT pr.pei FROM pei_results pr
                   JOIN experiment_runs er ON er.id = pr.run_id
                   WHERE pr.prompt_id = ?
                   ORDER BY er.timestamp DESC
                   LIMIT 1""",
                (prompt_id,),
            ).fetchone()
            return float(row["pei"]) if row else None
        finally:
            conn.close()

    def get_cell_completeness(self, run_id: int) -> dict:
        """Return per-cell repetition completeness for a run.

        Returns:
            {
              "expected_reps": int,
              "cells": {(prompt_id, language_id, model_id): actual_reps},
              "incomplete": [(prompt_id, language_id, model_id, actual_reps), ...],
            }
        expected_reps = MAX(repetition_index) + 1 across all successful rows in the run.
        """
        conn = self.db.get_connection()
        try:
            exp_row = conn.execute(
                """SELECT COALESCE(MAX(repetition_index) + 1, 1) AS expected_reps
                   FROM token_results
                   WHERE run_id = ? AND attempt_status = 'success'""",
                (run_id,),
            ).fetchone()
            expected = exp_row["expected_reps"] if exp_row else 1

            rows = conn.execute(
                """SELECT prompt_id, language_id, model_id,
                          COUNT(DISTINCT repetition_index) AS actual_reps
                   FROM token_results
                   WHERE run_id = ? AND attempt_status = 'success'
                   GROUP BY prompt_id, language_id, model_id""",
                (run_id,),
            ).fetchall()

            cells = {
                (r["prompt_id"], r["language_id"], r["model_id"]): r["actual_reps"]
                for r in rows
            }
            incomplete = [
                (p, l, m, a) for (p, l, m), a in cells.items() if a < expected
            ]
            return {"expected_reps": expected, "cells": cells, "incomplete": incomplete}
        finally:
            conn.close()

    def get_pei_by_run(self, run_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT pr.*, p.base_text, p.category
                   FROM pei_results pr
                   JOIN prompts p ON p.id = pr.prompt_id
                   WHERE pr.run_id=?
                   ORDER BY p.id""",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def insert_pei_group_result(
        self,
        run_id: int,
        prompt_id: int,
        group_type: str,
        group_value: str,
        language_count: int,
        cv_char: float,
        cv_word: float,
        cv_token: float,
        pei: float,
        pei_delta_vs_global: float,
        baseline_pei: float,
        pei_delta_vs_group: float,
        pei_band: str,
    ) -> int:
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                """INSERT INTO pei_group_results
                   (run_id, prompt_id, group_type, group_value, language_count,
                    cv_char_length, cv_word_count, cv_token_count, pei,
                    pei_delta_vs_global, baseline_pei, pei_delta_vs_group, pei_band)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    prompt_id,
                    group_type,
                    group_value,
                    language_count,
                    cv_char,
                    cv_word,
                    cv_token,
                    pei,
                    pei_delta_vs_global,
                    baseline_pei,
                    pei_delta_vs_group,
                    pei_band,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_pei_groups_by_run(self, run_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT pgr.*, p.base_text, p.category
                   FROM pei_group_results pgr
                   JOIN prompts p ON p.id = pgr.prompt_id
                   WHERE pgr.run_id=?
                   ORDER BY p.id, pgr.group_type, pgr.group_value""",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # --- Models ---

    def get_all_models(self):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT m.*, p.name as provider_name
                   FROM models m
                   JOIN providers p ON p.id = m.provider_id
                   WHERE m.is_active=1
                   ORDER BY p.name, m.name""",
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_model_by_id(self, model_id: int):
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT m.*, p.name as provider_name FROM models m JOIN providers p ON p.id=m.provider_id WHERE m.id=?",
                (model_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_run_status(self, run_id: int, status: str) -> None:
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE experiment_runs SET status = ? WHERE id = ?",
                (status, run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def insert_pei_group_partial(
        self,
        run_id: int,
        prompt_id: int,
        group_type: str,
        group_value: str,
        language_count: int,
        cv_char: float,
        cv_word: float,
        cv_token: float,
        pei: float,
        pei_delta_vs_global: float,
        pei_band: str,
    ) -> int:
        """Inserisce un record pei_group_results senza baseline (calcolata da finalize_pei_groups)."""
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                """INSERT INTO pei_group_results
                   (run_id, prompt_id, group_type, group_value, language_count,
                    cv_char_length, cv_word_count, cv_token_count, pei,
                    pei_delta_vs_global, baseline_pei, pei_delta_vs_group, pei_band)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)""",
                (
                    run_id, prompt_id, group_type, group_value, language_count,
                    cv_char, cv_word, cv_token, pei,
                    pei_delta_vs_global, pei_band,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def update_pei_group_baselines(self, run_id: int) -> None:
        """Calcola e aggiorna baseline_pei e pei_delta_vs_group per tutti i gruppi della run."""
        conn = self.db.get_connection()
        try:
            conn.execute(
                """UPDATE pei_group_results
                   SET baseline_pei = (
                       SELECT AVG(g2.pei) FROM pei_group_results g2
                       WHERE g2.run_id = pei_group_results.run_id
                         AND g2.group_type = pei_group_results.group_type
                         AND g2.group_value = pei_group_results.group_value
                   )
                   WHERE run_id = ?""",
                (run_id,),
            )
            conn.execute(
                """UPDATE pei_group_results
                   SET pei_delta_vs_group = ROUND(pei - baseline_pei, 6)
                   WHERE run_id = ? AND baseline_pei IS NOT NULL""",
                (run_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def get_run_snapshot_inputs(self, run_id: int, prompt_id: int) -> list[dict]:
        """
        Restituisce i testi (base_text inglese + traduzioni approvate snapshot) per un prompt
        in una run, con i metadati di lingua necessari per il calcolo PEI.
        """
        conn = self.db.get_connection()
        try:
            # Inglese (base_text del prompt)
            prompt_row = conn.execute(
                "SELECT base_text FROM prompts WHERE id = ?", (prompt_id,)
            ).fetchone()
            en_row = conn.execute(
                "SELECT id, name, code, script_group, morphology_group FROM languages WHERE code = 'en'"
            ).fetchone()

            inputs = []
            if prompt_row and en_row:
                inputs.append({
                    "language_id":       int(en_row["id"]),
                    "language_name":     en_row["name"],
                    "language_code":     en_row["code"],
                    "script_group":      en_row["script_group"] or "alphabetic",
                    "morphology_group":  en_row["morphology_group"] or "",
                    "text":              prompt_row["base_text"],
                })

            # Traduzioni dalla snapshot
            rows = conn.execute(
                """SELECT tc.text,
                          l.id as language_id, l.name as language_name,
                          l.code as language_code,
                          l.script_group, l.morphology_group
                   FROM run_translation_snapshot rts
                   JOIN translation_candidates tc ON tc.id = rts.candidate_id
                   JOIN languages l ON l.id = rts.language_id
                   WHERE rts.run_id = ? AND rts.prompt_id = ? AND l.code != 'en'""",
                (run_id, prompt_id),
            ).fetchall()
            for r in rows:
                inputs.append({
                    "language_id":      int(r["language_id"]),
                    "language_name":    r["language_name"],
                    "language_code":    r["language_code"],
                    "script_group":     r["script_group"] or "alphabetic",
                    "morphology_group": r["morphology_group"] or "",
                    "text":             r["text"],
                })
            return inputs
        finally:
            conn.close()

    # --- Run History (archivio per redo/replace) ---

    def archive_model_results(
        self,
        run_id: int,
        model_id: int,
        model_name: str,
        reason: str,
        replaced_by_model_id: int = None,
        replaced_by_model_name: str = None,
    ) -> int:
        """Salva in run_history i token_results correnti per un modello. Ritorna l'id del record."""
        import json as _json
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT tr.*, m.name as model_name, p.base_text,
                          l.name as language_name, l.code as language_code
                   FROM token_results tr
                   JOIN models m ON m.id = tr.model_id
                   JOIN prompts p ON p.id = tr.prompt_id
                   JOIN languages l ON l.id = tr.language_id
                   WHERE tr.run_id=? AND tr.model_id=? AND tr.attempt_status='success'""",
                (run_id, model_id),
            ).fetchall()
            results = [dict(r) for r in rows]
            cur = conn.execute(
                """INSERT INTO run_history
                   (run_id, model_id, model_name, reason,
                    replaced_by_model_id, replaced_by_model_name, results_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, model_id, model_name, reason,
                    replaced_by_model_id, replaced_by_model_name,
                    _json.dumps(results, default=str),
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def delete_model_results(self, run_id: int, model_id: int) -> int:
        """Elimina tutti i token_results di un modello in una run."""
        conn = self.db.get_connection()
        try:
            conn.execute(
                "DELETE FROM token_results WHERE run_id=? AND model_id=?",
                (run_id, model_id),
            )
            conn.commit()
            return conn.execute("SELECT changes()").fetchone()[0]
        finally:
            conn.close()

    def get_run_model_ids(self, run_id: int) -> set[int]:
        """Restituisce i model_id presenti nella run.

        Fonti:
        - token_results: modelli con almeno un risultato (completati o in retry)
        - run_queue: modelli con item attivi (pending/running/error/timeout) ma ancora
          senza risultati (es. appena aggiunti). Esclude done e cancelled: i done sono
          già in token_results; se non ci sono, il modello è stato sostituito/cancellato.
        """
        import json as _json
        conn = self.db.get_connection()
        try:
            ids: set[int] = set()
            for row in conn.execute(
                "SELECT DISTINCT model_id FROM token_results WHERE run_id=?", (run_id,)
            ).fetchall():
                ids.add(int(row["model_id"]))
            for row in conn.execute(
                """SELECT payload FROM run_queue
                   WHERE run_id=? AND operation_type='llm_call'
                   AND status NOT IN ('done', 'cancelled')""",
                (run_id,),
            ).fetchall():
                p = _json.loads(row["payload"])
                if mid := p.get("model_id"):
                    ids.add(int(mid))
            return ids
        finally:
            conn.close()

    def build_llm_payloads_from_snapshot(
        self, run_id: int, model_id: int, repetitions: int
    ) -> list[dict]:
        """Genera payload llm_call per un nuovo modello dal run_translation_snapshot congelato."""
        conn = self.db.get_connection()
        try:
            run_row = conn.execute(
                "SELECT study_id FROM experiment_runs WHERE id=?", (run_id,)
            ).fetchone()
            if not run_row:
                return []
            study_id = int(run_row["study_id"])

            model_row = conn.execute(
                """SELECT m.*, p.name AS provider_name
                   FROM models m JOIN providers p ON p.id = m.provider_id
                   WHERE m.id = ?""",
                (model_id,),
            ).fetchone()
            if not model_row:
                return []
            model = dict(model_row)

            english_row = conn.execute(
                "SELECT id, name, code, script_group, morphology_group FROM languages WHERE code='en'"
            ).fetchone()
            english_id = int(english_row["id"]) if english_row else None

            snap_rows = conn.execute(
                """SELECT rts.prompt_id, rts.language_id,
                          l.name AS language_name, l.code AS language_code,
                          l.script_group, l.morphology_group,
                          tc.text
                   FROM run_translation_snapshot rts
                   JOIN languages l ON l.id = rts.language_id
                   JOIN translation_candidates tc ON tc.id = rts.candidate_id
                   WHERE rts.run_id = ?""",
                (run_id,),
            ).fetchall()

            prompt_ids = list({r["prompt_id"] for r in snap_rows})

            def _payload(prompt_id, lang_id, lang_name, lang_code, script_g, morph_g, text, rep):
                return {
                    "run_id":           run_id,
                    "study_id":         study_id,
                    "prompt_id":        prompt_id,
                    "language_id":      lang_id,
                    "language_name":    lang_name,
                    "language_code":    lang_code,
                    "script_group":     script_g or "alphabetic",
                    "morphology_group": morph_g or "",
                    "model_id":         model_id,
                    "provider":         model["provider_name"],
                    "model_name":       model["name"],
                    "cost_per_input":   float(model.get("cost_per_input_token") or 0.0),
                    "cost_per_output":  float(model.get("cost_per_output_token") or 0.0),
                    "is_reasoning":     bool(model.get("is_reasoning", 0)),
                    "text":             text,
                    "repetition_index": rep,
                }

            payloads = []
            for prompt_id in prompt_ids:
                prompt_row = conn.execute(
                    "SELECT base_text FROM prompts WHERE id=?", (prompt_id,)
                ).fetchone()
                if not prompt_row:
                    continue

                if english_row:
                    for rep in range(repetitions):
                        payloads.append(_payload(
                            prompt_id, english_id,
                            english_row["name"], "en",
                            english_row["script_group"], english_row["morphology_group"],
                            prompt_row["base_text"], rep,
                        ))

                for snap in snap_rows:
                    if snap["prompt_id"] != prompt_id or snap["language_code"] == "en":
                        continue
                    if not snap["text"]:
                        continue
                    for rep in range(repetitions):
                        payloads.append(_payload(
                            prompt_id, snap["language_id"],
                            snap["language_name"], snap["language_code"],
                            snap["script_group"], snap["morphology_group"],
                            snap["text"], rep,
                        ))

            return payloads
        finally:
            conn.close()

    def get_run_history(self, run_id: int) -> list[dict]:
        """Ritorna le voci di storico archiviate per una run."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT id, run_id, model_id, model_name, archived_at, reason,
                          replaced_by_model_id, replaced_by_model_name
                   FROM run_history WHERE run_id=? ORDER BY archived_at DESC""",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def reconstruct_llm_payloads(self, run_id: int, model_id: int) -> list[dict]:
        """Ricostruisce i payload llm_call da token_results + snapshot (run senza queue items)."""
        conn = self.db.get_connection()
        try:
            model_row = conn.execute(
                """SELECT m.*, p.name as provider_name
                   FROM models m JOIN providers p ON p.id=m.provider_id WHERE m.id=?""",
                (model_id,),
            ).fetchone()
            if not model_row:
                return []
            model = dict(model_row)

            run_row = conn.execute(
                "SELECT study_id FROM experiment_runs WHERE id=?", (run_id,)
            ).fetchone()
            study_id = int(run_row["study_id"]) if run_row else None

            result_rows = conn.execute(
                """SELECT DISTINCT prompt_id, language_id FROM token_results
                   WHERE run_id=? AND model_id=? AND attempt_status='success'""",
                (run_id, model_id),
            ).fetchall()

            payloads = []
            for r in result_rows:
                prompt_id   = r["prompt_id"]
                language_id = r["language_id"]

                lang_row = conn.execute(
                    "SELECT name, code, script_group, morphology_group FROM languages WHERE id=?",
                    (language_id,),
                ).fetchone()
                if not lang_row:
                    continue
                lang = dict(lang_row)

                if lang["code"] == "en":
                    p_row = conn.execute(
                        "SELECT base_text FROM prompts WHERE id=?", (prompt_id,)
                    ).fetchone()
                    text = p_row["base_text"] if p_row else None
                else:
                    snap_row = conn.execute(
                        """SELECT tc.text FROM run_translation_snapshot rts
                           JOIN translation_candidates tc ON tc.id = rts.candidate_id
                           WHERE rts.run_id=? AND rts.prompt_id=? AND rts.language_id=?""",
                        (run_id, prompt_id, language_id),
                    ).fetchone()
                    text = snap_row["text"] if snap_row else None

                if not text:
                    continue

                payloads.append({
                    "run_id":        run_id,
                    "study_id":      study_id,
                    "prompt_id":     prompt_id,
                    "language_id":   language_id,
                    "language_name": lang["name"],
                    "language_code": lang["code"],
                    "model_id":      model_id,
                    "provider":      model["provider_name"],
                    "model_name":    model["name"],
                    "cost_per_input":  float(model.get("cost_per_input_token") or 0.0),
                    "cost_per_output": float(model.get("cost_per_output_token") or 0.0),
                    "is_reasoning":    bool(model.get("is_reasoning", 0)),
                    "text":          text,
                })
            return payloads
        finally:
            conn.close()

    def get_translation_scores_by_run(self, run_id: int) -> list:
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT DISTINCT snap.prompt_id, snap.language_id,
                          l.name  AS language_name,
                          l.code  AS language_code,
                          p.base_text,
                          ts.dsf, ts.rtf, ts.sfs, ts.ler_char, ts.ler_token,
                          ts.computed_at,
                          ssr.score_absolute AS magi_score_absolute,
                          ssr.score_rank     AS magi_score_rank,
                          ssr.score_rank_pct AS magi_score_rank_pct,
                          ssr.magi_required,
                          ssr.magi_score,
                          ssr.magi_disagreement,
                          ssr.magi_judges
                   FROM token_results tr
                   JOIN run_translation_snapshot snap
                        ON snap.run_id = tr.run_id
                       AND snap.prompt_id = tr.prompt_id
                       AND snap.language_id = tr.language_id
                   JOIN translation_scores ts ON ts.candidate_id = snap.candidate_id
                   JOIN languages l ON l.id = snap.language_id
                   JOIN prompts p ON p.id = snap.prompt_id
                   LEFT JOIN selection_score_results ssr ON ssr.candidate_id = snap.candidate_id
                   WHERE tr.run_id = ? AND tr.attempt_status = 'success'
                   ORDER BY snap.prompt_id, l.name""",
                (run_id,),
            ).fetchall()
            import json as _json
            result = []
            for r in rows:
                d = dict(r)
                if d.get("magi_judges"):
                    try:
                        d["magi_judges"] = _json.loads(d["magi_judges"])
                    except (ValueError, TypeError):
                        d["magi_judges"] = None
                result.append(d)
            return result
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Retroactive visible-token recomputation
    # ------------------------------------------------------------------

    def recompute_visible_tokens(self, run_id: int) -> dict:
        """Reapply the inflated-API-count heuristic to already-stored results.

        For each successful token_result in the run, checks whether
        api_reported_output_tokens / max(1, len(response_text)) exceeds the
        plausibility ceiling (2.0 for alphabetic scripts, 1.5 for logographic).
        When it does, visible_output_tokens is overwritten with a local tiktoken
        cl100k_base count.

        Returns a summary dict with keys:
          checked   – number of rows examined
          updated   – number of rows rewritten
          skipped   – rows where local tiktoken returned 0 (tiktoken not installed
                      or empty text) — kept at old value
          unchanged – rows that passed the heuristic
        """
        try:
            import tiktoken as _tiktoken
            _enc = _tiktoken.get_encoding("cl100k_base")

            def _local_count(text: str) -> int:
                return len(_enc.encode(text)) if text else 0
        except Exception:
            return {"checked": 0, "updated": 0, "skipped": 0, "unchanged": 0,
                    "error": "tiktoken not available"}

        _LOGO = {"zh", "ja", "ko", "yue", "wuu", "hak", "nan"}

        def _is_logo(code: str) -> bool:
            c = (code or "").lower()
            return c[:2] in _LOGO or c[:3].rstrip("-") in _LOGO

        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT tr.id,
                          COALESCE(tr.api_reported_output_tokens,
                                   CASE WHEN tr.source='api_reported' THEN tr.output_tokens END)
                              AS arot,
                          tr.response_text,
                          l.code AS language_code
                   FROM token_results tr
                   JOIN languages l ON l.id = tr.language_id
                   WHERE tr.run_id = ? AND tr.attempt_status = 'success'""",
                (run_id,),
            ).fetchall()

            checked = len(rows)
            updated = skipped = unchanged = 0
            updates: list[tuple[int, int]] = []

            for r in rows:
                arot = r["arot"] or 0
                text = r["response_text"] or ""
                char_len = max(1, len(text))

                if arot <= 0 or not text.strip():
                    unchanged += 1
                    continue

                threshold = 1.5 if _is_logo(r["language_code"]) else 2.0
                if arot / char_len <= threshold:
                    unchanged += 1
                    continue

                local_toks = _local_count(text)
                if local_toks <= 0:
                    skipped += 1
                    continue

                updates.append((local_toks, r["id"]))
                updated += 1

            if updates:
                conn.executemany(
                    "UPDATE token_results SET visible_output_tokens=? WHERE id=?",
                    updates,
                )
                conn.commit()
                _log.info(
                    "recompute_visible_tokens run=%d: updated=%d skipped=%d unchanged=%d",
                    run_id, updated, skipped, unchanged,
                )

            return {
                "checked": checked,
                "updated": updated,
                "skipped": skipped,
                "unchanged": unchanged,
            }
        finally:
            conn.close()
