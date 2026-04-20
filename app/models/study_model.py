"""
TokenScribe — Study Model
Author: Matteo Morreale
"""

import json
from .database import DatabaseManager


class StudyModel:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_all(self):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM studies ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_by_id(self, study_id: int):
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM studies WHERE id = ?", (study_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def create(self, name: str, description: str = "", config: dict = None) -> int:
        config_json = json.dumps(config or {})
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO studies (name, description, config) VALUES (?, ?, ?)",
                (name, description, config_json),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def update(self, study_id: int, name: str, description: str, config: dict = None):
        config_json = json.dumps(config or {})
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE studies SET name=?, description=?, config=? WHERE id=?",
                (name, description, config_json, study_id),
            )
            conn.commit()
        finally:
            conn.close()

    def delete(self, study_id: int):
        conn = self.db.get_connection()
        try:
            conn.execute("DELETE FROM studies WHERE id=?", (study_id,))
            conn.commit()
        finally:
            conn.close()

    def get_prompt_count(self, study_id: int) -> int:
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM prompts WHERE study_id=?", (study_id,)
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    def get_run_count(self, study_id: int) -> int:
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM experiment_runs WHERE study_id=?", (study_id,)
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()
