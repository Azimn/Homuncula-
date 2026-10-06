from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from homuncula.db import (
    BASE_SCHEMA,
    CURRENT_SCHEMA_VERSION,
    Database,
    DatabaseMigrationError,
    Migration,
)


def test_fresh_database_reaches_current_schema_version(tmp_path: Path) -> None:
    db = Database(tmp_path / "fresh.sqlite3")
    db.initialize()

    status = db.schema_status()
    assert status["current_version"] == CURRENT_SCHEMA_VERSION
    assert status["target_version"] == CURRENT_SCHEMA_VERSION
    assert [item["version"] for item in status["applied"]] == [1, 2]

    evidence_table = db.one(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = 'evidence_dossiers'
        """
    )
    assert evidence_table == {"name": "evidence_dossiers"}


def test_v02_database_upgrades_without_losing_durable_state(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.executescript(BASE_SCHEMA)
        conn.execute(
            """
            INSERT INTO threads (id, title, created_at, updated_at)
            VALUES ('thread-1', 'Legacy thread', '2026-10-06T00:00:00+00:00',
                    '2026-10-06T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO memories
            (id, scope, kind, content, source, confidence, metadata_json, created_at)
            VALUES ('memory-1', 'global', 'fact', 'Legacy durable memory',
                    'user', 1.0, '{}', '2026-10-06T00:00:00+00:00')
            """
        )

    db = Database(path)
    db.initialize()

    assert db.one("SELECT title FROM threads WHERE id = 'thread-1'") == {
        "title": "Legacy thread"
    }
    assert db.one("SELECT content FROM memories WHERE id = 'memory-1'") == {
        "content": "Legacy durable memory"
    }
    assert db.schema_status()["current_version"] == CURRENT_SCHEMA_VERSION
    assert db.one(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = 'evidence_read_receipts'
        """
    ) == {"name": "evidence_read_receipts"}


def test_initialize_is_idempotent_after_migrations(tmp_path: Path) -> None:
    db = Database(tmp_path / "idempotent.sqlite3")
    db.initialize()
    first = db.schema_status()

    db.initialize()
    second = db.schema_status()

    assert second == first
    assert db.one("SELECT COUNT(*) AS count FROM schema_migrations") == {
        "count": 2
    }


def test_tampered_migration_checksum_is_rejected(tmp_path: Path) -> None:
    db = Database(tmp_path / "tampered.sqlite3")
    db.initialize()
    db.execute(
        "UPDATE schema_migrations SET checksum = 'tampered' WHERE version = 2"
    )

    with pytest.raises(DatabaseMigrationError, match="does not match"):
        db.initialize()


def test_database_from_newer_homuncula_build_is_rejected_without_baseline_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO schema_migrations
            (version, name, checksum, applied_at)
            VALUES (?, 'future', 'future', '2026-10-06T00:00:00+00:00')
            """,
            (CURRENT_SCHEMA_VERSION + 1,),
        )

    db = Database(path)
    with pytest.raises(DatabaseMigrationError, match="newer"):
        db.initialize()

    with sqlite3.connect(path) as conn:
        threads = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'threads'
            """
        ).fetchone()
    assert threads is None


def test_failed_migration_rolls_back_schema_and_ledger(tmp_path: Path) -> None:
    db = Database(tmp_path / "rollback.sqlite3")
    db.initialize()
    migration = Migration(
        version=CURRENT_SCHEMA_VERSION + 1,
        name="intentional-failure",
        sql="""
        CREATE TABLE migration_rollback_probe (
            id TEXT PRIMARY KEY
        );
        INSERT INTO table_that_does_not_exist (id) VALUES ('boom');
        """,
    )

    with db.connect() as conn:
        with pytest.raises(DatabaseMigrationError, match="failed"):
            db._apply_migration(conn, migration)

    assert db.one(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = 'migration_rollback_probe'
        """
    ) is None
    assert db.one(
        "SELECT version FROM schema_migrations WHERE version = ?",
        (migration.version,),
    ) is None
