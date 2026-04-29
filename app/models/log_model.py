"""
TokenScribe — Log Model
Author: Matteo Morreale

Read-only access to operation_logs for the log viewer UI.
All writes happen via LogService (async queue).
"""

import json
from app.models.database import DatabaseManager


class LogModel:
    def __init__(self, db: DatabaseManager):
        self._db = db

    def get_logs(
        self,
        operation_type: str | None = None,
        level: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        event: str | None = None,
        search: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        where, params = self._build_where(operation_type, level, provider, model, event, search)
        sql = f"""
            SELECT id, operation_type, event, level, provider, model,
                   message, context_ref, payload, duration_ms, created_at
            FROM operation_logs
            {where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """
        params += [limit, offset]
        conn = self._db.get_connection()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [self._enrich(dict(r)) for r in rows]
        finally:
            conn.close()

    def count_logs(
        self,
        operation_type: str | None = None,
        level: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        event: str | None = None,
        search: str | None = None,
    ) -> int:
        where, params = self._build_where(operation_type, level, provider, model, event, search)
        sql = f"SELECT COUNT(*) FROM operation_logs {where}"
        conn = self._db.get_connection()
        try:
            return conn.execute(sql, params).fetchone()[0]
        finally:
            conn.close()

    def get_distinct_values(self) -> dict:
        conn = self._db.get_connection()
        try:
            return {
                "operation_types": [r[0] for r in conn.execute(
                    "SELECT DISTINCT operation_type FROM operation_logs ORDER BY 1"
                ).fetchall()],
                "levels": [r[0] for r in conn.execute(
                    "SELECT DISTINCT level FROM operation_logs ORDER BY 1"
                ).fetchall()],
                "providers": [r[0] for r in conn.execute(
                    "SELECT DISTINCT provider FROM operation_logs WHERE provider IS NOT NULL ORDER BY 1"
                ).fetchall()],
                "models": [r[0] for r in conn.execute(
                    "SELECT DISTINCT model FROM operation_logs WHERE model IS NOT NULL ORDER BY 1"
                ).fetchall()],
            }
        finally:
            conn.close()

    def get_stats(self) -> dict:
        conn = self._db.get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) FROM operation_logs").fetchone()[0]
            by_level = {
                r[0]: r[1]
                for r in conn.execute(
                    "SELECT level, COUNT(*) FROM operation_logs GROUP BY level"
                ).fetchall()
            }
            by_type = {
                r[0]: r[1]
                for r in conn.execute(
                    "SELECT operation_type, COUNT(*) FROM operation_logs GROUP BY operation_type"
                ).fetchall()
            }
            avg_duration = conn.execute(
                "SELECT AVG(duration_ms) FROM operation_logs WHERE duration_ms IS NOT NULL"
            ).fetchone()[0]
            return {
                "total": total,
                "by_level": by_level,
                "by_type": by_type,
                "avg_duration_ms": round(avg_duration, 1) if avg_duration else None,
            }
        finally:
            conn.close()

    def delete_all(self) -> int:
        conn = self._db.get_connection()
        try:
            cur = conn.execute("DELETE FROM operation_logs")
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_where(operation_type, level, provider, model, event, search):
        clauses, params = [], []
        if operation_type:
            clauses.append("operation_type = ?")
            params.append(operation_type)
        if level:
            clauses.append("level = ?")
            params.append(level)
        if provider:
            clauses.append("provider = ?")
            params.append(provider)
        if model:
            clauses.append("model = ?")
            params.append(model)
        if event:
            clauses.append("event = ?")
            params.append(event)
        if search:
            clauses.append("(message LIKE ? OR payload LIKE ? OR context_ref LIKE ?)")
            like = f"%{search}%"
            params += [like, like, like]
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    @staticmethod
    def _enrich(row: dict) -> dict:
        for field in ("context_ref", "payload"):
            raw = row.get(field)
            if raw:
                try:
                    row[field] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    pass
        return row
