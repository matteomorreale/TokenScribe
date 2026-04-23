"""
TokenScribe — Translation Model
Author: Matteo Morreale
"""

from .database import DatabaseManager


class TranslationModel:
    def __init__(self, db: DatabaseManager):
        self.db = db

    # --- Candidates ---

    def get_candidates_by_prompt(self, prompt_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT tc.*, l.name as language_name, l.code as language_code,
                          ws.name as writing_system,
                          l.script_group as script_group,
                          l.morphology_group as morphology_group,
                          ts.dsf, ts.rtf, ts.sfs, ts.ler_char, ts.ler_token
                   FROM translation_candidates tc
                   JOIN languages l ON l.id = tc.language_id
                   JOIN writing_systems ws ON ws.id = l.writing_system_id
                   LEFT JOIN translation_scores ts ON ts.candidate_id = tc.id
                   WHERE tc.prompt_id = ?
                   ORDER BY l.name, tc.version""",
                (prompt_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_candidate_by_id(self, candidate_id: int):
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                """SELECT tc.*, l.name as language_name, l.code as language_code,
                          ws.name as writing_system,
                          l.script_group as script_group,
                          l.morphology_group as morphology_group
                   FROM translation_candidates tc
                   JOIN languages l ON l.id = tc.language_id
                   JOIN writing_systems ws ON ws.id = l.writing_system_id
                   WHERE tc.id = ?""",
                (candidate_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def create_candidate(self, prompt_id: int, language_id: int, text: str) -> int:
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT MAX(version) as mv FROM translation_candidates WHERE prompt_id=? AND language_id=?",
                (prompt_id, language_id),
            ).fetchone()
            version = (row["mv"] or 0) + 1
            cur = conn.execute(
                "INSERT INTO translation_candidates (prompt_id, language_id, text, version) VALUES (?, ?, ?, ?)",
                (prompt_id, language_id, text, version),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def update_status(self, candidate_id: int, status: str):
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE translation_candidates SET status=? WHERE id=?",
                (status, candidate_id),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_candidate(self, candidate_id: int):
        conn = self.db.get_connection()
        try:
            conn.execute("DELETE FROM translation_candidates WHERE id=?", (candidate_id,))
            conn.commit()
        finally:
            conn.close()

    # --- Scores ---

    def upsert_score(self, candidate_id: int, dsf: float, rtf: float, sfs: float,
                     ler_char: float = None, ler_token: float = None):
        conn = self.db.get_connection()
        try:
            conn.execute(
                """INSERT INTO translation_scores (candidate_id, dsf, rtf, sfs, ler_char, ler_token)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(candidate_id) DO UPDATE SET
                     dsf=excluded.dsf, rtf=excluded.rtf, sfs=excluded.sfs,
                     ler_char=excluded.ler_char, ler_token=excluded.ler_token,
                     computed_at=strftime('%Y-%m-%dT%H:%M:%S','now')""",
                (candidate_id, dsf, rtf, sfs, ler_char, ler_token),
            )
            conn.commit()
        finally:
            conn.close()

    def get_score(self, candidate_id: int):
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM translation_scores WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # --- Approved Translations ---

    def approve(self, prompt_id: int, language_id: int, candidate_id: int):
        conn = self.db.get_connection()
        try:
            # Mark candidate as approved
            conn.execute(
                "UPDATE translation_candidates SET status='approved' WHERE id=?",
                (candidate_id,),
            )
            # Reject other candidates for same prompt+language
            conn.execute(
                """UPDATE translation_candidates SET status='rejected'
                   WHERE prompt_id=? AND language_id=? AND id!=?""",
                (prompt_id, language_id, candidate_id),
            )
            # Upsert approved_translations
            conn.execute(
                """INSERT INTO approved_translations (prompt_id, language_id, candidate_id)
                   VALUES (?, ?, ?)
                   ON CONFLICT(prompt_id, language_id) DO UPDATE SET
                     candidate_id=excluded.candidate_id,
                     approved_at=strftime('%Y-%m-%dT%H:%M:%S','now')""",
                (prompt_id, language_id, candidate_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_approved_by_prompt(self, prompt_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT at.*, l.name as language_name, l.code as language_code,
                          ws.name as writing_system,
                          l.script_group as script_group,
                          l.morphology_group as morphology_group,
                          tc.text, ts.sfs, ts.ler_char, ts.ler_token
                   FROM approved_translations at
                   JOIN languages l ON l.id = at.language_id
                   JOIN writing_systems ws ON ws.id = l.writing_system_id
                   JOIN translation_candidates tc ON tc.id = at.candidate_id
                   LEFT JOIN translation_scores ts ON ts.candidate_id = at.candidate_id
                   WHERE at.prompt_id=?
                   ORDER BY l.name""",
                (prompt_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_all_languages(self):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT l.*, ws.name as writing_system
                   FROM languages l
                   JOIN writing_systems ws ON ws.id = l.writing_system_id
                   ORDER BY l.name""",
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
