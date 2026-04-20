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
    ) -> int:
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                """INSERT INTO token_results
                   (run_id, prompt_id, language_id, model_id,
                    input_tokens, output_tokens, cost, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, prompt_id, language_id, model_id,
                 input_tokens, output_tokens, cost, source),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_results_by_run(self, run_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT tr.*,
                          p.base_text, p.category,
                          l.name as language_name, l.code as language_code,
                          ws.name as writing_system,
                          m.name as model_name,
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
            return [dict(r) for r in rows]
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
    ) -> int:
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                """INSERT INTO pei_results
                   (run_id, prompt_id, cv_char_length, cv_word_count, cv_token_count, pei)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, prompt_id, cv_char, cv_word, cv_token, pei),
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
