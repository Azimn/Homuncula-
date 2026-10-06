from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from homuncula.browser import BrowserProvider
from homuncula.db import Database
from homuncula.git_inspector import GitInspector
from homuncula.guardrails import ToolLoopGuard
from homuncula.verification import VerificationStore, classify_command


@pytest.mark.asyncio
async def test_browser_rejects_non_http_navigation_before_launch(tmp_path: Path) -> None:
    browser = BrowserProvider(tmp_path / "profile", channel="chromium", headless=True)
    with pytest.raises(ValueError, match="http"):
        await browser.navigate("file:///etc/passwd")
    with pytest.raises(ValueError, match="Credentials"):
        await browser.navigate("https://user:password@example.com/")


def test_tool_loop_guard_blocks_no_progress_and_duplicate_mutation() -> None:
    guard = ToolLoopGuard(no_progress_limit=3)
    args = {"path": "README.md"}

    for _ in range(3):
        assert guard.before("read_file", args).allowed
        guard.after("read_file", args, {"content": "same"})

    blocked = guard.before("read_file", args)
    assert not blocked.allowed
    assert blocked.code == "identical_no_progress"

    write_args = {"path": "x.txt", "content": "hello", "intent": "test"}
    assert guard.before("write_file", write_args).allowed
    guard.after(
        "write_file",
        write_args,
        {"status": "completed", "result": {"bytes": 5}},
    )
    duplicate = guard.before("write_file", write_args)
    assert not duplicate.allowed
    assert duplicate.code == "duplicate_mutation"


def test_verification_ledger_classifies_and_persists(tmp_path: Path) -> None:
    db = Database(tmp_path / "verify.sqlite3")
    db.initialize()
    store = VerificationStore(db)

    assert classify_command(["python", "-m", "pytest", "-q"]) == "test"
    assert classify_command(["python", "-m", "ruff", "check", "."]) == "lint"
    assert classify_command(["npm", "run", "typecheck"]) == "typecheck"
    assert classify_command(["npm", "run", "build"]) == "build"
    assert classify_command(["python", "script.py"]) is None

    event = store.record_process(
        argv=["python", "-m", "pytest", "-q"],
        cwd=".",
        returncode=0,
        stdout="12 passed",
        stderr="",
        responsibility_id=None,
        action_id="a1",
    )
    assert event is not None
    assert event["status"] == "passed"
    assert store.summary()["passing_kinds"] == ["test"]


def test_git_inspector_is_read_only_and_workspace_scoped(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "note.txt").write_text("hello\n", encoding="utf-8")

    inspector = GitInspector(tmp_path)
    status = inspector.status()
    assert status["branch"]
    assert any(item["path"] == "note.txt" for item in status["files"])

    with pytest.raises(PermissionError):
        inspector.diff("../outside.txt")
