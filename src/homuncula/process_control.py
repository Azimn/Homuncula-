from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import BinaryIO, Mapping


DEFAULT_CAPTURE_BYTES = 100_000

PROCESS_ENV_ALLOWLIST = frozenset(
    {
        "APPDATA",
        "COLORTERM",
        "COMSPEC",
        "CONDA_PREFIX",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOCALAPPDATA",
        "NO_COLOR",
        "NUMBER_OF_PROCESSORS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "SYSTEMROOT",
        "TEMP",
        "TERM",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "VIRTUAL_ENV",
        "WINDIR",
    }
)


@dataclass(frozen=True)
class CaptureResult:
    text: str
    total_bytes: int
    truncated: bool


class TailBuffer:
    """Thread-safe bounded byte tail with total-volume accounting."""

    def __init__(self, max_bytes: int = DEFAULT_CAPTURE_BYTES):
        self.max_bytes = max(1, int(max_bytes))
        self._data = bytearray()
        self._total_bytes = 0
        self._lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            self._total_bytes += len(chunk)
            if len(chunk) >= self.max_bytes:
                self._data = bytearray(chunk[-self.max_bytes :])
                return
            overflow = len(self._data) + len(chunk) - self.max_bytes
            if overflow > 0:
                del self._data[:overflow]
            self._data.extend(chunk)

    def result(self) -> CaptureResult:
        with self._lock:
            data = bytes(self._data)
            total = self._total_bytes
        return CaptureResult(
            text=data.decode("utf-8", errors="replace"),
            total_bytes=total,
            truncated=total > self.max_bytes,
        )


def drain_stream(stream: BinaryIO | None, buffer: TailBuffer) -> None:
    if stream is None:
        return
    try:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            buffer.append(chunk)
    finally:
        stream.close()


def sanitized_process_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a minimal inherited environment without arbitrary parent secrets."""

    source = source or os.environ
    result: dict[str, str] = {}
    for key, value in source.items():
        if key.upper() in PROCESS_ENV_ALLOWLIST:
            result[key] = value
    result["HOMUNCULA_PROCESS_CONTAINED"] = "1"
    return result


def isolation_popen_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
        }
    return {"start_new_session": True}


def terminate_pid_tree(
    pid: int,
    *,
    grace_seconds: float = 1.0,
) -> bool:
    """Best-effort termination for an isolated process group/tree."""

    if os.name == "nt":
        try:
            completed = subprocess.run(
                [
                    "taskkill",
                    "/PID",
                    str(pid),
                    "/T",
                    "/F",
                ],
                shell=False,
                capture_output=True,
                timeout=max(1.0, grace_seconds + 1.0),
                check=False,
                env=sanitized_process_environment(),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0

    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    time.sleep(max(0.0, grace_seconds))
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return True


def terminate_process_tree(
    process: subprocess.Popen[bytes],
    *,
    grace_seconds: float = 1.0,
) -> None:
    """Terminate a foreground command and its isolated descendants."""

    if process.poll() is not None:
        return

    tree_terminated = terminate_pid_tree(
        process.pid,
        grace_seconds=grace_seconds,
    )
    if not tree_terminated and process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
