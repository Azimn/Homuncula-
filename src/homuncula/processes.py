from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .db import Database
from .events import EventHub
from .process_control import (
    TailBuffer,
    isolation_popen_kwargs,
    sanitized_process_environment,
    terminate_pid_tree,
)


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
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._terminating: set[str] = set()

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
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=sanitized_process_environment(),
            **isolation_popen_kwargs(),
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
        self._processes[process_id] = process
        return {
            "process_id": process_id,
            "pid": process.pid,
            "argv": argv,
            "cwd": cwd,
            "status": "running",
        }

    async def _drain(
        self,
        reader: asyncio.StreamReader | None,
        buffer: TailBuffer,
    ) -> None:
        if reader is None:
            return
        while True:
            chunk = await reader.read(64 * 1024)
            if not chunk:
                break
            buffer.append(chunk)

    @staticmethod
    def _stored_output(buffer: TailBuffer) -> tuple[str, bool]:
        result = buffer.result()
        if not result.truncated:
            return result.text, False
        marker = f"[output truncated; {result.total_bytes} bytes produced]\n"
        return marker + result.text, True

    async def _wait(
        self,
        process_id: str,
        process: asyncio.subprocess.Process,
        *,
        responsibility_id: str | None,
    ) -> None:
        stdout_buffer = TailBuffer()
        stderr_buffer = TailBuffer()
        stdout_task = asyncio.create_task(self._drain(process.stdout, stdout_buffer))
        stderr_task = asyncio.create_task(self._drain(process.stderr, stderr_buffer))
        await process.wait()
        await asyncio.gather(stdout_task, stderr_task)

        stdout, stdout_truncated = self._stored_output(stdout_buffer)
        stderr, stderr_truncated = self._stored_output(stderr_buffer)
        status = "terminated" if process_id in self._terminating else "completed"
        self.db.execute(
            """
            UPDATE background_processes
            SET status = ?, returncode = ?, stdout = ?, stderr = ?, completed_at = ?
            WHERE id = ?
            """,
            (status, process.returncode, stdout, stderr, now_iso(), process_id),
        )
        await self.event_hub.publish(
            "process",
            status,
            {
                "process_id": process_id,
                "returncode": process.returncode,
                "responsibility_id": responsibility_id,
                "stdout_tail": stdout[-4000:],
                "stderr_tail": stderr[-4000:],
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
            },
            event_key=f"process:{process_id}:{status}",
        )
        self._tasks.pop(process_id, None)
        self._processes.pop(process_id, None)
        self._terminating.discard(process_id)

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
        running = [
            (process_id, process)
            for process_id, process in self._processes.items()
            if process.returncode is None
        ]
        for process_id, process in running:
            self._terminating.add(process_id)
            tree_terminated = await asyncio.to_thread(
                terminate_pid_tree,
                process.pid,
            )
            if not tree_terminated and process.returncode is None:
                process.kill()

        tasks = list(self._tasks.values())
        if not tasks:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=10,
            )
        except TimeoutError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
