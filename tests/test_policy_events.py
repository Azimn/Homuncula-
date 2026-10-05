from __future__ import annotations

from pathlib import Path

import pytest

from homuncula.db import Database
from homuncula.events import EventHub
from homuncula.sentinel import Sentinel


def test_observation_cannot_consume_mutation_grant(tmp_path: Path) -> None:
    db = Database(tmp_path / "policy.sqlite3")
    db.initialize()
    sentinel = Sentinel(db)
    sentinel.add_grant("filesystem.write", "src/*")

    normal = sentinel.request(
        capability="filesystem.write",
        target="src/app.py",
        intent="normal work",
        args={"path": "src/app.py", "content": "x"},
        preview="write",
        risk="write",
    )
    assert normal.status == "approved"

    observed = sentinel.request(
        capability="filesystem.write",
        target="src/app.py",
        intent="proactive observation",
        args={"path": "src/app.py", "content": "y"},
        preview="write",
        risk="write",
        force_approval=True,
    )
    assert observed.status == "pending"

    read = sentinel.request(
        capability="filesystem.read",
        target="src/app.py",
        intent="inspect",
        args={"path": "src/app.py"},
        preview="read",
        risk="read",
        force_approval=True,
    )
    assert read.status == "approved"


@pytest.mark.asyncio
async def test_event_subscription_is_deduplicated(tmp_path: Path) -> None:
    db = Database(tmp_path / "events.sqlite3")
    db.initialize()
    stamp = "2026-10-05T00:00:00+00:00"
    db.execute(
        "INSERT INTO threads (id, title, created_at, updated_at) VALUES ('t', 't', ?, ?)",
        (stamp, stamp),
    )
    db.execute(
        """
        INSERT INTO responsibilities
        (id, thread_id, title, objective, status, proactive_mode, created_at, updated_at)
        VALUES ('r', 't', 'Watch code', 'Notice Python changes', 'active', 'observe', ?, ?)
        """,
        (stamp, stamp),
    )

    wakes: list[tuple[str, str, dict]] = []

    async def wake(responsibility_id: str, reason: str, payload: dict) -> None:
        wakes.append((responsibility_id, reason, payload))

    hub = EventHub(db, wake)
    hub.subscribe("r", "filesystem", "*.py")

    first = await hub.publish(
        "filesystem",
        "changed",
        {"path": "src/app.py", "change": "modified"},
        event_key="same-event",
    )
    second = await hub.publish(
        "filesystem",
        "changed",
        {"path": "src/app.py", "change": "modified"},
        event_key="same-event",
    )

    assert first is True
    assert second is False
    assert len(wakes) == 1
    assert wakes[0][0] == "r"
