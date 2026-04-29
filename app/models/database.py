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
            self._migrate_schema(conn)
            self._seed_writing_systems(conn)
            self._seed_languages(conn)
            self._seed_providers(conn)
            conn.commit()
        finally:
            conn.close()

    def _migrate_schema(self, conn: sqlite3.Connection):
        try:
            cur = conn.execute("PRAGMA table_info(token_results)")
            columns = [row[1] for row in cur.fetchall()]
            if "response_text" not in columns:
                conn.execute("ALTER TABLE token_results ADD COLUMN response_text TEXT")
            if "visible_output_text_length" not in columns:
                conn.execute("ALTER TABLE token_results ADD COLUMN visible_output_text_length INTEGER")
            if "api_reported_output_tokens" not in columns:
                conn.execute("ALTER TABLE token_results ADD COLUMN api_reported_output_tokens INTEGER")
            if "token_accounting_mode" not in columns:
                conn.execute("ALTER TABLE token_results ADD COLUMN token_accounting_mode TEXT")
        except sqlite3.Error:
            pass

        try:
            cur = conn.execute("PRAGMA table_info(languages)")
            columns = [row[1] for row in cur.fetchall()]
            if "script_group" not in columns:
                conn.execute("ALTER TABLE languages ADD COLUMN script_group TEXT")
            if "morphology_group" not in columns:
                conn.execute("ALTER TABLE languages ADD COLUMN morphology_group TEXT")
        except sqlite3.Error:
            pass

        try:
            cur = conn.execute("PRAGMA table_info(pei_results)")
            columns = [row[1] for row in cur.fetchall()]
            if "script_group_count" not in columns:
                conn.execute("ALTER TABLE pei_results ADD COLUMN script_group_count INTEGER")
            if "morphology_group_count" not in columns:
                conn.execute("ALTER TABLE pei_results ADD COLUMN morphology_group_count INTEGER")
            if "pei_band" not in columns:
                conn.execute("ALTER TABLE pei_results ADD COLUMN pei_band TEXT")
        except sqlite3.Error:
            pass

        try:
            cur = conn.execute("PRAGMA table_info(pei_group_results)")
            columns = [row[1] for row in cur.fetchall()]
            if "baseline_pei" not in columns:
                conn.execute("ALTER TABLE pei_group_results ADD COLUMN baseline_pei REAL")
            if "pei_delta_vs_group" not in columns:
                conn.execute("ALTER TABLE pei_group_results ADD COLUMN pei_delta_vs_group REAL")
        except sqlite3.Error:
            pass

        try:
            cur = conn.execute("PRAGMA table_info(translation_scores)")
            columns = [row[1] for row in cur.fetchall()]
            if "ler_char" not in columns:
                conn.execute("ALTER TABLE translation_scores ADD COLUMN ler_char REAL")
            if "ler_token" not in columns:
                conn.execute("ALTER TABLE translation_scores ADD COLUMN ler_token REAL")
        except sqlite3.Error:
            pass

        try:
            cur = conn.execute("PRAGMA table_info(token_results)")
            columns = [row[1] for row in cur.fetchall()]
            if "normalized_output_tokens" not in columns:
                conn.execute("ALTER TABLE token_results ADD COLUMN normalized_output_tokens INTEGER")
            if "visible_output_tokens" not in columns:
                conn.execute("ALTER TABLE token_results ADD COLUMN visible_output_tokens INTEGER")
            if "response_valid" not in columns:
                conn.execute("ALTER TABLE token_results ADD COLUMN response_valid INTEGER NOT NULL DEFAULT 1")
                conn.execute("UPDATE token_results SET response_valid = CASE WHEN COALESCE(response_text, '') = '' THEN 0 ELSE 1 END")
        except sqlite3.Error:
            pass

        try:
            cur = conn.execute("PRAGMA table_info(selection_score_results)")
            columns = [row[1] for row in cur.fetchall()]
            if "magi_score" not in columns:
                conn.execute("ALTER TABLE selection_score_results ADD COLUMN magi_score REAL")
            if "magi_disagreement" not in columns:
                conn.execute("ALTER TABLE selection_score_results ADD COLUMN magi_disagreement INTEGER")
            if "magi_judges" not in columns:
                conn.execute("ALTER TABLE selection_score_results ADD COLUMN magi_judges TEXT")
        except sqlite3.Error:
            pass

        try:
            cur = conn.execute("PRAGMA table_info(models)")
            columns = [row[1] for row in cur.fetchall()]
            if "is_reasoning" not in columns:
                conn.execute("ALTER TABLE models ADD COLUMN is_reasoning INTEGER NOT NULL DEFAULT 0")
        except sqlite3.Error:
            pass

        try:
            cur = conn.execute("PRAGMA table_info(prompts)")
            columns = [row[1] for row in cur.fetchall()]
            if "notes" not in columns:
                conn.execute("ALTER TABLE prompts ADD COLUMN notes TEXT DEFAULT ''")
            if "pei_value" not in columns:
                conn.execute("ALTER TABLE prompts ADD COLUMN pei_value REAL")
            if "pei_cv_char" not in columns:
                conn.execute("ALTER TABLE prompts ADD COLUMN pei_cv_char REAL")
            if "pei_cv_word" not in columns:
                conn.execute("ALTER TABLE prompts ADD COLUMN pei_cv_word REAL")
            if "pei_cv_token" not in columns:
                conn.execute("ALTER TABLE prompts ADD COLUMN pei_cv_token REAL")
            if "pei_saved_at" not in columns:
                conn.execute("ALTER TABLE prompts ADD COLUMN pei_saved_at TEXT")
        except sqlite3.Error:
            pass

        try:
            cur = conn.execute("PRAGMA table_info(experiment_runs)")
            columns = [row[1] for row in cur.fetchall()]
            if "status" not in columns:
                conn.execute(
                    "ALTER TABLE experiment_runs ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'"
                )
                # Runs that already exist without a queue are completed by definition
                conn.execute("UPDATE experiment_runs SET status = 'completed'")
        except sqlite3.Error:
            pass

        # Seed default MAGI judge settings (only if not yet configured)
        try:
            judge_seeds = [
                ("magi_judge_balthasar_id", "openai",     "gpt-4.1"),
                ("magi_judge_caspar_id",    "anthropic",  "claude-opus-4-5"),
                ("magi_judge_melchior_id",  "google",     "gemini-2.5-pro"),
            ]
            for key, pname, mname in judge_seeds:
                if conn.execute("SELECT id FROM settings WHERE key=?", (key,)).fetchone():
                    continue
                row = conn.execute(
                    """SELECT m.id FROM models m
                       JOIN providers p ON p.id = m.provider_id
                       WHERE p.name=? AND m.name=?""",
                    (pname, mname),
                ).fetchone()
                if row:
                    conn.execute(
                        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                        (key, str(row["id"])),
                    )
        except sqlite3.Error:
            pass

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
                writing_system_id INTEGER NOT NULL REFERENCES writing_systems(id),
                script_group      TEXT,
                morphology_group  TEXT
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
                notes      TEXT DEFAULT '',
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
                is_reasoning          INTEGER NOT NULL DEFAULT 0,
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
                visible_output_text_length INTEGER,
                api_reported_output_tokens INTEGER,
                cost          REAL NOT NULL DEFAULT 0.0,
                source        TEXT NOT NULL DEFAULT 'api_reported' CHECK(source IN ('api_reported','estimated')),
                token_accounting_mode TEXT,
                response_text TEXT,
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
                script_group_count INTEGER,
                morphology_group_count INTEGER,
                pei_band         TEXT,
                computed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );

            CREATE TABLE IF NOT EXISTS pei_group_results (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id             INTEGER NOT NULL REFERENCES experiment_runs(id) ON DELETE CASCADE,
                prompt_id          INTEGER NOT NULL REFERENCES prompts(id),
                group_type         TEXT NOT NULL,
                group_value        TEXT NOT NULL,
                language_count     INTEGER NOT NULL DEFAULT 0,
                cv_char_length     REAL,
                cv_word_count      REAL,
                cv_token_count     REAL,
                pei                REAL,
                pei_delta_vs_global REAL,
                baseline_pei        REAL,
                pei_delta_vs_group  REAL,
                pei_band           TEXT,
                computed_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );

            CREATE TABLE IF NOT EXISTS selection_score_results (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id   INTEGER NOT NULL UNIQUE REFERENCES translation_candidates(id) ON DELETE CASCADE,
                prompt_id      INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
                score_absolute REAL,
                score_rank     INTEGER,
                score_rank_pct REAL,
                magi_required  INTEGER NOT NULL DEFAULT 0,
                lambda_used    REAL,
                nu_used        REAL,
                computed_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );

            CREATE TABLE IF NOT EXISTS run_translation_snapshot (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id       INTEGER NOT NULL REFERENCES experiment_runs(id) ON DELETE CASCADE,
                prompt_id    INTEGER NOT NULL REFERENCES prompts(id),
                language_id  INTEGER NOT NULL REFERENCES languages(id),
                candidate_id INTEGER NOT NULL REFERENCES translation_candidates(id),
                snapshotted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
                UNIQUE(run_id, prompt_id, language_id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                key        TEXT NOT NULL UNIQUE,
                value      TEXT,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );

            CREATE TABLE IF NOT EXISTS operation_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_type  TEXT NOT NULL,
                event           TEXT NOT NULL,
                level           TEXT NOT NULL DEFAULT 'INFO',
                provider        TEXT,
                model           TEXT,
                context_ref     TEXT,
                message         TEXT,
                payload         TEXT,
                duration_ms     INTEGER,
                created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
            );

            CREATE INDEX IF NOT EXISTS idx_oplogs_type    ON operation_logs(operation_type);
            CREATE INDEX IF NOT EXISTS idx_oplogs_level   ON operation_logs(level);
            CREATE INDEX IF NOT EXISTS idx_oplogs_created ON operation_logs(created_at DESC);

            CREATE TABLE IF NOT EXISTS run_queue (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id         INTEGER NOT NULL REFERENCES experiment_runs(id) ON DELETE CASCADE,
                operation_type TEXT NOT NULL,
                item_key       TEXT NOT NULL,
                payload        TEXT NOT NULL DEFAULT '{}',
                status         TEXT NOT NULL DEFAULT 'pending'
                               CHECK(status IN ('pending','running','done','error','timeout')),
                priority       INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
                started_at     TEXT,
                completed_at   TEXT,
                error_message  TEXT,
                retry_count    INTEGER NOT NULL DEFAULT 0,
                UNIQUE(run_id, operation_type, item_key)
            );

            CREATE INDEX IF NOT EXISTS idx_runq_run_id ON run_queue(run_id);
            CREATE INDEX IF NOT EXISTS idx_runq_status ON run_queue(status, priority, id);
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

        rows = conn.execute(
            """SELECT l.id, l.code, l.script_group, l.morphology_group, ws.name as writing_system
               FROM languages l
               JOIN writing_systems ws ON ws.id = l.writing_system_id"""
        ).fetchall()

        for r in rows:
            script_group = r["script_group"]
            if not script_group:
                ws = (r["writing_system"] or "").strip().lower()
                if ws in {"logographic", "mixed"}:
                    script_group = "logographic_mixed"
                else:
                    script_group = "alphabetic"

            morphology_group = r["morphology_group"]
            if not morphology_group:
                code = (r["code"] or "").strip().lower()
                if code in {"tr", "ja", "ko"}:
                    morphology_group = "agglutinative"

            conn.execute(
                "UPDATE languages SET script_group=?, morphology_group=? WHERE id=?",
                (script_group, morphology_group, r["id"]),
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
                           (provider_id, name, context_window, is_reasoning)
                           VALUES (?, ?, ?, ?)""",
                        (provider_row["id"], m["name"], m.get("context_window", 0),
                         1 if m.get("is_reasoning", False) else 0),
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
