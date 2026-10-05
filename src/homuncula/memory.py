from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from .db import Database
from .embeddings import Embedder, HashEmbedder, cosine_similarity


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class MemoryStore:
    def __init__(self, db: Database, *, embedder: Embedder | None = None):
        self.db = db
        self.embedder = embedder or HashEmbedder()

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
        self._index(memory_id, content)
        return self.get(memory_id)

    def revise(
        self,
        memory_id: str,
        *,
        content: str,
        reason: str,
        kind: str | None = None,
        source: str | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        current = self.get(memory_id)
        self.db.execute(
            """
            INSERT INTO memory_revisions
            (id, memory_id, previous_content, previous_kind, previous_source,
             previous_confidence, reason, revised_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                memory_id,
                current["content"],
                current["kind"],
                current["source"],
                current["confidence"],
                reason,
                now_iso(),
            ),
        )
        self.db.execute(
            """
            UPDATE memories
            SET content = ?, kind = ?, source = ?, confidence = ?
            WHERE id = ?
            """,
            (
                content,
                kind or current["kind"],
                source or current["source"],
                max(
                    0.0,
                    min(
                        1.0,
                        current["confidence"] if confidence is None else confidence,
                    ),
                ),
                memory_id,
            ),
        )
        self._index(memory_id, content)
        return self.get(memory_id)

    def get(self, memory_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM memories WHERE id = ?", (memory_id,))
        if not row:
            raise KeyError(memory_id)
        row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
        row["revisions"] = self.db.all(
            """
            SELECT id, previous_content, previous_kind, previous_source,
                   previous_confidence, reason, revised_at
            FROM memory_revisions
            WHERE memory_id = ?
            ORDER BY revised_at DESC
            """,
            (memory_id,),
        )
        return row

    def list(
        self,
        *,
        scope: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if scope:
            clauses.append("(scope = ? OR scope = 'global')")
            params.append(scope)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(limit, 500)))
        rows = self.db.all(
            f"SELECT * FROM memories{where} ORDER BY created_at DESC LIMIT ?",
            tuple(params),
        )
        for row in rows:
            row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
        return rows

    def search(
        self,
        query: str,
        *,
        scope: str = "global",
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 50))
        lexical = self._lexical_search(query, scope=scope, limit=max(limit * 3, 12))
        semantic = self._semantic_search(query, scope=scope, limit=max(limit * 3, 12))

        combined: dict[str, dict[str, Any]] = {}
        for rank, row in enumerate(lexical):
            item = combined.setdefault(row["id"], dict(row))
            item["lexical_score"] = max(item.get("lexical_score", 0.0), 1.0 / (rank + 1))
            item.setdefault("semantic_score", 0.0)

        for row, score in semantic:
            item = combined.setdefault(row["id"], dict(row))
            item["semantic_score"] = max(item.get("semantic_score", 0.0), score)
            item.setdefault("lexical_score", 0.0)

        for item in combined.values():
            confidence = float(item.get("confidence", 1.0))
            recency_bonus = 0.02 if item.get("last_used_at") else 0.0
            item["score"] = (
                0.55 * item["semantic_score"]
                + 0.35 * item["lexical_score"]
                + 0.10 * confidence
                + recency_bonus
            )

        rows = sorted(
            combined.values(),
            key=lambda item: (item["score"], item["created_at"]),
            reverse=True,
        )[:limit]

        if rows:
            ids = [row["id"] for row in rows]
            placeholders = ",".join("?" for _ in ids)
            self.db.execute(
                f"UPDATE memories SET last_used_at = ? WHERE id IN ({placeholders})",
                (now_iso(), *ids),
            )

        for row in rows:
            row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
        return rows

    def _lexical_search(
        self,
        query: str,
        *,
        scope: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            return self.db.all(
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
            return self.db.all(
                """
                SELECT * FROM memories
                WHERE (scope = ? OR scope = 'global')
                  AND (content LIKE ? OR source LIKE ?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (scope, like, like, limit),
            )

    def _semantic_search(
        self,
        query: str,
        *,
        scope: str,
        limit: int,
    ) -> list[tuple[dict[str, Any], float]]:
        query_vector = self.embedder.embed(query)
        if not query_vector:
            return []
        rows = self.db.all(
            """
            SELECT m.*, v.model, v.dimensions, v.vector_json
            FROM memory_vectors v
            JOIN memories m ON m.id = v.memory_id
            WHERE m.scope = ? OR m.scope = 'global'
            """,
            (scope,),
        )
        scored = []
        for row in rows:
            vector = json.loads(row.pop("vector_json"))
            row.pop("model", None)
            row.pop("dimensions", None)
            score = cosine_similarity(query_vector, vector)
            if score > 0:
                scored.append((row, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def _index(self, memory_id: str, content: str) -> None:
        vector = self.embedder.embed(content)
        if not vector:
            return
        self.db.execute(
            """
            INSERT INTO memory_vectors
            (memory_id, model, dimensions, vector_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                model = excluded.model,
                dimensions = excluded.dimensions,
                vector_json = excluded.vector_json,
                updated_at = excluded.updated_at
            """,
            (
                memory_id,
                self.embedder.name,
                len(vector),
                self.db.json(vector),
                now_iso(),
            ),
        )
