"""
TokenScribe — Experiment Model
Author: Matteo Morreale
"""

from .database import DatabaseManager


class ExperimentModel:
    def __init__(self, db: DatabaseManager):
        self.db = db

    # --- Runs ---

    def get_all_runs(self):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT er.*, s.name as study_name,
                          COUNT(tr.id) as result_count
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
                """SELECT er.*, COUNT(tr.id) as result_count
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
    ) -> int:
        conn = self.db.get_connection()
        try:
            if visible_output_text_length is None:
                visible_output_text_length = len(response_text or "")
            if token_accounting_mode is None:
                token_accounting_mode = source
            if api_reported_output_tokens is None and source == "api_reported":
                api_reported_output_tokens = output_tokens
            # visible_output_tokens supersedes normalized_output_tokens
            vot = visible_output_tokens if visible_output_tokens is not None else normalized_output_tokens

            cur = conn.execute(
                """INSERT INTO token_results
                   (run_id, prompt_id, language_id, model_id,
                    input_tokens, output_tokens,
                    visible_output_text_length, api_reported_output_tokens,
                    cost, source, token_accounting_mode, response_text,
                    normalized_output_tokens, visible_output_tokens)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, prompt_id, language_id, model_id,
                 input_tokens, output_tokens,
                 visible_output_text_length, api_reported_output_tokens,
                 cost, source, token_accounting_mode, response_text,
                 vot, vot),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_results_by_run(self, run_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT
                          tr.id,
                          tr.run_id,
                          tr.prompt_id,
                          tr.language_id,
                          tr.model_id,
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
                          tr.created_at,
                          p.base_text, p.category,
                          l.name as language_name, l.code as language_code,
                          l.script_group as script_group,
                          l.morphology_group as morphology_group,
                          ws.name as writing_system,
                          m.name as model_name,
                          m.cost_per_output_token,
                          pr.name as provider_name
                   FROM token_results tr
                   JOIN prompts p ON p.id = tr.prompt_id
                   JOIN languages l ON l.id = tr.language_id
                   JOIN writing_systems ws ON ws.id = l.writing_system_id
                   JOIN models m ON m.id = tr.model_id
                   JOIN providers pr ON pr.id = m.provider_id
                   WHERE tr.run_id=?
                   ORDER BY p.id, l.name, m.name""",
                (run_id,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                vot = d.get("visible_output_tokens") or 0
                arot = d.get("api_reported_output_tokens") or 0
                cpo = d.get("cost_per_output_token") or 0.0
                d["reasoning_tokens"] = max(0, arot - vot)
                d["cost_visible_only"] = round(vot * cpo, 8)
                d["ror"] = round(d["reasoning_tokens"] / vot, 3) if vot > 0 else 0.0
                results.append(d)
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

    def get_translation_scores_by_run(self, run_id: int) -> list:
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT DISTINCT at.prompt_id, at.language_id,
                          l.name  AS language_name,
                          l.code  AS language_code,
                          p.base_text,
                          ts.dsf, ts.rtf, ts.sfs, ts.ler_char, ts.ler_token,
                          ts.computed_at
                   FROM token_results tr
                   JOIN approved_translations at
                        ON at.prompt_id = tr.prompt_id
                       AND at.language_id = tr.language_id
                   JOIN translation_scores ts ON ts.candidate_id = at.candidate_id
                   JOIN languages l ON l.id = at.language_id
                   JOIN prompts p ON p.id = at.prompt_id
                   WHERE tr.run_id = ?
                   ORDER BY at.prompt_id, l.name""",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
