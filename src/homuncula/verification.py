from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from .db import Database


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def classify_command(argv: list[str]) -> str:
    text = " ".join(argv).lower()
    if any(token in text for token in ("pytest", "unittest", "npm test", "pnpm test", "vitest", "jest")):
        return "test"
    if any(token in text for token in ("ruff", "flake8", "eslint", "mypy", "typecheck", "tsc")):
        return "quality"
    if any(token in text for token in ("build", "pyinstaller", "electron-builder", "cargo build")):
        return "build"
    if "git diff" in text or "git status" in text:
        return "inspection"
    return "command"


class VerificationStore:
    def __init__(self, db: Database):
        self.db = db

    def record_process(
        self,
        *,
        action_id: str,
        responsibility_id: str | None,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        argv = [str(part) for part in result.get("argv", [])]
        returncode = int(result.get("returncode", -1))
        record_id = "verify_" + uuid.uuid4().hex
        self.db.execute(
            """
            INSERT INTO verification_events
            (id, action_id, responsibility_id, kind, command_json, cwd, status,
             returncode, stdout_summary, stderr_summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                action_id,
                responsibility_id,
                classify_command(argv),
                self.db.json(argv),
                str(result.get("cwd", ".")),
                "passed" if returncode == 0 else "failed",
                returncode,
                str(result.get("stdout", ""))[-4000:],
                str(result.get("stderr", ""))[-4000:],
                now_iso(),
            ),
        )
        return self.get(record_id)

    def get(self, record_id: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM verification_events WHERE id = ?",
            (record_id,),
        )
        if not row:
            raise KeyError(record_id)
        row["command"] = json.loads(row.pop("command_json"))
        return row

    def list(
        self,
        *,
        responsibility_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if responsibility_id:
            rows = self.db.all(
                """
                SELECT * FROM verification_events
                WHERE responsibility_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (responsibility_id, max(1, min(limit, 500))),
            )
        else:
            rows = self.db.all(
                """
                SELECT * FROM verification_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            )
        for row in rows:
            row["command"] = json.loads(row.pop("command_json"))
        return rows

    def summary(self, responsibility_id: str | None = None) -> dict[str, Any]:
        rows = self.list(responsibility_id=responsibility_id, limit=50)
        latest_by_kind: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest_by_kind.setdefault(row["kind"], row)
        return {
            "latest_by_kind": latest_by_kind,
            "total": len(rows),
            "has_failed": any(row["status"] == "failed" for row in rows),
        }
