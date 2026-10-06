from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from .db import Database


TEST_PATTERNS = (
    re.compile(r"(^|\s)(pytest|py\.test)(\s|$)"),
    re.compile(r"python\s+-m\s+unittest"),
    re.compile(r"(^|\s)(cargo|go|dotnet)\s+test(\s|$)"),
    re.compile(r"(^|\s)(npm|pnpm|yarn)\s+(run\s+)?test(\s|$)"),
)
LINT_PATTERNS = (
    re.compile(r"(^|\s)(ruff|flake8|pylint|eslint)(\s|$)"),
    re.compile(r"python\s+-m\s+ruff"),
)
TYPECHECK_PATTERNS = (
    re.compile(r"(^|\s)(tsc|mypy|pyright)(\s|$)"),
    re.compile(r"typecheck"),
)
BUILD_PATTERNS = (
    re.compile(r"(^|\s)(cargo|dotnet)\s+build(\s|$)"),
    re.compile(r"(^|\s)(npm|pnpm|yarn)\s+run\s+build(\s|$)"),
    re.compile(r"python\s+-m\s+build"),
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def classify_command(argv: list[str]) -> str | None:
    command = " ".join(argv).strip().lower()
    for pattern in TEST_PATTERNS:
        if pattern.search(command):
            return "test"
    for pattern in LINT_PATTERNS:
        if pattern.search(command):
            return "lint"
    for pattern in TYPECHECK_PATTERNS:
        if pattern.search(command):
            return "typecheck"
    for pattern in BUILD_PATTERNS:
        if pattern.search(command):
            return "build"
    return None


def summarize_output(stdout: str, stderr: str, *, limit: int = 1800) -> str:
    text = (stdout + "\n" + stderr).strip()
    if len(text) <= limit:
        return text
    half = max(1, limit // 2)
    omitted = len(text) - (half * 2)
    return text[:half] + f"\n...[{omitted} chars omitted]...\n" + text[-half:]


class VerificationStore:
    def __init__(self, db: Database):
        self.db = db

    def record_process(
        self,
        *,
        argv: list[str],
        cwd: str,
        returncode: int,
        stdout: str,
        stderr: str,
        responsibility_id: str | None = None,
        action_id: str | None = None,
    ) -> dict[str, Any] | None:
        kind = classify_command(argv)
        if kind is None:
            return None

        event_id = "verify_" + uuid.uuid4().hex
        command = " ".join(argv)
        self.db.execute(
            """
            INSERT INTO verification_events
            (id, responsibility_id, action_id, kind, command, cwd, status,
             exit_code, output_summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                responsibility_id,
                action_id,
                kind,
                command,
                cwd,
                "passed" if returncode == 0 else "failed",
                returncode,
                summarize_output(stdout, stderr),
                now_iso(),
            ),
        )
        return self.get(event_id)

    def get(self, event_id: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM verification_events WHERE id = ?",
            (event_id,),
        )
        if not row:
            raise KeyError(event_id)
        return row

    def list(
        self,
        *,
        responsibility_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        if responsibility_id:
            return self.db.all(
                """
                SELECT * FROM verification_events
                WHERE responsibility_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (responsibility_id, limit),
            )
        return self.db.all(
            """
            SELECT * FROM verification_events
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    def summary(self, responsibility_id: str | None = None) -> dict[str, Any]:
        rows = self.list(responsibility_id=responsibility_id, limit=100)
        latest_by_kind: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest_by_kind.setdefault(row["kind"], row)
        return {
            "latest_by_kind": latest_by_kind,
            "passing_kinds": sorted(
                kind
                for kind, row in latest_by_kind.items()
                if row["status"] == "passed"
            ),
            "failing_kinds": sorted(
                kind
                for kind, row in latest_by_kind.items()
                if row["status"] == "failed"
            ),
            "count": len(rows),
        }
