from datetime import UTC, datetime
from pathlib import Path

import pytest

from homuncula.computer import WindowsHostComputer, WorkspaceViolation
from homuncula.db import Database
from homuncula.runtime import WakeScheduler
from homuncula.sentinel import Sentinel


async def _noop(_: str, __: str) -> None:
    return None


def test_unknown_capability_is_denied(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.sqlite3")
    db.initialize()
    sentinel = Sentinel(db)

    decision = sentinel.request(
        capability="danger.unknown",
        target="anything",
        intent="test",
        args={},
        preview="unknown action",
        risk="unknown",
    )

    assert decision.status == "denied"


def test_write_requires_approval_until_granted(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.sqlite3")
    db.initialize()
    sentinel = Sentinel(db)

    first = sentinel.request(
        capability="filesystem.write",
        target="src/app.py",
        intent="test",
        args={"path": "src/app.py", "content": "x"},
        preview="write app",
        risk="write",
    )
    assert first.status == "pending"

    sentinel.add_grant("filesystem.write", "src/*")

    second = sentinel.request(
        capability="filesystem.write",
        target="src/app.py",
        intent="test",
        args={"path": "src/app.py", "content": "y"},
        preview="write app",
        risk="write",
    )
    assert second.status == "approved"


def test_workspace_read_write_and_escape(tmp_path: Path) -> None:
    computer = WindowsHostComputer(tmp_path)
    result = computer.write_text("notes/test.txt", "hello")
    assert result["bytes"] == 5
    assert computer.read_text("notes/test.txt")["content"] == "hello"

    with pytest.raises(WorkspaceViolation):
        computer.read_text("../outside.txt")


def test_due_wake_claim_is_transactional(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.sqlite3")
    db.initialize()

    stamp = datetime.now(UTC).isoformat()
    db.execute(
        "INSERT INTO threads (id, title, created_at, updated_at) VALUES ('t', 't', ?, ?)",
        (stamp, stamp),
    )
    db.execute(
        """
        INSERT INTO responsibilities
        (id, thread_id, title, objective, status, proactive_mode, created_at, updated_at)
        VALUES ('r', 't', 'r', 'o', 'active', 'observe', ?, ?)
        """,
        (stamp, stamp),
    )
    db.execute(
        """
        INSERT INTO wakes
        (id, responsibility_id, run_at, reason, payload_json, status, created_at)
        VALUES ('w', 'r', ?, 'test', '{}', 'scheduled', ?)
        """,
        (stamp, stamp),
    )

    scheduler = WakeScheduler(db, _noop)
    claimed = scheduler._claim_due()
    assert claimed is not None
    assert claimed["id"] == "w"
    assert scheduler._claim_due() is None
