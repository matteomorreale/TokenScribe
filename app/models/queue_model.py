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
ITEM_CANCELLED = "cancelled"

# Stati validi per una RUN
RUN_QUEUED    = "queued"
RUN_RUNNING   = "running"
RUN_COMPLETED = "completed"
RUN_PARTIAL   = "partial"    # completata ma con errori
RUN_FAILED    = "failed"     # errore critico
RUN_STOPPED   = "stopped"    # fermata manualmente dall'utente


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

    def requeue_at_end(self, item_id: int, max_retries: int = 10) -> bool:
        """
        Rimette un item in coda alla fine (nuovo id auto-increment) anziché marcarlo in errore.
        Usato per i rate-limit 429: l'item viene rielaborato dopo tutti i pending correnti.
        Ritorna True se rimesso in coda, False se ha superato max_retries → marcato come errore.
        """
        conn = self.db.get_connection()
        try:
            row = conn.execute("SELECT * FROM run_queue WHERE id = ?", (item_id,)).fetchone()
            if not row:
                return False
            retry_count = (row["retry_count"] or 0) + 1
            if retry_count > max_retries:
                conn.execute(
                    """UPDATE run_queue
                       SET status = ?, completed_at = ?, error_message = ?,
                           retry_count = ?
                       WHERE id = ?""",
                    (ITEM_ERROR, _now_iso(), "rate_limit: max retries exceeded", retry_count, item_id),
                )
                conn.commit()
                return False
            # Cancella e re-inserisce con nuovo id auto-increment → finisce in fondo alla coda
            conn.execute("DELETE FROM run_queue WHERE id = ?", (item_id,))
            conn.execute(
                """INSERT INTO run_queue
                   (run_id, operation_type, item_key, payload, status, priority, retry_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (row["run_id"], row["operation_type"], row["item_key"],
                 row["payload"], ITEM_PENDING, row["priority"], retry_count),
            )
            conn.commit()
            return True
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
            total     = sum(counts.values())
            done      = counts.get(ITEM_DONE, 0)
            error     = counts.get(ITEM_ERROR, 0) + counts.get(ITEM_TIMEOUT, 0)
            pending   = counts.get(ITEM_PENDING, 0)
            running   = counts.get(ITEM_RUNNING, 0)
            cancelled = counts.get(ITEM_CANCELLED, 0)
            active    = total - cancelled
            return {
                "total":     total,
                "done":      done,
                "error":     error,
                "pending":   pending,
                "running":   running,
                "cancelled": cancelled,
                "pct":       round(done / active * 100, 1) if active else 0,
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

    def cancel_pending_items(self, run_id: int) -> int:
        """Marca come 'cancelled' tutti gli item pending di una run (stop manuale)."""
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                "UPDATE run_queue SET status = ? WHERE run_id = ? AND status = ?",
                (ITEM_CANCELLED, run_id, ITEM_PENDING),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def restart_stopped_run(self, run_id: int) -> int:
        """Reset cancelled/error/timeout/running items a 'pending' per riavviare una run fermata."""
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                """UPDATE run_queue
                   SET status = ?, started_at = NULL, completed_at = NULL, error_message = NULL
                   WHERE run_id = ? AND status IN (?, ?, ?, ?)""",
                (ITEM_PENDING, run_id, ITEM_CANCELLED, ITEM_ERROR, ITEM_TIMEOUT, ITEM_RUNNING),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Redo / Replace model
    # ------------------------------------------------------------------

    def get_model_llm_payloads(self, run_id: int, model_id: int) -> list[dict]:
        """Ritorna i payload degli llm_call per un modello dalla coda (qualunque status)."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT payload FROM run_queue WHERE run_id=? AND operation_type='llm_call'",
                (run_id,),
            ).fetchall()
            result = []
            for r in rows:
                try:
                    p = json.loads(r["payload"] or "{}")
                except (ValueError, TypeError):
                    p = {}
                if int(p.get("model_id", -1)) == model_id:
                    result.append(p)
            return result
        finally:
            conn.close()

    def redo_model_items(self, run_id: int, model_id: int, payloads: list[dict]) -> int:
        """
        Resetta a 'pending' gli item llm_call esistenti per il modello.
        Se non ne esistono (run senza coda), li crea dai payloads forniti.
        Ritorna il numero di item pronti.
        """
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT id, payload FROM run_queue WHERE run_id=? AND operation_type='llm_call'",
                (run_id,),
            ).fetchall()
            ids_to_reset = []
            for r in rows:
                try:
                    p = json.loads(r["payload"] or "{}")
                except (ValueError, TypeError):
                    p = {}
                if int(p.get("model_id", -1)) == model_id:
                    ids_to_reset.append(r["id"])

            if ids_to_reset:
                placeholders = ",".join("?" * len(ids_to_reset))
                conn.execute(
                    f"""UPDATE run_queue
                        SET status='pending', started_at=NULL, completed_at=NULL, error_message=NULL
                        WHERE id IN ({placeholders})""",
                    ids_to_reset,
                )
                conn.commit()
                return len(ids_to_reset)

            # Nessun item esistente: crea da payloads (run precedenti al queue system)
            count = 0
            for p in payloads:
                item_key = f"llm:p{p['prompt_id']}:l{p['language_id']}:m{model_id}"
                cur = conn.execute(
                    """INSERT OR IGNORE INTO run_queue
                       (run_id, operation_type, item_key, payload, status, priority)
                       VALUES (?, 'llm_call', ?, ?, 'pending', 2)""",
                    (run_id, item_key, json.dumps(p, default=str)),
                )
                count += cur.rowcount
            conn.commit()
            return count
        finally:
            conn.close()

    def replace_model_items(
        self,
        run_id: int,
        old_model_id: int,
        new_model_id: int,
        new_model_info: dict,
        payloads: list[dict],
    ) -> int:
        """
        Elimina gli item llm_call del vecchio modello e crea quelli per il nuovo.
        Ritorna il numero di item creati.
        """
        conn = self.db.get_connection()
        try:
            # Rimuove item del vecchio modello
            rows = conn.execute(
                "SELECT id, payload FROM run_queue WHERE run_id=? AND operation_type='llm_call'",
                (run_id,),
            ).fetchall()
            old_ids = []
            for r in rows:
                try:
                    p = json.loads(r["payload"] or "{}")
                except (ValueError, TypeError):
                    p = {}
                if int(p.get("model_id", -1)) == old_model_id:
                    old_ids.append(r["id"])
            if old_ids:
                placeholders = ",".join("?" * len(old_ids))
                conn.execute(f"DELETE FROM run_queue WHERE id IN ({placeholders})", old_ids)

            # Crea item per il nuovo modello
            count = 0
            for old_p in payloads:
                new_p = dict(old_p)
                new_p["model_id"]      = new_model_id
                new_p["model_name"]    = new_model_info["name"]
                new_p["provider"]      = new_model_info["provider_name"]
                new_p["cost_per_input"]  = float(new_model_info.get("cost_per_input_token") or 0.0)
                new_p["cost_per_output"] = float(new_model_info.get("cost_per_output_token") or 0.0)
                new_p["is_reasoning"]    = bool(new_model_info.get("is_reasoning", 0))
                item_key = f"llm:p{old_p['prompt_id']}:l{old_p['language_id']}:m{new_model_id}"
                cur = conn.execute(
                    """INSERT OR IGNORE INTO run_queue
                       (run_id, operation_type, item_key, payload, status, priority)
                       VALUES (?, 'llm_call', ?, ?, 'pending', 2)""",
                    (run_id, item_key, json.dumps(new_p, default=str)),
                )
                count += cur.rowcount
            conn.commit()
            return count
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
        elif progress["cancelled"] > 0 and progress["pending"] == 0 and progress["running"] == 0:
            status = RUN_STOPPED
        elif progress["pending"] > 0 or progress["running"] > 0:
            status = RUN_RUNNING
        elif progress["error"] > 0 and progress["done"] == 0:
            status = RUN_FAILED
        elif progress["error"] > 0:
            status = RUN_PARTIAL
        else:
            # Tutti gli item attivi sono DONE — verifica se qualche risposta LLM era vuota/invalida
            if self._count_invalid_token_results(run_id) > 0:
                status = RUN_PARTIAL
            else:
                status = RUN_COMPLETED
        self.update_run_status(run_id, status)
        return status

    def _count_invalid_token_results(self, run_id: int) -> int:
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM token_results WHERE run_id=? AND response_valid=0",
                (run_id,),
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
