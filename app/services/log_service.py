"""
TokenScribe — LogService
Author: Matteo Morreale

Non-blocking async logging for AI operations (LLM calls, MAGI judges, experiments, translations).
Writes are queued and flushed by a daemon thread so callers never block.
"""

import json
import queue
import sqlite3
import threading
import time


class LogService:
    """
    Thread-safe async logger that writes operation_logs rows to SQLite.

    Usage:
        log_service.log(operation_type='experiment', event='llm_call_success', ...)
    """

    MAX_QUEUE_SIZE = 5000

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._queue: queue.Queue = queue.Queue(maxsize=self.MAX_QUEUE_SIZE)
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="ts-log-worker"
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # Public API — never blocks the caller
    # ------------------------------------------------------------------

    def log(
        self,
        operation_type: str,
        event: str,
        level: str = "INFO",
        provider: str | None = None,
        model: str | None = None,
        message: str | None = None,
        context_ref: dict | None = None,
        payload: dict | None = None,
        duration_ms: int | None = None,
    ) -> None:
        entry = {
            "operation_type": operation_type,
            "event": event,
            "level": level,
            "provider": provider,
            "model": model,
            "message": message,
            "context_ref": json.dumps(context_ref, default=str) if context_ref else None,
            "payload": json.dumps(payload, default=str) if payload else None,
            "duration_ms": duration_ms,
        }
        try:
            self._queue.put_nowait(entry)
        except queue.Full:
            pass  # drop silently when queue saturated — never block

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    def info(self, operation_type: str, event: str, **kwargs) -> None:
        self.log(operation_type, event, level="INFO", **kwargs)

    def warning(self, operation_type: str, event: str, **kwargs) -> None:
        self.log(operation_type, event, level="WARNING", **kwargs)

    def error(self, operation_type: str, event: str, **kwargs) -> None:
        self.log(operation_type, event, level="ERROR", **kwargs)

    def debug(self, operation_type: str, event: str, **kwargs) -> None:
        self.log(operation_type, event, level="DEBUG", **kwargs)

    # ------------------------------------------------------------------
    # Background worker — runs in daemon thread
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        conn: sqlite3.Connection | None = None
        idle_closes = 0

        while True:
            try:
                entry = self._queue.get(timeout=5.0)
                if conn is None:
                    conn = self._open_conn()
                self._insert(conn, entry)
                self._queue.task_done()
                idle_closes = 0
            except queue.Empty:
                # Close idle connection after ~30 s of inactivity (6 x 5 s timeouts)
                idle_closes += 1
                if conn and idle_closes >= 6:
                    self._close_conn(conn)
                    conn = None
                    idle_closes = 0
            except Exception:
                # Never let the worker die; try to reset the connection
                self._close_conn(conn)
                conn = None
                time.sleep(1)

    def _open_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @staticmethod
    def _close_conn(conn: sqlite3.Connection | None) -> None:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    @staticmethod
    def _insert(conn: sqlite3.Connection, entry: dict) -> None:
        conn.execute(
            """INSERT INTO operation_logs
               (operation_type, event, level, provider, model,
                message, context_ref, payload, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry["operation_type"],
                entry["event"],
                entry["level"],
                entry["provider"],
                entry["model"],
                entry["message"],
                entry["context_ref"],
                entry["payload"],
                entry["duration_ms"],
            ),
        )
        conn.commit()
