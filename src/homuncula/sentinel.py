from __future__ import annotations

import fnmatch
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from .auth import redact_payload
from .db import Database


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Decision:
    action_id: str
    status: str
    reason: str


class Sentinel:
    INTERNAL_ALLOW = frozenset(
        {
            "memory.search",
            "memory.remember",
            "memory.revise",
            "runtime.schedule_wake",
            "runtime.subscribe_event",
            "responsibility.read",
            "finding.create",
            "plan.create",
            "plan.read",
            "plan.advance",
            "plan.block",
            "plan.resume",
            "plan.fail",
            "skill.list",
            "skill.read",
            "verification.read",
        }
    )

    READ_ALLOW = frozenset(
        {
            "filesystem.list",
            "filesystem.read",
            "browser.navigate",
            "browser.read",
            "windows.ui.read",
            "process.read",
        }
    )

    KNOWN_CAPABILITIES = INTERNAL_ALLOW | READ_ALLOW | frozenset(
        {
            "filesystem.write",
            "process.exec",
            "process.start",
            "browser.interact",
            "browser.upload",
            "windows.ui.interact",
            "network.http",
            "skill.install",
        }
    )

    def __init__(self, db: Database):
        self.db = db

    def request(
        self,
        *,
        capability: str,
        target: str,
        intent: str,
        args: dict,
        preview: str,
        risk: str,
        force_approval: bool = False,
    ) -> Decision:
        action_id = uuid.uuid4().hex
        created_at = now_iso()

        if capability not in self.KNOWN_CAPABILITIES:
            status = "denied"
            reason = "unknown capability"
        elif (
            force_approval
            and capability not in self.INTERNAL_ALLOW
            and capability not in self.READ_ALLOW
        ):
            status = "pending"
            reason = "observation mode requires explicit approval"
        elif capability in self.INTERNAL_ALLOW or capability in self.READ_ALLOW:
            status = "approved"
            reason = "default local policy"
        elif self._matches_grant(capability, target):
            status = "approved"
            reason = "matching explicit grant"
        else:
            status = "pending"
            reason = "user approval required"

        safe_args = redact_payload(args)
        self.db.execute(
            """
            INSERT INTO actions
            (id, capability, target, intent, args_json, preview, risk, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_id,
                capability,
                target,
                intent,
                self.db.json(safe_args),
                preview,
                risk,
                status,
                created_at,
            ),
        )
        return Decision(action_id, status, reason)

    def approve(self, action_id: str) -> dict:
        action = self.get(action_id)
        if action["status"] not in {"pending", "approved"}:
            raise ValueError(f"Action cannot be approved from {action['status']}")
        self.db.execute(
            "UPDATE actions SET status = 'approved', decided_at = ? WHERE id = ?",
            (now_iso(), action_id),
        )
        return self.get(action_id)

    def deny(self, action_id: str) -> dict:
        action = self.get(action_id)
        if action["status"] not in {"pending", "approved"}:
            raise ValueError(f"Action cannot be denied from {action['status']}")
        self.db.execute(
            "UPDATE actions SET status = 'denied', decided_at = ? WHERE id = ?",
            (now_iso(), action_id),
        )
        return self.get(action_id)

    def mark_executing(self, action_id: str) -> dict:
        action = self.get(action_id)
        if action["status"] != "approved":
            raise ValueError("Only approved actions may execute")
        self.db.execute(
            "UPDATE actions SET status = 'executing' WHERE id = ?",
            (action_id,),
        )
        return self.get(action_id)

    def complete(self, action_id: str, result: dict) -> dict:
        self.db.execute(
            """
            UPDATE actions
            SET status = 'completed', completed_at = ?, result_json = ?
            WHERE id = ?
            """,
            (
                now_iso(),
                self.db.json(redact_payload(result)),
                action_id,
            ),
        )
        return self.get(action_id)

    def fail(self, action_id: str, error: str) -> dict:
        self.db.execute(
            """
            UPDATE actions
            SET status = 'failed', completed_at = ?, error = ?
            WHERE id = ?
            """,
            (now_iso(), error[:4000], action_id),
        )
        return self.get(action_id)

    def get(self, action_id: str) -> dict:
        row = self.db.one("SELECT * FROM actions WHERE id = ?", (action_id,))
        if not row:
            raise KeyError(action_id)
        return row

    def pending(self) -> list[dict]:
        return self.db.all(
            "SELECT * FROM actions WHERE status = 'pending' ORDER BY created_at ASC"
        )

    def list_grants(self) -> list[dict]:
        return self.db.all(
            "SELECT * FROM grants ORDER BY created_at DESC"
        )

    def add_grant(
        self,
        capability: str,
        resource_pattern: str,
        *,
        expires_at: str | None = None,
    ) -> dict:
        if capability not in self.KNOWN_CAPABILITIES:
            raise ValueError(f"Unknown capability: {capability}")
        grant_id = uuid.uuid4().hex
        self.db.execute(
            """
            INSERT INTO grants
            (id, capability, resource_pattern, effect, expires_at, created_at)
            VALUES (?, ?, ?, 'allow', ?, ?)
            """,
            (grant_id, capability, resource_pattern, expires_at, now_iso()),
        )
        row = self.db.one("SELECT * FROM grants WHERE id = ?", (grant_id,))
        if not row:
            raise RuntimeError("Grant insert failed")
        return row

    def revoke_grant(self, grant_id: str) -> None:
        self.db.execute("DELETE FROM grants WHERE id = ?", (grant_id,))

    def _matches_grant(self, capability: str, target: str) -> bool:
        rows = self.db.all(
            "SELECT * FROM grants WHERE capability = ? AND effect = 'allow'",
            (capability,),
        )
        now = datetime.now(UTC)
        for row in rows:
            expires_at = row["expires_at"]
            if expires_at and datetime.fromisoformat(expires_at) <= now:
                continue
            if fnmatch.fnmatch(target, row["resource_pattern"]):
                return True
        return False

    @staticmethod
    def args(action: dict) -> dict:
        return json.loads(action["args_json"])
