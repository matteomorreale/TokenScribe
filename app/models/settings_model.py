"""
TokenScribe — Settings Model
Author: Matteo Morreale
"""

from .database import DatabaseManager


class SettingsModel:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def get(self, key: str, default=None):
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
            return row["value"] if row else default
        finally:
            conn.close()

    def set(self, key: str, value: str):
        conn = self.db.get_connection()
        try:
            conn.execute(
                """INSERT INTO settings (key, value)
                   VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                     value=excluded.value,
                     updated_at=strftime('%Y-%m-%dT%H:%M:%S','now')""",
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()

    def set_many(self, data: dict):
        conn = self.db.get_connection()
        try:
            for key, value in data.items():
                conn.execute(
                    """INSERT INTO settings (key, value)
                       VALUES (?, ?)
                       ON CONFLICT(key) DO UPDATE SET
                         value=excluded.value,
                         updated_at=strftime('%Y-%m-%dT%H:%M:%S','now')""",
                    (key, value),
                )
            conn.commit()
        finally:
            conn.close()

    def get_all(self) -> dict:
        conn = self.db.get_connection()
        try:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            return {r["key"]: r["value"] for r in rows}
        finally:
            conn.close()

    # --- Provider model management ---

    def get_all_providers(self):
        conn = self.db.get_connection()
        try:
            rows = conn.execute("SELECT * FROM providers ORDER BY name").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_models_by_provider(self, provider_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM models WHERE provider_id=? ORDER BY name",
                (provider_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def update_model_costs(
        self,
        model_id: int,
        cost_per_input: float,
        cost_per_output: float,
        is_active: int,
    ):
        conn = self.db.get_connection()
        try:
            conn.execute(
                """UPDATE models SET
                     cost_per_input_token=?,
                     cost_per_output_token=?,
                     is_active=?
                   WHERE id=?""",
                (cost_per_input, cost_per_output, is_active, model_id),
            )
            conn.commit()
        finally:
            conn.close()

    def add_model(self, provider_id: int, name: str, context_window: int = 0) -> int:
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO models (provider_id, name, context_window) VALUES (?, ?, ?)",
                (provider_id, name, context_window),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # --- Language management ---

    def get_all_languages(self):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT l.*, ws.name as writing_system
                   FROM languages l
                   JOIN writing_systems ws ON ws.id = l.writing_system_id
                   ORDER BY l.name"""
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_all_writing_systems(self):
        conn = self.db.get_connection()
        try:
            rows = conn.execute("SELECT * FROM writing_systems ORDER BY name").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_language(self, name: str, code: str, writing_system_id: int) -> int:
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO languages (name, code, writing_system_id) VALUES (?, ?, ?)",
                (name, code, writing_system_id),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
