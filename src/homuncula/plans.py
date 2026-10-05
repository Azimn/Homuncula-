from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .db import Database


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class PlanError(RuntimeError):
    pass


class PlanStore:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        responsibility_id: str,
        *,
        title: str,
        goal: str,
        steps: list[dict[str, str] | str],
    ) -> dict[str, Any]:
        if not title.strip() or not goal.strip() or not steps:
            raise ValueError("A plan requires a title, goal, and at least one step")

        responsibility = self.db.one(
            "SELECT id FROM responsibilities WHERE id = ?",
            (responsibility_id,),
        )
        if not responsibility:
            raise KeyError(responsibility_id)

        active = self.active(responsibility_id)
        if active:
            raise PlanError(
                f"Responsibility already has an active plan: {active['id']}"
            )

        plan_id = "plan_" + uuid.uuid4().hex
        stamp = now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO plans
                (id, responsibility_id, title, goal, status, current_step, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'active', 1, ?, ?)
                """,
                (
                    plan_id,
                    responsibility_id,
                    title.strip(),
                    goal.strip(),
                    stamp,
                    stamp,
                ),
            )
            for position, raw in enumerate(steps, start=1):
                if isinstance(raw, str):
                    step_title = raw.strip()
                    detail = raw.strip()
                else:
                    step_title = str(raw.get("title") or raw.get("detail") or "").strip()
                    detail = str(raw.get("detail") or step_title).strip()
                if not step_title:
                    raise ValueError(f"Plan step {position} is empty")
                conn.execute(
                    """
                    INSERT INTO plan_steps
                    (id, plan_id, position, title, detail, status, started_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "step_" + uuid.uuid4().hex,
                        plan_id,
                        position,
                        step_title,
                        detail,
                        "active" if position == 1 else "pending",
                        stamp if position == 1 else None,
                    ),
                )
        return self.get(plan_id)

    def active(self, responsibility_id: str) -> dict[str, Any] | None:
        row = self.db.one(
            """
            SELECT id FROM plans
            WHERE responsibility_id = ? AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (responsibility_id,),
        )
        return self.get(row["id"]) if row else None

    def get(self, plan_id: str) -> dict[str, Any]:
        plan = self.db.one("SELECT * FROM plans WHERE id = ?", (plan_id,))
        if not plan:
            raise KeyError(plan_id)
        plan["steps"] = self.db.all(
            """
            SELECT id, position, title, detail, status, summary, started_at, completed_at
            FROM plan_steps
            WHERE plan_id = ?
            ORDER BY position ASC
            """,
            (plan_id,),
        )
        return plan

    def list(
        self,
        *,
        responsibility_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if responsibility_id:
            rows = self.db.all(
                """
                SELECT id FROM plans
                WHERE responsibility_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (responsibility_id, max(1, min(limit, 500))),
            )
        else:
            rows = self.db.all(
                "SELECT id FROM plans ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            )
        return [self.get(row["id"]) for row in rows]

    def advance(
        self,
        plan_id: str,
        *,
        summary: str,
    ) -> dict[str, Any]:
        plan = self.get(plan_id)
        if plan["status"] != "active":
            raise PlanError("Only an active plan can advance")
        current = plan["current_step"]
        if current is None:
            raise PlanError("Active plan has no current step")

        steps = plan["steps"]
        if current < 1 or current > len(steps):
            raise PlanError("Plan current_step is outside its step range")

        current_step = steps[current - 1]
        if current_step["status"] != "active":
            raise PlanError("Current plan step is not active")

        stamp = now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE plan_steps
                SET status = 'complete', summary = ?, completed_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (summary.strip(), stamp, current_step["id"]),
            )

            next_position = current + 1
            if next_position <= len(steps):
                next_step = steps[next_position - 1]
                conn.execute(
                    """
                    UPDATE plan_steps
                    SET status = 'active', started_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (stamp, next_step["id"]),
                )
                conn.execute(
                    """
                    UPDATE plans
                    SET current_step = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (next_position, stamp, plan_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE plans
                    SET status = 'complete', current_step = NULL,
                        updated_at = ?, completed_at = ?
                    WHERE id = ?
                    """,
                    (stamp, stamp, plan_id),
                )

        return self.get(plan_id)

    def block_step(
        self,
        plan_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        plan = self.get(plan_id)
        if plan["status"] != "active" or plan["current_step"] is None:
            raise PlanError("Plan has no active step to block")
        step = plan["steps"][plan["current_step"] - 1]
        stamp = now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE plan_steps
                SET status = 'blocked', summary = ?
                WHERE id = ?
                """,
                (reason.strip(), step["id"]),
            )
            conn.execute(
                "UPDATE plans SET status = 'blocked', updated_at = ? WHERE id = ?",
                (stamp, plan_id),
            )
        return self.get(plan_id)

    def resume(self, plan_id: str) -> dict[str, Any]:
        plan = self.get(plan_id)
        if plan["status"] != "blocked" or plan["current_step"] is None:
            raise PlanError("Only a blocked plan can resume")
        step = plan["steps"][plan["current_step"] - 1]
        stamp = now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE plan_steps
                SET status = 'active', summary = NULL,
                    started_at = COALESCE(started_at, ?)
                WHERE id = ?
                """,
                (stamp, step["id"]),
            )
            conn.execute(
                "UPDATE plans SET status = 'active', updated_at = ? WHERE id = ?",
                (stamp, plan_id),
            )
        return self.get(plan_id)

    def fail(self, plan_id: str, *, reason: str) -> dict[str, Any]:
        plan = self.get(plan_id)
        if plan["status"] in {"complete", "failed"}:
            raise PlanError("Plan is already terminal")
        stamp = now_iso()
        with self.db.transaction() as conn:
            if plan["current_step"] is not None:
                step = plan["steps"][plan["current_step"] - 1]
                conn.execute(
                    """
                    UPDATE plan_steps
                    SET status = 'failed', summary = ?, completed_at = ?
                    WHERE id = ?
                    """,
                    (reason.strip(), stamp, step["id"]),
                )
            conn.execute(
                """
                UPDATE plans
                SET status = 'failed', current_step = NULL,
                    updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (stamp, stamp, plan_id),
            )
        return self.get(plan_id)
