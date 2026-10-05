from __future__ import annotations

import json
from dataclasses import dataclass
from .db import Database
from .memory import MemoryStore


@dataclass(frozen=True)
class ContextBundle:
    messages: list[dict[str, str]]
    memory_ids: list[str]
    estimated_tokens: int


class ContextCompiler:
    def __init__(
        self,
        db: Database,
        memory: MemoryStore,
        *,
        token_budget: int = 12000,
    ):
        self.db = db
        self.memory = memory
        self.token_budget = max(2048, token_budget)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, (len(text) + 3) // 4)

    def compile(
        self,
        thread_id: str,
        current_text: str,
        *,
        responsibility_id: str | None = None,
    ) -> ContextBundle:
        budget = self.token_budget
        consumed = 0
        messages: list[dict[str, str]] = []
        memory_ids: list[str] = []

        responsibility = None
        if responsibility_id:
            responsibility = self.db.one(
                "SELECT * FROM responsibilities WHERE id = ?",
                (responsibility_id,),
            )

        query_parts = [current_text]
        if responsibility:
            query_parts.extend(
                [
                    responsibility["title"],
                    responsibility["objective"],
                ]
            )
        query = " ".join(part for part in query_parts if part).strip()

        memory_rows = self.memory.search(
            query,
            scope=responsibility_id or "global",
            limit=12,
        )
        if memory_rows:
            lines = []
            for row in memory_rows:
                memory_ids.append(row["id"])
                lines.append(
                    f"[{row['kind']}; source={row['source']}; confidence={row['confidence']:.2f}] "
                    f"{row['content']}"
                )
            memory_text = "Relevant durable memory:\n" + "\n".join(lines)
            token_cost = self._estimate_tokens(memory_text)
            if token_cost < budget // 3:
                messages.append({"role": "system", "content": memory_text})
                consumed += token_cost

        if responsibility:
            state_text = (
                "Active responsibility state:\n"
                f"Title: {responsibility['title']}\n"
                f"Objective: {responsibility['objective']}\n"
                f"Status: {responsibility['status']}\n"
                f"Proactive mode: {responsibility['proactive_mode']}"
            )
            token_cost = self._estimate_tokens(state_text)
            if consumed + token_cost < budget:
                messages.append({"role": "system", "content": state_text})
                consumed += token_cost

            activities = self.db.all(
                """
                SELECT kind, message, metadata_json, created_at
                FROM activities
                WHERE responsibility_id = ?
                ORDER BY created_at DESC
                LIMIT 12
                """,
                (responsibility_id,),
            )
            activities.reverse()
            if activities:
                lines = []
                for item in activities:
                    metadata = json.loads(item["metadata_json"] or "{}")
                    metadata.pop("credential_ref", None)
                    lines.append(
                        f"{item['created_at']} {item['kind']}: {item['message']}"
                    )
                activity_text = "Recent operational history:\n" + "\n".join(lines)
                token_cost = self._estimate_tokens(activity_text)
                if consumed + token_cost < budget:
                    messages.append({"role": "system", "content": activity_text})
                    consumed += token_cost

        rows = self.db.all(
            """
            SELECT role, content
            FROM messages
            WHERE thread_id = ?
            ORDER BY created_at DESC
            LIMIT 80
            """,
            (thread_id,),
        )

        selected: list[dict[str, str]] = []
        for row in rows:
            token_cost = self._estimate_tokens(row["content"])
            if consumed + token_cost > budget:
                break
            selected.append({"role": row["role"], "content": row["content"]})
            consumed += token_cost
        selected.reverse()
        messages.extend(selected)

        return ContextBundle(
            messages=messages,
            memory_ids=memory_ids,
            estimated_tokens=consumed,
        )
