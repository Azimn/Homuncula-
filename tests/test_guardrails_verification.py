from __future__ import annotations

from pathlib import Path

from homuncula.auth import REDACTED, redact_text
from homuncula.db import Database
from homuncula.guardrails import ToolLoopGuard
from homuncula.verification import VerificationStore, classify_command


def test_tool_loop_guard_blocks_repetition_and_identical_results() -> None:
    guard = ToolLoopGuard(
        max_total_calls=20,
        max_same_tool=10,
        max_same_call=2,
        max_same_result=2,
    )
    args = {"path": "README.md"}

    assert guard.before("read_file", args).allowed
    assert guard.after("read_file", args, {"content": "same"}).allowed
    assert guard.before("read_file", args).allowed
    repeated = guard.after("read_file", args, {"content": "same"})
    assert repeated.allowed is False
    assert repeated.code == "same_result_cap"

    blocked = guard.before("read_file", args)
    assert blocked.allowed is False
    assert blocked.code == "same_call_cap"


def test_verification_evidence_records_scope_and_redacts_output(tmp_path: Path) -> None:
    db = Database(tmp_path / "verify.sqlite3")
    db.initialize()
    store = VerificationStore(db)

    record = store.record_process(
        action_id="action-1",
        responsibility_id="resp-1",
        result={
            "argv": ["python", "-m", "pytest", "-q"],
            "cwd": ".",
            "returncode": 0,
            "stdout": "12 passed\nTOKEN=super-secret-value",
            "stderr": "Authorization: Bearer abc.def.ghi",
        },
    )

    assert record["kind"] == "test"
    assert record["status"] == "passed"
    assert "super-secret-value" not in record["stdout_summary"]
    assert "abc.def.ghi" not in record["stderr_summary"]
    assert REDACTED in record["stdout_summary"]
    assert REDACTED in record["stderr_summary"]

    summary = store.summary("resp-1")
    assert summary["latest_by_kind"]["test"]["id"] == record["id"]
    assert summary["has_failed"] is False


def test_command_classification_and_text_redaction() -> None:
    assert classify_command(["npm", "run", "typecheck"]) == "quality"
    assert classify_command(["npm", "run", "build"]) == "build"
    assert classify_command(["git", "status", "--short"]) == "inspection"
    assert redact_text("api_key=abc123 password:letmein").count(REDACTED) == 2


def test_verification_marks_timeouts_and_truncated_capture(tmp_path: Path) -> None:
    db = Database(tmp_path / "verify-timeout.sqlite3")
    db.initialize()
    store = VerificationStore(db)

    record = store.record_process(
        action_id="action-timeout",
        responsibility_id="resp-timeout",
        result={
            "argv": ["python", "-c", "import time; time.sleep(30)"],
            "cwd": ".",
            "returncode": -1,
            "stdout": "x" * 10000,
            "stderr": "",
            "stdout_truncated": True,
            "stderr_truncated": False,
            "timed_out": True,
        },
    )

    assert record["status"] == "timed_out"
    assert record["stdout_summary"].startswith("[captured output truncated]")
    assert len(record["stdout_summary"]) <= 4000

    summary = store.summary("resp-timeout")
    assert summary["has_failed"] is True
