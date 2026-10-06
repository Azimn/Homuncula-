from __future__ import annotations

import json
import re
from typing import Any

from .memory import MemoryStore
from .provider import OllamaProvider
from .sentinel import Sentinel
from .skills import SkillStore


REVIEW_PROMPT = """
Review the recent local conversation for durable learning.

Return one JSON object and nothing else:
{
  "memories": [
    {
      "content": "durable fact, preference, decision, or commitment",
      "kind": "fact|preference|decision|relationship|commitment",
      "confidence": 0.0
    }
  ],
  "skill_suggestions": [
    {
      "name": "short reusable class-level skill name",
      "description": "what recurring task this skill covers",
      "instructions": "concise reusable procedure",
      "allowed_tools": ["optional", "tool", "names"]
    }
  ]
}

Rules:
Only save information that is likely to matter in future conversations.
Do not save transient wording, secrets, credentials, or hidden reasoning.
Prefer zero items over weak guesses.
Limit memories to 3 and skill suggestions to 2.
Skill suggestions must describe reusable classes of work, not one-off fixes.
Do not claim to have changed a skill. Skill installation requires user approval.
""".strip()


def prune_conversation(
    messages: list[dict[str, Any]],
    *,
    max_messages: int = 12,
    max_chars: int = 12_000,
) -> str:
    lines: list[str] = []
    for message in messages[-max_messages:]:
        role = str(message.get("role") or "unknown")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        compact = re.sub(r"\\s+", " ", content).strip()
        lines.append(f"{role.upper()}: {compact[:1600]}")

    selected: list[str] = []
    used = 0
    for line in reversed(lines):
        cost = len(line) + 1
        if used + cost > max_chars:
            break
        selected.append(line)
        used += cost
    selected.reverse()
    return "\n".join(selected)


def parse_review_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Review output must be a JSON object")
    return data


class PostTurnReviewer:
    def __init__(
        self,
        provider: OllamaProvider,
        memory: MemoryStore,
        skills: SkillStore,
        sentinel: Sentinel,
    ):
        self.provider = provider
        self.memory = memory
        self.skills = skills
        self.sentinel = sentinel

    async def review(
        self,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        digest = prune_conversation(messages)
        if not digest:
            return {"memories_added": 0, "skill_actions": []}

        response = await self.provider.chat(
            [
                {"role": "system", "content": REVIEW_PROMPT},
                {"role": "user", "content": digest},
            ],
            [],
        )
        data = parse_review_json(response.content)
        memories_added = self._apply_memories(data.get("memories"))
        skill_actions = self._propose_skills(data.get("skill_suggestions"))
        return {
            "memories_added": memories_added,
            "skill_actions": skill_actions,
        }

    def _apply_memories(self, raw: Any) -> int:
        if not isinstance(raw, list):
            return 0
        added = 0
        allowed_kinds = {
            "fact",
            "preference",
            "decision",
            "relationship",
            "commitment",
        }
        for item in raw[:3]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if len(content) < 8 or len(content) > 2000:
                continue
            kind = str(item.get("kind") or "fact").strip().lower()
            if kind not in allowed_kinds:
                kind = "fact"
            try:
                confidence = float(item.get("confidence", 0.75))
            except (TypeError, ValueError):
                confidence = 0.75
            confidence = max(0.0, min(1.0, confidence))
            if confidence < 0.65 or self._already_known(content):
                continue
            self.memory.add(
                content,
                kind=kind,
                source="background-review",
                confidence=confidence,
                metadata={"reviewed": True},
            )
            added += 1
        return added

    def _already_known(self, content: str) -> bool:
        normalized = " ".join(content.lower().split())
        for row in self.memory.search(content, scope="global", limit=5):
            existing = " ".join(str(row["content"]).lower().split())
            if existing == normalized:
                return True
        return False

    def _propose_skills(self, raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        actions: list[str] = []
        existing = {item["name"] for item in self.skills.list()}
        for item in raw[:2]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            description = str(item.get("description") or "").strip()
            instructions = str(item.get("instructions") or "").strip()
            allowed_tools = item.get("allowed_tools") or []
            if not name or not description or len(instructions) < 20:
                continue
            try:
                normalized = self.skills.normalize_name(name)
            except ValueError:
                continue
            if normalized in existing:
                continue
            if not isinstance(allowed_tools, list):
                allowed_tools = []
            clean_tools = [
                str(tool)
                for tool in allowed_tools
                if isinstance(tool, str)
            ][:20]
            decision = self.sentinel.request(
                capability="skill.install",
                target=normalized,
                intent="Post-turn review suggested a reusable local skill",
                args={
                    "op": "install",
                    "name": normalized,
                    "description": description[:1000],
                    "instructions": instructions[:8000],
                    "allowed_tools": clean_tools,
                    "source": "background-review",
                },
                preview=f"Install suggested local skill {normalized}",
                risk="local-extension",
                force_approval=True,
            )
            if decision.status == "pending":
                actions.append(decision.action_id)
        return actions
