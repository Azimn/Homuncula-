from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from homuncula.computer import WindowsHostComputer
from homuncula.db import Database
from homuncula.events import EventHub
from homuncula.process_control import sanitized_process_environment
from homuncula.processes import BackgroundProcessManager


async def _noop_wake(
    responsibility_id: str,
    reason: str,
    payload: dict,
) -> None:
    return None


def test_sanitized_process_environment_drops_parent_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOMUNCULA_TEST_SECRET", "should-not-cross-boundary")
    environment = sanitized_process_environment()

    assert "HOMUNCULA_TEST_SECRET" not in environment
    assert environment["HOMUNCULA_PROCESS_CONTAINED"] == "1"
    if "PATH" in os.environ:
        assert environment["PATH"] == os.environ["PATH"]


def test_foreground_process_has_bounded_output_and_minimal_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOMUNCULA_TEST_SECRET", "should-not-cross-boundary")
    computer = WindowsHostComputer(tmp_path)

    result = computer.run_process(
        [
            sys.executable,
            "-c",
            (
                "import os,sys;"
                "sys.stdout.write('x'*200000);"
                "sys.stdout.write('\\nENV='+os.environ.get('HOMUNCULA_TEST_SECRET','missing'))"
            ),
        ]
    )

    assert result["returncode"] == 0
    assert result["stdout"].endswith("\nENV=missing")
    assert "should-not-cross-boundary" not in result["stdout"]
    assert result["stdout_bytes"] > 100_000
    assert result["stdout_truncated"] is True
    assert len(result["stdout"].encode("utf-8")) <= 100_000
    assert result["environment_policy"] == "minimal-inherited"


def test_foreground_timeout_returns_explicit_containment_result(tmp_path: Path) -> None:
    computer = WindowsHostComputer(tmp_path)

    result = computer.run_process(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ],
        timeout=1,
    )

    assert result["timed_out"] is True
    assert isinstance(result["returncode"], int)
    assert result["duration_seconds"] < 10


@pytest.mark.asyncio
async def test_background_output_is_bounded_and_secret_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOMUNCULA_TEST_SECRET", "should-not-cross-boundary")
    db = Database(tmp_path / "background.sqlite3")
    db.initialize()
    manager = BackgroundProcessManager(
        db,
        tmp_path,
        EventHub(db, _noop_wake),
    )

    started = await manager.start(
        [
            sys.executable,
            "-c",
            (
                "import os,sys;"
                "sys.stdout.write('y'*200000);"
                "sys.stdout.write('\\nENV='+os.environ.get('HOMUNCULA_TEST_SECRET','missing'))"
            ),
        ]
    )
    task = manager._tasks[started["process_id"]]
    await task

    row = manager.get(started["process_id"])
    assert row["status"] == "completed"
    assert "should-not-cross-boundary" not in (row["stdout"] or "")
    assert row["stdout"].endswith("\nENV=missing")
    assert row["stdout"].startswith("[output truncated;")
    assert len(row["stdout"].encode("utf-8")) < 101_000

    await manager.shutdown()


@pytest.mark.asyncio
async def test_background_shutdown_terminates_running_process_tree(tmp_path: Path) -> None:
    db = Database(tmp_path / "shutdown.sqlite3")
    db.initialize()
    manager = BackgroundProcessManager(
        db,
        tmp_path,
        EventHub(db, _noop_wake),
    )

    started = await manager.start(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ]
    )
    process = manager._processes[started["process_id"]]
    assert process.returncode is None

    await manager.shutdown()

    assert process.returncode is not None
    row = manager.get(started["process_id"])
    assert row["status"] == "terminated"
