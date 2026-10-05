from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


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
        completed = subprocess.run(
            argv,
            cwd=working_dir,
            shell=False,
            capture_output=True,
            text=True,
            timeout=max(1, min(timeout, 1800)),
            check=False,
        )
        return {
            "argv": argv,
            "cwd": str(working_dir.relative_to(self.workspace)),
            "returncode": completed.returncode,
            "stdout": completed.stdout[-100_000:],
            "stderr": completed.stderr[-100_000:],
        }
