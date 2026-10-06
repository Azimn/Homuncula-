from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


class GitUnavailable(RuntimeError):
    pass


class GitInspector:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()

    def _run(
        self,
        args: list[str],
        *,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.workspace), *args],
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise GitUnavailable(str(exc)) from exc
        if result.returncode != 0:
            raise GitUnavailable((result.stderr or result.stdout).strip())
        return result

    def _repository_root(self) -> Path:
        root = Path(self._run(["rev-parse", "--show-toplevel"]).stdout.strip()).resolve()
        try:
            self.workspace.relative_to(root)
        except ValueError as exc:
            raise GitUnavailable("Workspace is outside the resolved Git root") from exc
        return root

    def status(self, *, limit: int = 250) -> dict[str, Any]:
        self._repository_root()
        branch = self._run(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        raw = self._run(
            ["status", "--porcelain=v1", "--untracked-files=normal", "--", "."]
        ).stdout

        files = []
        for line in raw.splitlines()[: max(1, min(limit, 1000))]:
            if len(line) < 4:
                continue
            files.append(
                {
                    "index": line[0],
                    "worktree": line[1],
                    "path": line[3:],
                }
            )

        stat = self._run(["diff", "--stat", "--", "."]).stdout[-20_000:]
        staged_stat = self._run(["diff", "--cached", "--stat", "--", "."]).stdout[-20_000:]
        return {
            "root": str(self.workspace),
            "branch": branch,
            "files": files,
            "working_stat": stat,
            "staged_stat": staged_stat,
        }

    def diff(
        self,
        relative: str,
        *,
        staged: bool = False,
        max_chars: int = 80_000,
    ) -> dict[str, Any]:
        self._repository_root()
        candidate = (self.workspace / relative).resolve()
        try:
            safe_relative = candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise PermissionError(f"Git path escapes workspace: {relative}") from exc

        args = ["diff"]
        if staged:
            args.append("--cached")
        args.extend(["--", safe_relative.as_posix()])
        content = self._run(args).stdout
        truncated = len(content) > max_chars
        return {
            "path": safe_relative.as_posix(),
            "staged": staged,
            "diff": content[:max_chars],
            "truncated": truncated,
        }
