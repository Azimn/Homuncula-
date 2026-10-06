from __future__ import annotations

from pathlib import Path

import pytest

from homuncula.db import Database
from homuncula.memory import MemoryStore
from homuncula.provider import ProviderMessage
from homuncula.review import PostTurnReviewer, parse_review_json, prune_conversation
from homuncula.sentinel import Sentinel
from homuncula.skills import SkillStore


class FakeProvider:
    def __init__(self, content: str):
        self.content = content

    async def chat(self, messages, tools):
        return ProviderMessage(
            content=self.content,
            tool_calls=[],
            raw={"content": self.content},
        )


def test_review_digest_is_recent_and_bounded() -> None:
    messages = [
        {"role": "user", "content": "old " + ("x" * 5000)},
        {"role": "assistant", "content": "middle"},
        {"role": "user", "content": "recent preference"},
    ]
    digest = prune_conversation(messages, max_messages=2, max_chars=200)
    assert "recent preference" in digest
    assert "old " not in digest
    assert len(digest) <= 200


def test_review_json_accepts_plain_and_fenced_json() -> None:
    plain = parse_review_json('{"memories":[],"skill_suggestions":[]}')
    fenced = parse_review_json(
        '```json\n{"memories":[],"skill_suggestions":[]}\n```'
    )
    assert plain == fenced


@pytest.mark.asyncio
async def test_review_adds_memory_but_skill_requires_approval(tmp_path: Path) -> None:
    db = Database(tmp_path / "review.sqlite3")
    db.initialize()
    memory = MemoryStore(db)
    skills = SkillStore(tmp_path / "skills")
    sentinel = Sentinel(db)
    provider = FakeProvider(
        """
        {
          "memories": [
            {
              "content": "The user prefers concise technical status updates.",
              "kind": "preference",
              "confidence": 0.93
            }
          ],
          "skill_suggestions": [
            {
              "name": "Repository Verification",
              "description": "Verify repository changes before claiming completion.",
              "instructions": "Run the relevant tests and quality checks, record exact results, and report only the scope actually verified.",
              "allowed_tools": ["run_process", "read_file"]
            }
          ]
        }
        """
    )
    reviewer = PostTurnReviewer(provider, memory, skills, sentinel)

    result = await reviewer.review(
        [
            {"role": "user", "content": "Keep status updates concise and verify changes."},
            {"role": "assistant", "content": "Understood."},
        ]
    )

    assert result["memories_added"] == 1
    stored = memory.list(limit=10)
    assert stored[0]["source"] == "background-review"
    assert "concise technical status" in stored[0]["content"]

    assert len(result["skill_actions"]) == 1
    pending = sentinel.pending()
    assert len(pending) == 1
    assert pending[0]["capability"] == "skill.install"
    assert pending[0]["status"] == "pending"
    assert skills.list() == []
