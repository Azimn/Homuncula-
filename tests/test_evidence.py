from __future__ import annotations

import json
from pathlib import Path

import pytest

from homuncula.context import ContextCompiler
from homuncula.db import Database
from homuncula.evidence import EvidenceStore
from homuncula.evidence_review import EvidenceCouncil
from homuncula.memory import MemoryStore
from homuncula.provider import ProviderMessage


class SequenceProvider:
    def __init__(self, responses: list[str | Exception]):
        self.responses = list(responses)

    async def chat(self, messages, tools):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return ProviderMessage(
            content=item,
            tool_calls=[],
            raw={"content": item},
        )


def review_json(
    verdict: str,
    observation_id: str,
    *,
    confidence: float = 0.9,
    unknowns: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "confidence": confidence,
            "reasons": ["The packet supports this reviewer verdict."],
            "evidence_ids": [observation_id] if verdict == "pass" else [],
            "unknowns": unknowns or [],
        }
    )


def test_observations_are_deduplicated_with_provenance(tmp_path: Path) -> None:
    db = Database(tmp_path / "evidence.sqlite3")
    db.initialize()
    evidence = EvidenceStore(db)

    first = evidence.capture_observation(
        source_kind="browser",
        source_locator="https://example.test/report",
        source_title="Example report",
        content="The measured result was 42.",
    )
    second = evidence.capture_observation(
        source_kind="browser",
        source_locator="https://example.test/report",
        source_title="Example report",
        content="The measured result was 42.",
    )

    assert first["id"] == second["id"]
    assert first["source"]["kind"] == "browser"
    assert first["source"]["locator"] == "https://example.test/report"
    assert first["content_hash"]

    dossier = evidence.create_dossier(
        "The measured result was 42.",
        [first["id"]],
        unknowns=["Independent replication has not been checked."],
    )
    assert dossier["status"] == "hold"
    assert dossier["precheck"]["observation_count"] == 1
    assert dossier["precheck"]["distinct_source_count"] == 1
    assert dossier["declared_unknowns"]
    assert evidence.promotable(dossier["id"]) is False


@pytest.mark.asyncio
async def test_review_council_passes_only_with_valid_packet_citations(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "pass.sqlite3")
    db.initialize()
    evidence = EvidenceStore(db)
    observation = evidence.capture_observation(
        source_kind="document",
        source_locator="workspace://report.txt",
        content="The integration test completed successfully.",
    )
    dossier = evidence.create_dossier(
        "The integration test completed successfully.",
        [observation["id"]],
    )
    provider = SequenceProvider(
        [review_json("pass", observation["id"]) for _ in range(4)]
    )

    reviewed = await EvidenceCouncil(provider, evidence).review(dossier["id"])

    assert reviewed["status"] == "pass"
    assert reviewed["confidence"] == pytest.approx(0.9)
    assert len(reviewed["reviews"]) == 4
    assert all(item["valid"] for item in reviewed["reviews"])
    assert evidence.promotable(dossier["id"]) is True


@pytest.mark.asyncio
async def test_unknowns_keep_an_otherwise_passing_round_on_hold(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "unknown.sqlite3")
    db.initialize()
    evidence = EvidenceStore(db)
    observation = evidence.capture_observation(
        source_kind="document",
        source_locator="workspace://partial.txt",
        content="The observed result is positive.",
    )
    dossier = evidence.create_dossier(
        "The observed result is positive.",
        [observation["id"]],
    )
    provider = SequenceProvider(
        [
            review_json("pass", observation["id"]),
            review_json(
                "pass",
                observation["id"],
                unknowns=["Independent replication is unresolved."],
            ),
            review_json("pass", observation["id"]),
            review_json("pass", observation["id"]),
        ]
    )

    reviewed = await EvidenceCouncil(provider, evidence).review(dossier["id"])

    assert reviewed["status"] == "hold"
    assert "Independent replication is unresolved." in reviewed["unknowns"]


@pytest.mark.asyncio
async def test_invalid_reviewer_citation_fails_closed_to_hold(tmp_path: Path) -> None:
    db = Database(tmp_path / "invalid.sqlite3")
    db.initialize()
    evidence = EvidenceStore(db)
    observation = evidence.capture_observation(
        source_kind="api",
        source_locator="local://fixture",
        content="A bounded fixture observation.",
    )
    dossier = evidence.create_dossier(
        "The fixture contains a bounded observation.",
        [observation["id"]],
    )

    invalid = json.dumps(
        {
            "verdict": "pass",
            "confidence": 0.99,
            "reasons": ["Invented citation."],
            "evidence_ids": ["obs_not_in_packet"],
            "unknowns": [],
        }
    )
    provider = SequenceProvider(
        [
            invalid,
            review_json("pass", observation["id"]),
            review_json("pass", observation["id"]),
            review_json("pass", observation["id"]),
        ]
    )
    reviewed = await EvidenceCouncil(provider, evidence).review(dossier["id"])

    assert reviewed["status"] == "hold"
    assert any(not item["valid"] for item in reviewed["reviews"])
    assert "did not complete validly" in " ".join(reviewed["unknowns"])


