from __future__ import annotations

import collections.abc
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_SCHEMA = """
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

CREATE TABLE IF NOT EXISTS verification_events (
    id TEXT PRIMARY KEY,
    action_id TEXT,
    responsibility_id TEXT,
    kind TEXT NOT NULL,
    command_json TEXT NOT NULL,
    cwd TEXT NOT NULL,
    status TEXT NOT NULL,
    returncode INTEGER NOT NULL,
    stdout_summary TEXT NOT NULL,
    stderr_summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verification_responsibility_time
ON verification_events(responsibility_id, created_at);

"""

MIGRATION_LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


class DatabaseMigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.strip().encode("utf-8")).hexdigest()


BASELINE_VERSION = 1
BASELINE_NAME = "v0.2-baseline"
BASELINE_CHECKSUM = hashlib.sha256(BASE_SCHEMA.strip().encode("utf-8")).hexdigest()

EVIDENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_sources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    locator TEXT NOT NULL,
    title TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(kind, locator)
);

CREATE TABLE IF NOT EXISTS evidence_read_receipts (
    id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL REFERENCES actions(id) ON DELETE RESTRICT,
    responsibility_id TEXT REFERENCES responsibilities(id) ON DELETE SET NULL,
    capability TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    locator TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(action_id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_read_receipts_responsibility_time
ON evidence_read_receipts(responsibility_id, created_at);

CREATE TABLE IF NOT EXISTS evidence_observations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES evidence_sources(id) ON DELETE RESTRICT,
    responsibility_id TEXT REFERENCES responsibilities(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE(source_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_evidence_observations_responsibility_time
ON evidence_observations(responsibility_id, observed_at);

CREATE TABLE IF NOT EXISTS evidence_observation_receipts (
    observation_id TEXT NOT NULL REFERENCES evidence_observations(id) ON DELETE CASCADE,
    receipt_id TEXT NOT NULL REFERENCES evidence_read_receipts(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(observation_id, receipt_id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_observation_receipts_receipt
ON evidence_observation_receipts(receipt_id);

CREATE TABLE IF NOT EXISTS evidence_dossiers (
    id TEXT PRIMARY KEY,
    responsibility_id TEXT REFERENCES responsibilities(id) ON DELETE SET NULL,
    claim TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL,
    precheck_json TEXT NOT NULL,
    declared_unknowns_json TEXT NOT NULL,
    unknowns_json TEXT NOT NULL,
    review_round_id TEXT,
    promoted_memory_id TEXT REFERENCES memories(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_evidence_dossiers_responsibility_status
ON evidence_dossiers(responsibility_id, status, updated_at);

CREATE TABLE IF NOT EXISTS evidence_dossier_observations (
    dossier_id TEXT NOT NULL REFERENCES evidence_dossiers(id) ON DELETE CASCADE,
    observation_id TEXT NOT NULL REFERENCES evidence_observations(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    PRIMARY KEY(dossier_id, observation_id),
    UNIQUE(dossier_id, position)
);

CREATE TABLE IF NOT EXISTS evidence_reviews (
    id TEXT PRIMARY KEY,
    dossier_id TEXT NOT NULL REFERENCES evidence_dossiers(id) ON DELETE CASCADE,
    round_id TEXT NOT NULL,
    role TEXT NOT NULL,
    verdict TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasons_json TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    unknowns_json TEXT NOT NULL,
    valid INTEGER NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(dossier_id, round_id, role)
);
CREATE INDEX IF NOT EXISTS idx_evidence_reviews_dossier_round
ON evidence_reviews(dossier_id, round_id, created_at);
"""

MIGRATIONS = (
    Migration(
        version=2,
        name="epistemic-evidence-and-read-receipts",
        sql=EVIDENCE_SCHEMA,
    ),
)
CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version


def _migration_statements(script: str) -> list[str]:
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines():
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise DatabaseMigrationError("Migration SQL contains an incomplete statement")
    return statements


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
            conn.executescript(MIGRATION_LEDGER_SCHEMA)
            ledger = conn.execute(
                "SELECT COUNT(*) AS count FROM schema_migrations"
            ).fetchone()
            if ledger and int(ledger["count"]) > 0:
                self._validate_migration_ledger(conn)

            conn.executescript(BASE_SCHEMA)
            self._ensure_migration_baseline(conn)
            self._validate_migration_ledger(conn)
            self._apply_pending_migrations(conn)
            self._initialize_fts(conn)

    def _ensure_migration_baseline(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM schema_migrations"
        ).fetchone()
        if row and int(row["count"]) == 0:
            conn.execute(
                """
                INSERT INTO schema_migrations
                (version, name, checksum, applied_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    BASELINE_VERSION,
                    BASELINE_NAME,
                    BASELINE_CHECKSUM,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()

    def _known_migrations(self) -> dict[int, tuple[str, str]]:
        known = {
            BASELINE_VERSION: (BASELINE_NAME, BASELINE_CHECKSUM),
        }
        for migration in MIGRATIONS:
            known[migration.version] = (migration.name, migration.checksum)
        return known

    def _validate_migration_ledger(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT version, name, checksum
            FROM schema_migrations
            ORDER BY version
            """
        ).fetchall()
        known = self._known_migrations()
        versions = [int(row["version"]) for row in rows]
        if not versions:
            raise DatabaseMigrationError("Database migration baseline is missing")
        if versions[-1] > CURRENT_SCHEMA_VERSION:
            raise DatabaseMigrationError(
                "Database schema is newer than this Homuncula build"
            )
        expected_prefix = list(range(BASELINE_VERSION, versions[-1] + 1))
        if versions != expected_prefix:
            raise DatabaseMigrationError(
                "Database migration ledger has missing or out-of-order versions"
            )
        for row in rows:
            version = int(row["version"])
            expected = known.get(version)
            if expected is None:
                raise DatabaseMigrationError(
                    f"Database contains unknown migration version {version}"
                )
            expected_name, expected_checksum = expected
            if row["name"] != expected_name or row["checksum"] != expected_checksum:
                raise DatabaseMigrationError(
                    f"Migration {version} does not match this Homuncula build"
                )

    def _apply_pending_migrations(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT MAX(version) AS version FROM schema_migrations"
        ).fetchone()
        current = int(row["version"]) if row and row["version"] is not None else 0
        for migration in MIGRATIONS:
            if migration.version <= current:
                continue
            self._apply_migration(conn, migration)
            current = migration.version

    def _apply_migration(
        self,
        conn: sqlite3.Connection,
        migration: Migration,
    ) -> None:
        try:
            conn.execute("BEGIN IMMEDIATE")
            for statement in _migration_statements(migration.sql):
                conn.execute(statement)
            conn.execute(
                """
                INSERT INTO schema_migrations
                (version, name, checksum, applied_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise DatabaseMigrationError(
                f"Migration {migration.version} ({migration.name}) failed"
            ) from exc

    def _initialize_fts(self, conn: sqlite3.Connection) -> None:
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

    def schema_status(self) -> dict[str, Any]:
        with self.connect() as conn:
            exists = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'schema_migrations'
                """
            ).fetchone()
            if not exists:
                return {
                    "current_version": 0,
                    "target_version": CURRENT_SCHEMA_VERSION,
                    "applied": [],
                }
            rows = conn.execute(
                """
                SELECT version, name, checksum, applied_at
                FROM schema_migrations
                ORDER BY version
                """
            ).fetchall()
        applied = [dict(row) for row in rows]
        current = int(applied[-1]["version"]) if applied else 0
        return {
            "current_version": current,
            "target_version": CURRENT_SCHEMA_VERSION,
            "applied": applied,
        }

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
