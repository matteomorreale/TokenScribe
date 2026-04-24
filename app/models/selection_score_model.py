"""
TokenScribe — Selection Score Model
Author: Matteo Morreale
"""

import json
from .database import DatabaseManager


class SelectionScoreModel:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def upsert_scores(self, candidates: list):
        """Persist MAGI Phase 1 scores for a list of candidate dicts."""
        conn = self.db.get_connection()
        try:
            for c in candidates:
                conn.execute(
                    """INSERT INTO selection_score_results
                       (candidate_id, prompt_id, score_absolute, score_rank, score_rank_pct,
                        magi_required, lambda_used, nu_used)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(candidate_id) DO UPDATE SET
                         score_absolute=excluded.score_absolute,
                         score_rank=excluded.score_rank,
                         score_rank_pct=excluded.score_rank_pct,
                         magi_required=excluded.magi_required,
                         lambda_used=excluded.lambda_used,
                         nu_used=excluded.nu_used,
                         magi_score=NULL,
                         magi_disagreement=NULL,
                         magi_judges=NULL,
                         computed_at=strftime('%Y-%m-%dT%H:%M:%S','now')""",
                    (
                        c["id"],
                        c["prompt_id"],
                        c.get("score_absolute"),
                        c.get("score_rank"),
                        c.get("score_rank_pct"),
                        1 if c.get("magi_required") else 0,
                        c.get("lambda_used"),
                        c.get("nu_used"),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def update_magi_result(
        self,
        candidate_id: int,
        magi_score: float,
        magi_disagreement: bool,
        magi_judges: dict,
    ):
        """Persist Phase 2 judge results for a single candidate."""
        conn = self.db.get_connection()
        try:
            conn.execute(
                """UPDATE selection_score_results
                   SET magi_score=?, magi_disagreement=?, magi_judges=?,
                       computed_at=strftime('%Y-%m-%dT%H:%M:%S','now')
                   WHERE candidate_id=?""",
                (
                    magi_score,
                    1 if magi_disagreement else 0,
                    json.dumps(magi_judges, ensure_ascii=False),
                    candidate_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_by_prompt(self, prompt_id: int) -> list:
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT ssr.*, tc.language_id, tc.text, tc.status,
                          l.name AS language_name, l.code AS language_code,
                          ts.sfs, ts.dsf, ts.rtf, ts.ler_char, ts.ler_token
                   FROM selection_score_results ssr
                   JOIN translation_candidates tc ON tc.id = ssr.candidate_id
                   JOIN languages l ON l.id = tc.language_id
                   LEFT JOIN translation_scores ts ON ts.candidate_id = ssr.candidate_id
                   WHERE ssr.prompt_id = ?
                   ORDER BY ssr.score_rank""",
                (prompt_id,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if d.get("magi_judges"):
                    try:
                        d["magi_judges"] = json.loads(d["magi_judges"])
                    except (json.JSONDecodeError, TypeError):
                        d["magi_judges"] = None
                result.append(d)
            return result
        finally:
            conn.close()

    def get_readiness_by_prompts(self, prompt_ids: list) -> dict:
        """
        Returns {prompt_id: readiness_dict} where readiness_dict has:
          approved_count, scored_count, magi_count, magi_required_count,
          judge_count, status ("green"|"yellow"|"red")
        """
        if not prompt_ids:
            return {}
        conn = self.db.get_connection()
        try:
            placeholders = ",".join("?" * len(prompt_ids))
            rows = conn.execute(
                f"""SELECT
                       p.id AS prompt_id,
                       COUNT(DISTINCT at.candidate_id)                                          AS approved_count,
                       COUNT(DISTINCT CASE WHEN ts.sfs IS NOT NULL THEN at.candidate_id END)   AS scored_count,
                       COUNT(DISTINCT ssr.candidate_id)                                         AS magi_count,
                       COALESCE(SUM(CASE WHEN ssr.magi_required=1 THEN 1 ELSE 0 END), 0)       AS magi_required_count,
                       COALESCE(SUM(CASE WHEN ssr.magi_score IS NOT NULL THEN 1 ELSE 0 END), 0) AS judge_count
                    FROM prompts p
                    LEFT JOIN approved_translations at ON at.prompt_id = p.id
                    LEFT JOIN translation_scores ts ON ts.candidate_id = at.candidate_id
                    LEFT JOIN selection_score_results ssr ON ssr.prompt_id = p.id
                    WHERE p.id IN ({placeholders})
                    GROUP BY p.id""",
                prompt_ids,
            ).fetchall()
        finally:
            conn.close()

        result = {}
        for r in rows:
            d = dict(r)
            approved = d.get("approved_count") or 0
            scored = d.get("scored_count") or 0
            magi = d.get("magi_count") or 0
            required = d.get("magi_required_count") or 0
            if approved == 0:
                d["status"] = "red"
            elif scored < approved or magi == 0:
                d["status"] = "yellow"
            elif required > 0:
                d["status"] = "yellow"
            else:
                d["status"] = "green"
            result[d["prompt_id"]] = d
        # prompts with no rows at all default to red
        for pid in prompt_ids:
            result.setdefault(pid, {
                "prompt_id": pid, "approved_count": 0, "scored_count": 0,
                "magi_count": 0, "magi_required_count": 0, "judge_count": 0,
                "status": "red",
            })
        return result

    def get_by_prompt_multi(self, prompt_ids: list) -> dict:
        """Return {prompt_id: [scored_candidates]} for multiple prompts."""
        if not prompt_ids:
            return {}
        conn = self.db.get_connection()
        try:
            placeholders = ",".join("?" * len(prompt_ids))
            rows = conn.execute(
                f"""SELECT ssr.*, tc.language_id, tc.text, tc.status,
                           l.name AS language_name, l.code AS language_code,
                           ts.sfs, ts.dsf, ts.rtf, ts.ler_char, ts.ler_token
                    FROM selection_score_results ssr
                    JOIN translation_candidates tc ON tc.id = ssr.candidate_id
                    JOIN languages l ON l.id = tc.language_id
                    LEFT JOIN translation_scores ts ON ts.candidate_id = ssr.candidate_id
                    WHERE ssr.prompt_id IN ({placeholders})
                    ORDER BY ssr.prompt_id, ssr.score_rank""",
                prompt_ids,
            ).fetchall()
            result: dict = {}
            for r in rows:
                d = dict(r)
                if d.get("magi_judges"):
                    try:
                        d["magi_judges"] = json.loads(d["magi_judges"])
                    except (json.JSONDecodeError, TypeError):
                        d["magi_judges"] = None
                pid = d["prompt_id"]
                result.setdefault(pid, []).append(d)
            return result
        finally:
            conn.close()
