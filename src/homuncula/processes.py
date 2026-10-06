from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .db import Database
from .events import EventHub


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class BackgroundProcessManager:
    def __init__(
        self,
        db: Database,
        workspace: Path,
        event_hub: EventHub,
    ):
        self.db = db
        self.workspace = Path(workspace).resolve()
        self.event_hub = event_hub
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def _resolve_cwd(self, relative: str) -> Path:
        candidate = (self.workspace / relative).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise PermissionError(f"Process cwd escapes workspace: {relative}") from exc
        return candidate

    async def start(
        self,
        argv: list[str],
        *,
        cwd: str = ".",
        responsibility_id: str | None = None,
    ) -> dict[str, Any]:
        if not argv or not all(isinstance(part, str) and part for part in argv):
            raise ValueError("argv must contain non-empty strings")

        working_dir = self._resolve_cwd(cwd)
        process_id = "proc_" + uuid.uuid4().hex
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=working_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.db.execute(
            """
            INSERT INTO background_processes
            (id, responsibility_id, argv_json, cwd, status, pid, started_at)
            VALUES (?, ?, ?, ?, 'running', ?, ?)
            """,
            (
                process_id,
                responsibility_id,
                self.db.json(argv),
                cwd,
                process.pid,
                now_iso(),
            ),
        )
        task = asyncio.create_task(
            self._wait(
                process_id,
                process,
                responsibility_id=responsibility_id,
            ),
            name=f"homuncula-{process_id}",
        )
        self._tasks[process_id] = task
        return {
            "process_id": process_id,
            "pid": process.pid,
            "argv": argv,
            "cwd": cwd,
            "status": "running",
        }

    async def _wait(
        self,
        process_id: str,
        process: asyncio.subprocess.Process,
        *,
        responsibility_id: str | None,
    ) -> None:
        stdout_raw, stderr_raw = await process.communicate()
        stdout = stdout_raw.decode("utf-8", errors="replace")[-100_000:]
        stderr = stderr_raw.decode("utf-8", errors="replace")[-100_000:]
        self.db.execute(
            """
            UPDATE background_processes
            SET status = 'completed', returncode = ?, stdout = ?, stderr = ?, completed_at = ?
            WHERE id = ?
            """,
            (process.returncode, stdout, stderr, now_iso(), process_id),
        )
        await self.event_hub.publish(
            "process",
            "completed",
            {
                "process_id": process_id,
                "returncode": process.returncode,
                "responsibility_id": responsibility_id,
                "stdout_tail": stdout[-4000:],
                "stderr_tail": stderr[-4000:],
            },
            event_key=f"process:{process_id}:completed",
        )
        self._tasks.pop(process_id, None)

    def get(self, process_id: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM background_processes WHERE id = ?",
            (process_id,),
        )
        if not row:
            raise KeyError(process_id)
        row["argv"] = json.loads(row.pop("argv_json"))
        return row

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.all(
            """
            SELECT * FROM background_processes
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        )
        for row in rows:
            row["argv"] = json.loads(row.pop("argv_json"))
        return rows

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        if not tasks:
            return
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
