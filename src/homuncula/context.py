from __future__ import annotations

import json
from dataclasses import dataclass

from .db import Database
from .memory import MemoryStore
from .plans import PlanStore
from .skills import SkillStore


@dataclass(frozen=True)
class ContextBundle:
    messages: list[dict[str, str]]
    memory_ids: list[str]
    skill_names: list[str]
    plan_id: str | None
    estimated_tokens: int


class ContextCompiler:
    def __init__(
        self,
        db: Database,
        memory: MemoryStore,
        plans: PlanStore,
        skills: SkillStore,
        *,
        token_budget: int = 12000,
    ):
        self.db = db
        self.memory = memory
        self.plans = plans
        self.skills = skills
        self.token_budget = max(2048, token_budget)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, (len(text) + 3) // 4)

    def _append_if_fits(
        self,
        messages: list[dict[str, str]],
        text: str,
        consumed: int,
        *,
        reserve: int = 0,
    ) -> int:
        token_cost = self._estimate_tokens(text)
        if consumed + token_cost + reserve > self.token_budget:
            return consumed
        messages.append({"role": "system", "content": text})
        return consumed + token_cost

    def compile(
        self,
        thread_id: str,
        current_text: str,
        *,
        responsibility_id: str | None = None,
    ) -> ContextBundle:
        consumed = 0
        messages: list[dict[str, str]] = []
        memory_ids: list[str] = []
        skill_names: list[str] = []
        plan_id: str | None = None

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
            consumed = self._append_if_fits(
                messages,
                "Relevant durable memory:\n" + "\n".join(lines),
                consumed,
                reserve=self.token_budget // 2,
            )

        matched_skills = self.skills.search(query, limit=3)
        if matched_skills:
            skill_blocks: list[str] = []
            for skill in matched_skills:
                body = skill["instructions"][:7000]
                skill_blocks.append(
                    f"Skill: {skill['name']}\n"
                    f"Description: {skill['description']}\n"
                    f"Allowed tool guidance: {', '.join(skill['allowed_tools']) or 'none declared'}\n"
                    f"Instructions:\n{body}"
                )
                skill_names.append(skill["name"])
            consumed = self._append_if_fits(
                messages,
                "Relevant local skills:\n\n" + "\n\n".join(skill_blocks),
                consumed,
                reserve=self.token_budget // 3,
            )

        if responsibility:
            state_text = (
                "Active responsibility state:\n"
                f"Title: {responsibility['title']}\n"
                f"Objective: {responsibility['objective']}\n"
                f"Status: {responsibility['status']}\n"
                f"Proactive mode: {responsibility['proactive_mode']}"
            )
            consumed = self._append_if_fits(
                messages,
                state_text,
                consumed,
                reserve=self.token_budget // 3,
            )

            plan = self.plans.active(responsibility_id)
            if plan:
                plan_id = plan["id"]
                step_lines = []
                for step in plan["steps"]:
                    marker = ">>" if step["status"] == "active" else "-"
                    step_lines.append(
                        f"{marker} {step['position']}. {step['title']} [{step['status']}]"
                    )
                plan_text = (
                    "Durable active plan:\n"
                    f"Plan ID: {plan['id']}\n"
                    f"Goal: {plan['goal']}\n"
                    + "\n".join(step_lines)
                    + "\nAdvance the plan only after the active step is actually complete."
                )
                consumed = self._append_if_fits(
                    messages,
                    plan_text,
                    consumed,
                    reserve=self.token_budget // 4,
                )

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
                consumed = self._append_if_fits(
                    messages,
                    "Recent operational history:\n" + "\n".join(lines),
                    consumed,
                    reserve=self.token_budget // 4,
                )

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
            if consumed + token_cost > self.token_budget:
                break
            selected.append({"role": row["role"], "content": row["content"]})
            consumed += token_cost
        selected.reverse()
        messages.extend(selected)

        return ContextBundle(
            messages=messages,
            memory_ids=memory_ids,
            skill_names=skill_names,
            plan_id=plan_id,
            estimated_tokens=consumed,
        )
