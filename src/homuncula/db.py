from __future__ import annotations

import collections.abc
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_thread_time
ON messages(thread_id, created_at);

CREATE TABLE IF NOT EXISTS responsibilities (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    proactive_mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wakes (
    id TEXT PRIMARY KEY,
    responsibility_id TEXT NOT NULL REFERENCES responsibilities(id) ON DELETE CASCADE,
    run_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    completed_at TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_wakes_due
ON wakes(status, run_at);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_scope
ON memories(scope, kind, created_at);

CREATE TABLE IF NOT EXISTS memory_revisions (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    previous_content TEXT NOT NULL,
    previous_kind TEXT NOT NULL,
    previous_source TEXT NOT NULL,
    previous_confidence REAL NOT NULL,
    reason TEXT NOT NULL,
    revised_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_revisions_memory
ON memory_revisions(memory_id, revised_at);

CREATE TABLE IF NOT EXISTS memory_vectors (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    responsibility_id TEXT NOT NULL REFERENCES responsibilities(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    current_step INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_plans_responsibility_status
ON plans(responsibility_id, status, updated_at);

CREATE TABLE IF NOT EXISTS plan_steps (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(plan_id, position)
);
CREATE INDEX IF NOT EXISTS idx_plan_steps_plan
ON plan_steps(plan_id, position);

CREATE TABLE IF NOT EXISTS verification_events (
    id TEXT PRIMARY KEY,
    responsibility_id TEXT REFERENCES responsibilities(id) ON DELETE CASCADE,
    action_id TEXT,
    kind TEXT NOT NULL,
    command TEXT NOT NULL,
    cwd TEXT NOT NULL,
    status TEXT NOT NULL,
    exit_code INTEGER NOT NULL,
    output_summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verification_responsibility_time
ON verification_events(responsibility_id, created_at);

CREATE TABLE IF NOT EXISTS grants (
    id TEXT PRIMARY KEY,
    capability TEXT NOT NULL,
    resource_pattern TEXT NOT NULL,
    effect TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    capability TEXT NOT NULL,
    target TEXT NOT NULL,
    intent TEXT NOT NULL,
    args_json TEXT NOT NULL,
    preview TEXT NOT NULL,
    risk TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    completed_at TEXT,
    result_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_actions_status_time
ON actions(status, created_at);

CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY,
    responsibility_id TEXT,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activities_time
ON activities(created_at);

CREATE TABLE IF NOT EXISTS event_subscriptions (
    id TEXT PRIMARY KEY,
    responsibility_id TEXT NOT NULL REFERENCES responsibilities(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    pattern TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_subscriptions_source
ON event_subscriptions(source, enabled);

CREATE TABLE IF NOT EXISTS event_receipts (
    event_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    responsibility_id TEXT REFERENCES responsibilities(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_status_time
ON findings(status, created_at);

CREATE TABLE IF NOT EXISTS background_processes (
    id TEXT PRIMARY KEY,
    responsibility_id TEXT,
    argv_json TEXT NOT NULL,
    cwd TEXT NOT NULL,
    status TEXT NOT NULL,
    pid INTEGER,
    returncode INTEGER,
    stdout TEXT,
    stderr TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT
);
"""

class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            try:
                conn.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                    USING fts5(content, source, content='memories', content_rowid='rowid');

                    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                      INSERT INTO memory_fts(rowid, content, source)
                      VALUES (new.rowid, new.content, new.source);
                    END;

                    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                      INSERT INTO memory_fts(memory_fts, rowid, content, source)
                      VALUES ('delete', old.rowid, old.content, old.source);
                    END;

                    CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                      INSERT INTO memory_fts(memory_fts, rowid, content, source)
                      VALUES ('delete', old.rowid, old.content, old.source);
                      INSERT INTO memory_fts(rowid, content, source)
                      VALUES (new.rowid, new.content, new.source);
                    END;
                    """
                )
                conn.execute(
                    """
                    INSERT INTO memory_fts(rowid, content, source)
                    SELECT m.rowid, m.content, m.source
                    FROM memories m
                    WHERE NOT EXISTS (
                        SELECT 1 FROM memory_fts f WHERE f.rowid = m.rowid
                    )
                    """
                )
            except sqlite3.OperationalError:
                pass

    @contextmanager
    def transaction(
        self,
    ) -> collections.abc.Generator[sqlite3.Connection, None, None]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self.connect() as conn:
            conn.execute(sql, params)

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def setting(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    @staticmethod
    def json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
