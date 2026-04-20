"""
TokenScribe — Database Manager
Author: Matteo Morreale

Handles SQLite connection, schema bootstrap and seed data.
All schema creation is idempotent (CREATE TABLE IF NOT EXISTS).
"""

import sqlite3
import os
import json
from datetime import datetime, timezone


class DatabaseManager:
    """
    Central database access class for TokenScribe.
    Provides connection management and schema bootstrap.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Return a new SQLite connection with row_factory set."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    # ------------------------------------------------------------------
    # Schema Bootstrap
    # ------------------------------------------------------------------

    def bootstrap(self):
        """Create all tables and seed reference data if not present."""
        conn = self.get_connection()
        try:
            self._create_tables(conn)
            self._seed_writing_systems(conn)
            self._seed_languages(conn)
            self._seed_providers(conn)
            conn.commit()
        finally:
            conn.close()

    def _create_tables(self, conn: sqlite3.Connection):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS writing_systems (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS languages (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT NOT NULL,
                code              TEXT NOT NULL UNIQUE,
                writing_system_id INTEGER NOT NULL REFERENCES writing_systems(id)
            );

            CREATE TABLE IF NOT EXISTS studies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                description TEXT,
                config      TEXT DEFAULT '{}',
                created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );

            CREATE TABLE IF NOT EXISTS prompts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                study_id   INTEGER NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                base_text  TEXT NOT NULL,
                category   TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );

            CREATE TABLE IF NOT EXISTS translation_candidates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt_id   INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
                language_id INTEGER NOT NULL REFERENCES languages(id),
                text        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
                version     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );

            CREATE TABLE IF NOT EXISTS translation_scores (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL UNIQUE REFERENCES translation_candidates(id) ON DELETE CASCADE,
                dsf          REAL,
                rtf          REAL,
                sfs          REAL,
                computed_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );

            CREATE TABLE IF NOT EXISTS approved_translations (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt_id    INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
                language_id  INTEGER NOT NULL REFERENCES languages(id),
                candidate_id INTEGER NOT NULL REFERENCES translation_candidates(id),
                approved_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
                UNIQUE(prompt_id, language_id)
            );

            CREATE TABLE IF NOT EXISTS providers (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS models (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id           INTEGER NOT NULL REFERENCES providers(id),
                name                  TEXT NOT NULL,
                context_window        INTEGER DEFAULT 0,
                cost_per_input_token  REAL DEFAULT 0.0,
                cost_per_output_token REAL DEFAULT 0.0,
                is_active             INTEGER NOT NULL DEFAULT 1,
                UNIQUE(provider_id, name)
            );

            CREATE TABLE IF NOT EXISTS experiment_runs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                study_id   INTEGER NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                notes      TEXT,
                timestamp  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );

            CREATE TABLE IF NOT EXISTS token_results (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id        INTEGER NOT NULL REFERENCES experiment_runs(id) ON DELETE CASCADE,
                prompt_id     INTEGER NOT NULL REFERENCES prompts(id),
                language_id   INTEGER NOT NULL REFERENCES languages(id),
                model_id      INTEGER NOT NULL REFERENCES models(id),
                input_tokens  INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cost          REAL NOT NULL DEFAULT 0.0,
                source        TEXT NOT NULL DEFAULT 'api_reported' CHECK(source IN ('api_reported','estimated')),
                created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );

            CREATE TABLE IF NOT EXISTS pei_results (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          INTEGER NOT NULL REFERENCES experiment_runs(id) ON DELETE CASCADE,
                prompt_id       INTEGER NOT NULL REFERENCES prompts(id),
                cv_char_length  REAL,
                cv_word_count   REAL,
                cv_token_count  REAL,
                pei             REAL,
                computed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                key        TEXT NOT NULL UNIQUE,
                value      TEXT,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );
        """)

    def _seed_writing_systems(self, conn: sqlite3.Connection):
        from config import TokenScribeConfig
        for ws in TokenScribeConfig.WRITING_SYSTEMS:
            conn.execute(
                "INSERT OR IGNORE INTO writing_systems (name) VALUES (?)", (ws,)
            )

    def _seed_languages(self, conn: sqlite3.Connection):
        from config import TokenScribeConfig
        for name, code, ws_name in TokenScribeConfig.SEED_LANGUAGES:
            row = conn.execute(
                "SELECT id FROM writing_systems WHERE name = ?", (ws_name,)
            ).fetchone()
            if row:
                conn.execute(
                    "INSERT OR IGNORE INTO languages (name, code, writing_system_id) VALUES (?, ?, ?)",
                    (name, code, row["id"]),
                )

    def _seed_providers(self, conn: sqlite3.Connection):
        from config import TokenScribeConfig
        for provider_name, models in TokenScribeConfig.DEFAULT_MODELS.items():
            conn.execute(
                "INSERT OR IGNORE INTO providers (name) VALUES (?)", (provider_name,)
            )
            provider_row = conn.execute(
                "SELECT id FROM providers WHERE name = ?", (provider_name,)
            ).fetchone()
            if provider_row:
                for m in models:
                    conn.execute(
                        """INSERT OR IGNORE INTO models
                           (provider_id, name, context_window)
                           VALUES (?, ?, ?)""",
                        (provider_row["id"], m["name"], m.get("context_window", 0)),
                    )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def reset(self):
        """Drop all tables and re-bootstrap. Used from Settings UI."""
        conn = self.get_connection()
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            for t in tables:
                conn.execute(f"DROP TABLE IF EXISTS [{t['name']}]")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.commit()
        finally:
            conn.close()
        self.bootstrap()

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
