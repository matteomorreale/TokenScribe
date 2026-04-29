"""
TokenScribe — QueueModel
Author: Matteo Morreale

CRUD per la tabella run_queue. Gestisce lo stato degli item della coda
di esecuzione asincrona delle RUN. Thread-safe via SQLite WAL + transazioni atomiche.
"""

import json
from datetime import datetime, timezone

from .database import DatabaseManager

# Stati validi per un item di coda
ITEM_PENDING   = "pending"
ITEM_RUNNING   = "running"
ITEM_DONE      = "done"
ITEM_ERROR     = "error"
ITEM_TIMEOUT   = "timeout"

# Stati validi per una RUN
RUN_QUEUED    = "queued"
RUN_RUNNING   = "running"
RUN_COMPLETED = "completed"
RUN_PARTIAL   = "partial"    # completata ma con errori
RUN_FAILED    = "failed"     # errore critico


class QueueModel:
    def __init__(self, db: DatabaseManager):
        self.db = db

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    def enqueue(
        self,
        run_id: int,
        operation_type: str,
        item_key: str,
        payload: dict,
        priority: int = 0,
    ) -> bool:
        """Inserisce un item in coda. Idempotente: ignora duplicati su (run_id, operation_type, item_key)."""
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO run_queue
                   (run_id, operation_type, item_key, payload, status, priority)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, operation_type, item_key, json.dumps(payload, default=str), ITEM_PENDING, priority),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Worker: claim + complete
    # ------------------------------------------------------------------

    def dequeue_next(self) -> dict | None:
        """
        Preleva il prossimo item pending in ordine (priority ASC, id ASC)
        e lo marca atomicamente come running. Restituisce None se la coda è vuota.
        """
        conn = self.db.get_connection()
        try:
            now = _now_iso()
            # Legge il prossimo pending senza bloccarlo (SQLite serializza tramite WAL)
            row = conn.execute(
                """SELECT * FROM run_queue
                   WHERE status = ?
                   ORDER BY priority ASC, id ASC
                   LIMIT 1""",
                (ITEM_PENDING,),
            ).fetchone()
            if not row:
                return None
            item_id = row["id"]
            conn.execute(
                "UPDATE run_queue SET status = ?, started_at = ? WHERE id = ? AND status = ?",
                (ITEM_RUNNING, now, item_id, ITEM_PENDING),
            )
            conn.commit()
            # Rilegge per avere certezza che sia stato il nostro UPDATE ad avere effetto
            updated = conn.execute("SELECT * FROM run_queue WHERE id = ?", (item_id,)).fetchone()
            if not updated or updated["status"] != ITEM_RUNNING:
                return None  # qualcun altro lo ha preso (race window improbabile con SQLite WAL)
            d = dict(updated)
            d["payload"] = json.loads(d["payload"] or "{}")
            return d
        finally:
            conn.close()

    def mark_done(self, item_id: int) -> None:
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE run_queue SET status = ?, completed_at = ? WHERE id = ?",
                (ITEM_DONE, _now_iso(), item_id),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_error(self, item_id: int, message: str) -> None:
        conn = self.db.get_connection()
        try:
            conn.execute(
                """UPDATE run_queue
                   SET status = ?, completed_at = ?, error_message = ?,
                       retry_count = retry_count + 1
                   WHERE id = ?""",
                (ITEM_ERROR, _now_iso(), str(message)[:2000], item_id),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_timeout(self, item_id: int) -> None:
        conn = self.db.get_connection()
        try:
            conn.execute(
                """UPDATE run_queue
                   SET status = ?, completed_at = ?, error_message = ?,
                       retry_count = retry_count + 1
                   WHERE id = ?""",
                (ITEM_TIMEOUT, _now_iso(), "timeout", item_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_run_queue(self, run_id: int) -> list[dict]:
        """Ritorna tutti gli item di una run in ordine di coda."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM run_queue WHERE run_id = ? ORDER BY priority ASC, id ASC",
                (run_id,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["payload"] = json.loads(d["payload"] or "{}")
                except (ValueError, TypeError):
                    d["payload"] = {}
                result.append(d)
            return result
        finally:
            conn.close()

    def get_run_progress(self, run_id: int) -> dict:
        """Ritorna conteggi per status e il totale degli item di una run."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM run_queue WHERE run_id = ? GROUP BY status",
                (run_id,),
            ).fetchall()
            counts = {r["status"]: r["cnt"] for r in rows}
            total = sum(counts.values())
            done  = counts.get(ITEM_DONE, 0)
            error = counts.get(ITEM_ERROR, 0) + counts.get(ITEM_TIMEOUT, 0)
            pending  = counts.get(ITEM_PENDING, 0)
            running  = counts.get(ITEM_RUNNING, 0)
            return {
                "total":   total,
                "done":    done,
                "error":   error,
                "pending": pending,
                "running": running,
                "pct":     round(done / total * 100, 1) if total else 0,
            }
        finally:
            conn.close()

    def get_error_items(self, run_id: int) -> list[dict]:
        """Ritorna gli item in errore di una run con il payload parsato."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT * FROM run_queue
                   WHERE run_id = ? AND status IN (?, ?)
                   ORDER BY priority ASC, id ASC""",
                (run_id, ITEM_ERROR, ITEM_TIMEOUT),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["payload"] = json.loads(d["payload"] or "{}")
                except (ValueError, TypeError):
                    d["payload"] = {}
                result.append(d)
            return result
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Resume / Retry
    # ------------------------------------------------------------------

    def reset_items_for_retry(self, run_id: int, model_ids: list[int] | None = None) -> int:
        """
        Resetta a 'pending' gli item in errore/timeout di una run.
        Se model_ids è specificato, filtra solo gli item llm_call con quel model_id nel payload.
        Ritorna il numero di item resettati.
        """
        conn = self.db.get_connection()
        try:
            error_rows = conn.execute(
                """SELECT id, operation_type, payload FROM run_queue
                   WHERE run_id = ? AND status IN (?, ?)""",
                (run_id, ITEM_ERROR, ITEM_TIMEOUT),
            ).fetchall()

            ids_to_reset = []
            for r in error_rows:
                if model_ids is None:
                    ids_to_reset.append(r["id"])
                else:
                    # Filtra per model_id nel payload degli llm_call
                    try:
                        p = json.loads(r["payload"] or "{}")
                    except (ValueError, TypeError):
                        p = {}
                    mid = p.get("model_id")
                    if mid is not None and int(mid) in model_ids:
                        ids_to_reset.append(r["id"])
                    elif r["operation_type"] != "llm_call":
                        # Item non-LLM (es. finalize_pei_groups): resetta sempre
                        ids_to_reset.append(r["id"])

            if not ids_to_reset:
                return 0

            placeholders = ",".join("?" * len(ids_to_reset))
            conn.execute(
                f"""UPDATE run_queue
                    SET status = ?, started_at = NULL, completed_at = NULL, error_message = NULL
                    WHERE id IN ({placeholders})""",
                [ITEM_PENDING] + ids_to_reset,
            )
            conn.commit()
            return len(ids_to_reset)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Recover stale 'running' items after crash/restart
    # ------------------------------------------------------------------

    def recover_stale_running(self, run_id: int | None = None) -> int:
        """
        All'avvio dell'app resetta a 'pending' tutti gli item rimasti in stato
        'running' da una sessione precedente (crash o riavvio).
        """
        conn = self.db.get_connection()
        try:
            if run_id is not None:
                conn.execute(
                    "UPDATE run_queue SET status = ?, started_at = NULL WHERE status = ? AND run_id = ?",
                    (ITEM_PENDING, ITEM_RUNNING, run_id),
                )
            else:
                conn.execute(
                    "UPDATE run_queue SET status = ?, started_at = NULL WHERE status = ?",
                    (ITEM_PENDING, ITEM_RUNNING),
                )
            conn.commit()
            return conn.execute("SELECT changes()").fetchone()[0]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Run status
    # ------------------------------------------------------------------

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

    def recompute_run_status(self, run_id: int) -> str:
        """
        Calcola e salva lo status della run in base agli item in coda.
        Ritorna il nuovo status.
        """
        progress = self.get_run_progress(run_id)
        if progress["total"] == 0:
            status = RUN_COMPLETED
        elif progress["pending"] > 0 or progress["running"] > 0:
            status = RUN_RUNNING
        elif progress["error"] > 0 and progress["done"] == 0:
            status = RUN_FAILED
        elif progress["error"] > 0:
            status = RUN_PARTIAL
        else:
            status = RUN_COMPLETED
        self.update_run_status(run_id, status)
        return status


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
