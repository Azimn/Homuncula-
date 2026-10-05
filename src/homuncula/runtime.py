from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from .computer import WindowsHostComputer
from .db import Database
from .memory import MemoryStore
from .provider import OllamaProvider
from .sentinel import Sentinel


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


SYSTEM_PROMPT = """
You are Homuncula, a persistent local agent running on the user's computer.

Your job is to complete work through durable responsibilities, memory, tools, and explicit
capability boundaries. You may use read-only workspace tools directly. Mutating filesystem
operations and process execution may require user approval through Sentinel.

Do not claim an action occurred unless a tool result confirms it. Do not treat a pending
approval as execution. When working inside a responsibility, schedule a future wake only when
there is a real future dependency or useful continuation point. Do not create polling loops.

Use memory for durable facts or decisions that are likely to matter later. Keep operational
activity concise. Never expose hidden chain-of-thought. Report conclusions, evidence, tool
results, pending approvals, and next dependencies instead.
""".strip()


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files inside the configured local workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "."},
                    "limit": {"type": "integer", "default": 200},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file inside the configured workspace.",
            "parameters": {
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Propose writing a UTF-8 text file inside the workspace.",
            "parameters": {
                "type": "object",
                "required": ["path", "content", "intent"],
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "intent": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_process",
            "description": "Propose executing a process with argv and shell disabled.",
            "parameters": {
                "type": "object",
                "required": ["argv", "intent"],
                "properties": {
                    "argv": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string", "default": "."},
                    "timeout": {"type": "integer", "default": 120},
                    "intent": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Search durable local memory.",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "scope": {"type": "string", "default": "global"},
                    "limit": {"type": "integer", "default": 8},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Store a durable fact, preference, decision, or commitment.",
            "parameters": {
                "type": "object",
                "required": ["content"],
                "properties": {
                    "content": {"type": "string"},
                    "scope": {"type": "string", "default": "global"},
                    "kind": {"type": "string", "default": "fact"},
                    "source": {"type": "string", "default": "agent"},
                    "confidence": {"type": "number", "default": 1.0},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_wake",
            "description": "Schedule this responsibility to resume after a real future dependency.",
            "parameters": {
                "type": "object",
                "required": ["delay_seconds", "reason"],
                "properties": {
                    "delay_seconds": {"type": "integer", "minimum": 1},
                    "reason": {"type": "string"},
                },
            },
        },
    },
]


class HomunculaRuntime:
    def __init__(
        self,
        db: Database,
        computer: WindowsHostComputer,
        memory: MemoryStore,
        sentinel: Sentinel,
        provider: OllamaProvider,
    ):
        self.db = db
        self.computer = computer
        self.memory = memory
        self.sentinel = sentinel
        self.provider = provider

    def activity(
        self,
        kind: str,
        message: str,
        *,
        responsibility_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO activities
            (id, responsibility_id, kind, message, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                responsibility_id,
                kind,
                message,
                self.db.json(metadata or {}),
                now_iso(),
            ),
        )

    def create_thread(self, title: str) -> dict[str, Any]:
        thread_id = uuid.uuid4().hex
        stamp = now_iso()
        self.db.execute(
            "INSERT INTO threads (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (thread_id, title, stamp, stamp),
        )
        row = self.db.one("SELECT * FROM threads WHERE id = ?", (thread_id,))
        if not row:
            raise RuntimeError("Thread insert failed")
        return row

    def create_responsibility(
        self,
        title: str,
        objective: str,
        *,
        proactive_mode: str = "observe",
        start_now: bool = True,
    ) -> dict[str, Any]:
        thread = self.create_thread(title)
        responsibility_id = uuid.uuid4().hex
        stamp = now_iso()
        self.db.execute(
            """
            INSERT INTO responsibilities
            (id, thread_id, title, objective, status, proactive_mode, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                responsibility_id,
                thread["id"],
                title,
                objective,
                proactive_mode,
                stamp,
                stamp,
            ),
        )
        self.activity(
            "responsibility.created",
            f"Created responsibility: {title}",
            responsibility_id=responsibility_id,
        )
        if start_now:
            self.schedule_wake(responsibility_id, 1, "initial responsibility start")
        return self.get_responsibility(responsibility_id)

    def get_responsibility(self, responsibility_id: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM responsibilities WHERE id = ?", (responsibility_id,)
        )
        if not row:
            raise KeyError(responsibility_id)
        return row

    def list_responsibilities(self) -> list[dict[str, Any]]:
        return self.db.all(
            "SELECT * FROM responsibilities ORDER BY updated_at DESC"
        )

    def schedule_wake(
        self,
        responsibility_id: str,
        delay_seconds: int,
        reason: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.get_responsibility(responsibility_id)
        wake_id = uuid.uuid4().hex
        run_at = datetime.now(UTC) + timedelta(seconds=max(1, delay_seconds))
        self.db.execute(
            """
            INSERT INTO wakes
            (id, responsibility_id, run_at, reason, payload_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'scheduled', ?)
            """,
            (
                wake_id,
                responsibility_id,
                run_at.isoformat(),
                reason,
                self.db.json(payload or {}),
                now_iso(),
            ),
        )
        self.activity(
            "wake.scheduled",
            f"Scheduled wake: {reason}",
            responsibility_id=responsibility_id,
            metadata={"wake_id": wake_id, "run_at": run_at.isoformat()},
        )
        row = self.db.one("SELECT * FROM wakes WHERE id = ?", (wake_id,))
        if not row:
            raise RuntimeError("Wake insert failed")
        return row

    async def chat(
        self,
        thread_id: str,
        content: str,
        *,
        responsibility_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.db.one("SELECT id FROM threads WHERE id = ?", (thread_id,)):
            raise KeyError(thread_id)

        self._store_message(thread_id, "user", content)
        history = self.db.all(
            """
            SELECT role, content FROM messages
            WHERE thread_id = ?
            ORDER BY created_at DESC
            LIMIT 24
            """,
            (thread_id,),
        )
        history.reverse()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *[{"role": row["role"], "content": row["content"]} for row in history],
        ]

        pending_actions: list[str] = []
        final_content = ""

        for _ in range(10):
            response = await self.provider.chat(messages, TOOLS)
            final_content = response.content or final_content

            if not response.tool_calls:
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": response.tool_calls,
                }
            )

            for tool_call in response.tool_calls:
                fn = tool_call.get("function") or {}
                name = fn.get("name") or ""
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args)

                result = await self._call_tool(
                    name,
                    args,
                    responsibility_id=responsibility_id,
                )
                if result.get("status") == "approval_required":
                    pending_actions.append(result["action_id"])

                messages.append(
                    {
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            if pending_actions:
                final_content = (
                    response.content
                    or "I prepared an action that requires approval before it can run."
                )
                break

        if not final_content:
            final_content = "The local model returned no final text."

        self._store_message(thread_id, "assistant", final_content)
        return {
            "content": final_content,
            "pending_actions": pending_actions,
            "thread_id": thread_id,
        }

    async def run_responsibility(self, responsibility_id: str, reason: str) -> None:
        responsibility = self.get_responsibility(responsibility_id)
        if responsibility["status"] != "active":
            return

        self.activity(
            "wake.fired",
            f"Woke responsibility: {reason}",
            responsibility_id=responsibility_id,
        )
        prompt = (
            "Resume this responsibility.\n\n"
            f"Title: {responsibility['title']}\n"
            f"Objective: {responsibility['objective']}\n"
            f"Wake reason: {reason}\n\n"
            "Inspect relevant state, perform safe read-only work as needed, propose governed "
            "actions when mutation is necessary, and schedule another wake only if a concrete "
            "future dependency exists."
        )
        try:
            result = await self.chat(
                responsibility["thread_id"],
                prompt,
                responsibility_id=responsibility_id,
            )
            self.activity(
                "responsibility.turn",
                result["content"][:1000],
                responsibility_id=responsibility_id,
                metadata={"pending_actions": result["pending_actions"]},
            )
        except Exception as exc:
            self.db.execute(
                "UPDATE responsibilities SET status = 'failed', updated_at = ? WHERE id = ?",
                (now_iso(), responsibility_id),
            )
            self.activity(
                "responsibility.failed",
                str(exc),
                responsibility_id=responsibility_id,
            )
            raise

    async def _call_tool(
        self,
        name: str,
        args: dict[str, Any],
        *,
        responsibility_id: str | None,
    ) -> dict[str, Any]:
        if name == "list_files":
            return self.computer.list_files(
                args.get("path", "."),
                limit=int(args.get("limit", 200)),
            )

        if name == "read_file":
            return self.computer.read_text(args["path"])

        if name == "search_memory":
            return {
                "memories": self.memory.search(
                    args["query"],
                    scope=args.get("scope", "global"),
                    limit=int(args.get("limit", 8)),
                )
            }

        if name == "remember":
            return self.memory.add(
                args["content"],
                scope=args.get("scope", "global"),
                kind=args.get("kind", "fact"),
                source=args.get("source", "agent"),
                confidence=float(args.get("confidence", 1.0)),
                metadata={"responsibility_id": responsibility_id},
            )

        if name == "schedule_wake":
            if not responsibility_id:
                return {"error": "schedule_wake requires an active responsibility"}
            wake = self.schedule_wake(
                responsibility_id,
                int(args["delay_seconds"]),
                args["reason"],
            )
            return {
                "status": "scheduled",
                "wake_id": wake["id"],
                "run_at": wake["run_at"],
            }

        if name == "write_file":
            decision = self.sentinel.request(
                capability="filesystem.write",
                target=args["path"],
                intent=args["intent"],
                args={"path": args["path"], "content": args["content"]},
                preview=f"Write workspace file {args['path']}",
                risk="write",
            )
            self.activity(
                "action.proposed",
                f"Proposed filesystem write: {args['path']}",
                responsibility_id=responsibility_id,
                metadata={"action_id": decision.action_id, "status": decision.status},
            )
            if decision.status == "approved":
                return await self.execute_action(decision.action_id)
            return {
                "status": "approval_required",
                "action_id": decision.action_id,
                "preview": f"Write workspace file {args['path']}",
            }

        if name == "run_process":
            decision = self.sentinel.request(
                capability="process.exec",
                target=args.get("cwd", "."),
                intent=args["intent"],
                args={
                    "argv": args["argv"],
                    "cwd": args.get("cwd", "."),
                    "timeout": args.get("timeout", 120),
                },
                preview="Run process: " + " ".join(args["argv"]),
                risk="execute",
            )
            self.activity(
                "action.proposed",
                "Proposed process execution",
                responsibility_id=responsibility_id,
                metadata={"action_id": decision.action_id, "status": decision.status},
            )
            if decision.status == "approved":
                return await self.execute_action(decision.action_id)
            return {
                "status": "approval_required",
                "action_id": decision.action_id,
                "preview": "Run process: " + " ".join(args["argv"]),
            }

        return {"error": f"Unknown tool: {name}"}

    async def execute_action(self, action_id: str) -> dict[str, Any]:
        action = self.sentinel.mark_executing(action_id)
        args = self.sentinel.args(action)
        try:
            if action["capability"] == "filesystem.write":
                result = self.computer.write_text(args["path"], args["content"])
            elif action["capability"] == "process.exec":
                result = await asyncio.to_thread(
                    self.computer.run_process,
                    args["argv"],
                    cwd=args.get("cwd", "."),
                    timeout=int(args.get("timeout", 120)),
                )
            else:
                raise ValueError(f"No executor for capability {action['capability']}")
            self.sentinel.complete(action_id, result)
            self.activity(
                "action.completed",
                action["preview"],
                metadata={"action_id": action_id, "result": result},
            )
            return {"status": "completed", "action_id": action_id, "result": result}
        except Exception as exc:
            self.sentinel.fail(action_id, str(exc))
            self.activity(
                "action.failed",
                str(exc),
                metadata={"action_id": action_id},
            )
            raise

    def _store_message(self, thread_id: str, role: str, content: str) -> None:
        stamp = now_iso()
        self.db.execute(
            """
            INSERT INTO messages (id, thread_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex, thread_id, role, content, stamp),
        )
        self.db.execute(
            "UPDATE threads SET updated_at = ? WHERE id = ?",
            (stamp, thread_id),
        )


class WakeScheduler:
    def __init__(self, db: Database, callback: Callable[[str, str], Awaitable[None]]):
        self.db = db
        self.callback = callback
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            wake = self._claim_due()
            if wake:
                try:
                    await self.callback(wake["responsibility_id"], wake["reason"])
                    self.db.execute(
                        "UPDATE wakes SET status = 'completed', completed_at = ? WHERE id = ?",
                        (now_iso(), wake["id"]),
                    )
                except Exception as exc:
                    self.db.execute(
                        """
                        UPDATE wakes
                        SET status = 'failed', completed_at = ?, error = ?
                        WHERE id = ?
                        """,
                        (now_iso(), str(exc), wake["id"]),
                    )
                continue

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()

    def _claim_due(self) -> dict[str, Any] | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                SELECT * FROM wakes
                WHERE status = 'scheduled' AND run_at <= ?
                ORDER BY run_at ASC
                LIMIT 1
                """,
                (now_iso(),),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE wakes SET status = 'claimed', claimed_at = ? WHERE id = ?",
                (now_iso(), row["id"]),
            )
            return dict(row)
