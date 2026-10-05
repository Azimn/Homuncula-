from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from .db import Database


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class MemoryStore:
    def __init__(self, db: Database):
        self.db = db

    def add(
        self,
        content: str,
        *,
        scope: str = "global",
        kind: str = "fact",
        source: str = "agent",
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        memory_id = uuid.uuid4().hex
        created_at = now_iso()
        self.db.execute(
            """
            INSERT INTO memories
            (id, scope, kind, content, source, confidence, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                scope,
                kind,
                content,
                source,
                max(0.0, min(1.0, confidence)),
                self.db.json(metadata or {}),
                created_at,
            ),
        )
        return self.get(memory_id)

    def get(self, memory_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM memories WHERE id = ?", (memory_id,))
        if not row:
            raise KeyError(memory_id)
        return row

    def search(
        self,
        query: str,
        *,
        scope: str = "global",
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 50))
        try:
            rows = self.db.all(
                """
                SELECT m.*
                FROM memory_fts f
                JOIN memories m ON m.rowid = f.rowid
                WHERE memory_fts MATCH ?
                  AND (m.scope = ? OR m.scope = 'global')
                ORDER BY bm25(memory_fts), m.created_at DESC
                LIMIT ?
                """,
                (query, scope, limit),
            )
        except sqlite3.OperationalError:
            like = f"%{query}%"
            rows = self.db.all(
                """
                SELECT * FROM memories
                WHERE (scope = ? OR scope = 'global')
                  AND (content LIKE ? OR source LIKE ?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (scope, like, like, limit),
            )

        if rows:
            ids = [row["id"] for row in rows]
            placeholders = ",".join("?" for _ in ids)
            self.db.execute(
                f"UPDATE memories SET last_used_at = ? WHERE id IN ({placeholders})",
                (now_iso(), *ids),
            )
        return rows
