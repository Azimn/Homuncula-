from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from watchfiles import Change, awatch

from .db import Database

WakeCallback = Callable[[str, str, dict[str, Any]], Awaitable[None]]

def now_iso() -> str:
    return datetime.now(UTC).isoformat()

class EventHub:
    def __init__(self, db: Database, wake_callback: WakeCallback):
        self.db = db
        self.wake_callback = wake_callback

    def subscribe(
        self,
        responsibility_id: str,
        source: str,
        pattern: str = "*",
    ) -> dict[str, Any]:
        subscription_id = uuid.uuid4().hex
        self.db.execute(
            """
            INSERT INTO event_subscriptions
            (id, responsibility_id, source, pattern, enabled, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (
                subscription_id,
                responsibility_id,
                source,
                pattern or "*",
                now_iso(),
            ),
        )
        row = self.db.one(
            "SELECT * FROM event_subscriptions WHERE id = ?",
            (subscription_id,),
        )
        if not row:
            raise RuntimeError("Event subscription insert failed")
        return row

    def list_subscriptions(
        self,
        responsibility_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if responsibility_id:
            return self.db.all(
                """
                SELECT * FROM event_subscriptions
                WHERE responsibility_id = ?
                ORDER BY created_at ASC
                """,
                (responsibility_id,),
            )
        return self.db.all(
            "SELECT * FROM event_subscriptions ORDER BY created_at ASC"
        )

    def disable(self, subscription_id: str) -> None:
        self.db.execute(
            "UPDATE event_subscriptions SET enabled = 0 WHERE id = ?",
            (subscription_id,),
        )

    async def publish(
        self,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_key: str | None = None,
    ) -> bool:
        key = event_key or self._event_key(source, event_type, payload)
        try:
            self.db.execute(
                """
                INSERT INTO event_receipts
                (event_key, source, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key, source, event_type, self.db.json(payload), now_iso()),
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                return False
            raise

        subscriptions = self.db.all(
            """
            SELECT * FROM event_subscriptions
            WHERE source = ? AND enabled = 1
            """,
            (source,),
        )
        match_value = str(
            payload.get("path")
            or payload.get("process_id")
            or payload.get("name")
            or event_type
        )
        for subscription in subscriptions:
            if fnmatch.fnmatch(match_value, subscription["pattern"]):
                reason = f"{source}.{event_type}: {match_value}"
                await self.wake_callback(
                    subscription["responsibility_id"],
                    reason,
                    {
                        "event_source": source,
                        "event_type": event_type,
                        "event_payload": payload,
                        "observation": True,
                    },
                )
        return True

    @staticmethod
    def _event_key(
        source: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> str:
        material = json.dumps(
            [source, event_type, payload],
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

class WorkspaceEventSource:
    def __init__(self, workspace: Path, hub: EventHub):
        self.workspace = Path(workspace).resolve()
        self.hub = hub
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        async for changes in awatch(self.workspace, stop_event=self._stop):
            for change, raw_path in changes:
                path = Path(raw_path)
                relative = self._relative(path)
                if relative is None or self._ignored(relative):
                    continue
                source = "git" if ".git" in relative.parts else "filesystem"
                event_type = self._event_type(change)
                stat = None
                try:
                    stat = path.stat()
                except OSError:
                    pass
                payload = {
                    "path": relative.as_posix(),
                    "change": event_type,
                    "size": stat.st_size if stat else None,
                    "mtime_ns": stat.st_mtime_ns if stat else None,
                }
                key_material = {
                    "path": payload["path"],
                    "change": payload["change"],
                    "size": payload["size"],
                    "mtime_ns": payload["mtime_ns"],
                }
                await self.hub.publish(
                    source,
                    "changed",
                    payload,
                    event_key=EventHub._event_key(source, "changed", key_material),
                )

    def _relative(self, path: Path) -> Path | None:
        try:
            return path.resolve().relative_to(self.workspace)
        except (OSError, ValueError):
            return None

    @staticmethod
    def _ignored(relative: Path) -> bool:
        ignored = {".venv", "node_modules", "__pycache__", ".homuncula"}
        return any(part in ignored for part in relative.parts)

    @staticmethod
    def _event_type(change: Change) -> str:
        mapping = {
            Change.added: "added",
            Change.modified: "modified",
            Change.deleted: "deleted",
        }
        return mapping.get(change, "changed")