@pytest.mark.asyncio
async def test_provider_failure_fails_closed_to_hold(tmp_path: Path) -> None:
    db = Database(tmp_path / "failure.sqlite3")
    db.initialize()
    evidence = EvidenceStore(db)
    observation = evidence.capture_observation(
        source_kind="git",
        source_locator="git://local/repo@abc123",
        content="The test fixture records a commit observation.",
    )
    dossier = evidence.create_dossier(
        "The repository fixture contains the observed commit.",
        [observation["id"]],
    )
    provider = SequenceProvider(
        [
            review_json("pass", observation["id"]),
            RuntimeError("local model unavailable"),
            review_json("pass", observation["id"]),
            review_json("pass", observation["id"]),
        ]
    )

    reviewed = await EvidenceCouncil(provider, evidence).review(dossier["id"])

    assert reviewed["status"] == "hold"
    failed = [item for item in reviewed["reviews"] if not item["valid"]]
    assert len(failed) == 1
    assert "RuntimeError" in str(failed[0]["error"])


@pytest.mark.asyncio
async def test_two_critical_rejections_resolve_to_reject(tmp_path: Path) -> None:
    db = Database(tmp_path / "reject.sqlite3")
    db.initialize()
    evidence = EvidenceStore(db)
    observation = evidence.capture_observation(
        source_kind="document",
        source_locator="workspace://negative.txt",
        content="The observed value was false.",
    )
    dossier = evidence.create_dossier(
        "The observed value was true.",
        [observation["id"]],
    )
    provider = SequenceProvider(
        [
            review_json("hold", observation["id"], confidence=0.6),
            review_json("reject", observation["id"], confidence=0.9),
            review_json("reject", observation["id"], confidence=0.95),
            review_json("hold", observation["id"], confidence=0.7),
        ]
    )

    reviewed = await EvidenceCouncil(provider, evidence).review(dossier["id"])

    assert reviewed["status"] == "reject"


def test_promotion_link_is_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "promote.sqlite3")
    db.initialize()
    evidence = EvidenceStore(db)
    memory = MemoryStore(db)
    observation = evidence.capture_observation(
        source_kind="document",
        source_locator="workspace://accepted.txt",
        content="The accepted claim has source evidence.",
    )
    dossier = evidence.create_dossier(
        "The accepted claim has source evidence.",
        [observation["id"]],
    )
    db.execute(
        """
        UPDATE evidence_dossiers
        SET status = 'pass', confidence = 0.88
        WHERE id = ?
        """,
        (dossier["id"],),
    )
    stored = memory.add(
        dossier["claim"],
        source=f"evidence:{dossier['id']}",
        confidence=0.88,
    )

    first = evidence.mark_promoted(dossier["id"], stored["id"])
    second = evidence.mark_promoted(dossier["id"], "different")

    assert first["promoted_memory_id"] == stored["id"]
    assert second["promoted_memory_id"] == stored["id"]


def test_context_surfaces_unresolved_responsibility_evidence(tmp_path: Path) -> None:
    db = Database(tmp_path / "context.sqlite3")
    db.initialize()
    memory = MemoryStore(db)
    evidence = EvidenceStore(db)
    stamp = "2026-10-06T00:00:00+00:00"

    db.execute(
        "INSERT INTO threads (id, title, created_at, updated_at) VALUES ('t', 'Research', ?, ?)",
        (stamp, stamp),
    )
    db.execute(
        """
        INSERT INTO responsibilities
        (id, thread_id, title, objective, status, proactive_mode, created_at, updated_at)
        VALUES ('r', 't', 'Check claim', 'Determine whether the claim is supported',
                'active', 'observe', ?, ?)
        """,
        (stamp, stamp),
    )

    observation = evidence.capture_observation(
        source_kind="browser",
        source_locator="https://example.test/evidence",
        content="One source reports the claimed result.",
        responsibility_id="r",
    )
    evidence.create_dossier(
        "The claimed result is established.",
        [observation["id"]],
        responsibility_id="r",
        unknowns=["A second independent source is still missing."],
    )

    compiler = ContextCompiler(db, memory, token_budget=4096)
    bundle = compiler.compile(
        "t",
        "Continue checking the claim.",
        responsibility_id="r",
    )

    evidence_blocks = [
        item["content"]
        for item in bundle.messages
        if "Epistemic evidence state:" in item["content"]
    ]
    assert evidence_blocks
    assert "[HOLD;" in evidence_blocks[0]
    assert "must not be stated as established fact" in evidence_blocks[0]
