from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .process_control import (
    TailBuffer,
    drain_stream,
    isolation_popen_kwargs,
    sanitized_process_environment,
    terminate_process_tree,
)


class WorkspaceViolation(PermissionError):
    pass


class WindowsHostComputer:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()

    def _resolve(self, relative: str | Path) -> Path:
        candidate = (self.workspace / relative).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise WorkspaceViolation(f"Path escapes workspace: {relative}") from exc
        return candidate

    def resolve_path(self, relative: str | Path) -> Path:
        return self._resolve(relative)

    def list_files(self, relative: str = ".", *, limit: int = 200) -> dict[str, Any]:
        root = self._resolve(relative)
        if not root.exists():
            raise FileNotFoundError(root)
        if not root.is_dir():
            raise NotADirectoryError(root)

        items = []
        for path in sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            items.append(
                {
                    "name": path.name,
                    "path": str(path.relative_to(self.workspace)),
                    "kind": "directory" if path.is_dir() else "file",
                    "size": path.stat().st_size if path.is_file() else None,
                }
            )
            if len(items) >= max(1, min(limit, 1000)):
                break
        return {"workspace": str(self.workspace), "items": items}

    def read_text(self, relative: str, *, max_chars: int = 200_000) -> dict[str, Any]:
        path = self._resolve(relative)
        text = path.read_text(encoding="utf-8")
        truncated = len(text) > max_chars
        return {
            "path": str(path.relative_to(self.workspace)),
            "content": text[:max_chars],
            "truncated": truncated,
        }

    def write_text(self, relative: str, content: str) -> dict[str, Any]:
        path = self._resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {
            "path": str(path.relative_to(self.workspace)),
            "bytes": len(content.encode("utf-8")),
        }

    def run_process(
        self,
        argv: list[str],
        *,
        cwd: str = ".",
        timeout: int = 120,
    ) -> dict[str, Any]:
        if not argv or not all(isinstance(part, str) and part for part in argv):
            raise ValueError("argv must contain at least one non-empty string")

        working_dir = self._resolve(cwd)
        bounded_timeout = max(1, min(timeout, 1800))
        stdout_buffer = TailBuffer()
        stderr_buffer = TailBuffer()
        started = time.monotonic()

        process = subprocess.Popen(
            argv,
            cwd=working_dir,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=sanitized_process_environment(),
            **isolation_popen_kwargs(),
        )
        stdout_thread = threading.Thread(
            target=drain_stream,
            args=(process.stdout, stdout_buffer),
            name=f"homuncula-stdout-{process.pid}",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=drain_stream,
            args=(process.stderr, stderr_buffer),
            name=f"homuncula-stderr-{process.pid}",
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        timed_out = False
        try:
            returncode = process.wait(timeout=bounded_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_process_tree(process)
            try:
                returncode = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait(timeout=5)

        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        stdout = stdout_buffer.result()
        stderr = stderr_buffer.result()

        return {
            "argv": argv,
            "cwd": str(working_dir.relative_to(self.workspace)),
            "returncode": returncode,
            "stdout": stdout.text,
            "stderr": stderr.text,
            "stdout_bytes": stdout.total_bytes,
            "stderr_bytes": stderr.total_bytes,
            "stdout_truncated": stdout.truncated,
            "stderr_truncated": stderr.truncated,
            "timed_out": timed_out,
            "duration_seconds": round(time.monotonic() - started, 3),
            "environment_policy": "minimal-inherited",
        }
