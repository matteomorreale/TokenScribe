"""
TokenScribe — Prompt Model
Author: Matteo Morreale
"""

from .database import DatabaseManager


class PromptModel:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_by_study(self, study_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT p.*,
                          (SELECT COUNT(*) FROM approved_translations WHERE prompt_id=p.id) AS translation_count
                   FROM prompts p
                   WHERE p.study_id=?
                   ORDER BY p.created_at ASC""",
                (study_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_by_id(self, prompt_id: int):
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM prompts WHERE id=?", (prompt_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def create(self, study_id: int, base_text: str, category: str = "", notes: str = "") -> int:
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO prompts (study_id, base_text, category, notes) VALUES (?, ?, ?, ?)",
                (study_id, base_text, category, notes),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def update(self, prompt_id: int, base_text: str, category: str = "", notes: str = ""):
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE prompts SET base_text=?, category=?, notes=? WHERE id=?",
                (base_text, category, notes, prompt_id),
            )
            conn.commit()
        finally:
            conn.close()

    def delete(self, prompt_id: int):
        conn = self.db.get_connection()
        try:
            conn.execute("DELETE FROM prompts WHERE id=?", (prompt_id,))
            conn.commit()
        finally:
            conn.close()

    def save_pei_snapshot(self, prompt_id: int, pei: float, cv_char: float, cv_word: float, cv_token: float):
        conn = self.db.get_connection()
        try:
            conn.execute(
                """UPDATE prompts
                   SET pei_value=?, pei_cv_char=?, pei_cv_word=?, pei_cv_token=?,
                       pei_saved_at=strftime('%Y-%m-%dT%H:%M:%S','now')
                   WHERE id=?""",
                (pei, cv_char, cv_word, cv_token, prompt_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_translation_count(self, prompt_id: int) -> int:
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM translation_candidates WHERE prompt_id=?",
                (prompt_id,),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()
