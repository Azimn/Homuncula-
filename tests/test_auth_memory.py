from __future__ import annotations

from pathlib import Path

from homuncula.auth import REDACTED, load_or_create_owner_token, redact_payload
from homuncula.context import ContextCompiler
from homuncula.db import Database
from homuncula.memory import MemoryStore


def test_owner_token_is_persisted_and_redaction_is_recursive(tmp_path: Path) -> None:
    token = load_or_create_owner_token(tmp_path)
    assert len(token) >= 32
    assert load_or_create_owner_token(tmp_path) == token

    payload = {
        "token": "abc",
        "nested": {"password": "p", "safe": 7},
        "items": [{"authorization": "Bearer secret"}],
    }
    redacted = redact_payload(payload)
    assert redacted["token"] == REDACTED
    assert redacted["nested"]["password"] == REDACTED
    assert redacted["nested"]["safe"] == 7
    assert redacted["items"][0]["authorization"] == REDACTED


def test_memory_revision_hybrid_search_and_context(tmp_path: Path) -> None:
    db = Database(tmp_path / "memory.sqlite3")
    db.initialize()
    memory = MemoryStore(db)

    first = memory.add(
        "The project uses a local Ollama model for inference.",
        kind="decision",
        source="user",
    )
    memory.add(
        "The village game has a gothic setting.",
        kind="fact",
        source="project",
    )

    results = memory.search("local Ollama inference", limit=5)
    assert results
    assert results[0]["id"] == first["id"]

    revised = memory.revise(
        first["id"],
        content="The project prefers a local model provider and can use Ollama.",
        reason="Clarified provider independence",
        source="user",
    )
    assert revised["revisions"]
    assert revised["revisions"][0]["previous_content"].startswith("The project uses")

    stamp = first["created_at"]
    db.execute(
        "INSERT INTO threads (id, title, created_at, updated_at) VALUES ('t', 'Main', ?, ?)",
        (stamp, stamp),
    )
    db.execute(
        """
        INSERT INTO messages (id, thread_id, role, content, created_at)
        VALUES ('m1', 't', 'user', 'Use the local model plan', ?)
        """,
        (stamp,),
    )
    compiler = ContextCompiler(db, memory, token_budget=2048)
    bundle = compiler.compile("t", "What model plan are we using?")
    assert bundle.estimated_tokens <= 2048
    assert any("durable memory" in item["content"].lower() for item in bundle.messages)
