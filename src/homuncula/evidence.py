from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from .db import Database
from .auth import redact_payload, redact_text


REVIEW_ROLES = ("scout", "verifier", "skeptic", "integrator")
VALID_VERDICTS = {"pass", "hold", "reject"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _clean_strings(value: Any, *, limit: int, item_limit: int = 2000) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        text = str(item).strip()
        if text:
            result.append(text[:item_limit])
    return result


class EvidenceStore:
    """Durable epistemic state between raw observation and durable memory."""

    def __init__(self, db: Database):
        self.db = db

    def _validate_responsibility(self, responsibility_id: str | None) -> None:
        if responsibility_id and not self.db.one(
            "SELECT id FROM responsibilities WHERE id = ?",
            (responsibility_id,),
        ):
            raise KeyError(responsibility_id)

    def register_source(
        self,
        kind: str,
        locator: str,
        *,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_kind = kind.strip().lower()
        source_locator = redact_text(locator.strip())
        if not source_kind or len(source_kind) > 80:
            raise ValueError("Evidence source kind must be 1 to 80 characters")
        if not source_locator or len(source_locator) > 4000:
            raise ValueError("Evidence source locator must be 1 to 4000 characters")

        existing = self.db.one(
            "SELECT * FROM evidence_sources WHERE kind = ? AND locator = ?",
            (source_kind, source_locator),
        )
        if existing:
            return self._decode_source(existing)

        source_id = "source_" + uuid.uuid4().hex
        self.db.execute(
            """
            INSERT INTO evidence_sources
            (id, kind, locator, title, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                source_kind,
                source_locator,
                redact_text((title or "").strip())[:500],
                self.db.json(redact_payload(metadata or {})),
                now_iso(),
            ),
        )
        return self.get_source(source_id)

    def get_source(self, source_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM evidence_sources WHERE id = ?", (source_id,))
        if not row:
            raise KeyError(source_id)
        return self._decode_source(row)

    def capture_observation(
        self,
        *,
        source_kind: str,
        source_locator: str,
        content: str,
        responsibility_id: str | None = None,
        source_title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_responsibility(responsibility_id)
        text = redact_text(content.strip())
        if not text:
            raise ValueError("Evidence observation content cannot be empty")
        if len(text) > 50_000:
            raise ValueError("Evidence observation content exceeds 50000 characters")

        source = self.register_source(
            source_kind,
            source_locator,
            title=source_title,
        )
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = self.db.one(
            """
            SELECT id FROM evidence_observations
            WHERE source_id = ? AND content_hash = ?
            """,
            (source["id"], digest),
        )
        if existing:
            return self.get_observation(existing["id"])

        observation_id = "obs_" + uuid.uuid4().hex
        self.db.execute(
            """
            INSERT INTO evidence_observations
            (id, source_id, responsibility_id, content, content_hash, metadata_json, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation_id,
                source["id"],
                responsibility_id,
                text,
                digest,
                self.db.json(redact_payload(metadata or {})),
                now_iso(),
            ),
        )
        return self.get_observation(observation_id)

    def get_observation(self, observation_id: str) -> dict[str, Any]:
        row = self.db.one(
            """
            SELECT o.*, s.kind AS source_kind, s.locator AS source_locator,
                   s.title AS source_title, s.metadata_json AS source_metadata_json
            FROM evidence_observations o
            JOIN evidence_sources s ON s.id = o.source_id
            WHERE o.id = ?
            """,
            (observation_id,),
        )
        if not row:
            raise KeyError(observation_id)
        return self._decode_observation(row)

    def list_observations(
        self,
        *,
        responsibility_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 500))
        if responsibility_id:
            rows = self.db.all(
                """
                SELECT o.*, s.kind AS source_kind, s.locator AS source_locator,
                       s.title AS source_title, s.metadata_json AS source_metadata_json
                FROM evidence_observations o
                JOIN evidence_sources s ON s.id = o.source_id
                WHERE o.responsibility_id = ?
                ORDER BY o.observed_at DESC
                LIMIT ?
                """,
                (responsibility_id, bounded),
            )
        else:
            rows = self.db.all(
                """
                SELECT o.*, s.kind AS source_kind, s.locator AS source_locator,
                       s.title AS source_title, s.metadata_json AS source_metadata_json
                FROM evidence_observations o
                JOIN evidence_sources s ON s.id = o.source_id
                ORDER BY o.observed_at DESC
                LIMIT ?
                """,
                (bounded,),
            )
        return [self._decode_observation(row) for row in rows]

    def create_dossier(
        self,
        claim: str,
        observation_ids: list[str],
        *,
        responsibility_id: str | None = None,
        unknowns: list[str] | None = None,
    ) -> dict[str, Any]:
        self._validate_responsibility(responsibility_id)
        normalized_claim = claim.strip()
        if len(normalized_claim) < 8 or len(normalized_claim) > 8000:
            raise ValueError("Evidence claim must be 8 to 8000 characters")

        unique_ids = list(
            dict.fromkeys(
                str(item).strip()
                for item in observation_ids
                if str(item).strip()
            )
        )
        if not unique_ids:
            raise ValueError("An evidence dossier requires at least one observation")
        if len(unique_ids) > 20:
            raise ValueError("An evidence dossier supports at most 20 observations")

        observations = [self.get_observation(item) for item in unique_ids]
        distinct_sources = len({item["source"]["id"] for item in observations})
        source_kinds = sorted({item["source"]["kind"] for item in observations})
        precheck = {
            "eligible_for_review": True,
            "observation_count": len(observations),
            "distinct_source_count": distinct_sources,
            "source_kinds": source_kinds,
            "all_locators_present": all(
                bool(item["source"]["locator"]) for item in observations
            ),
        }
        declared_unknowns = _clean_strings(unknowns or [], limit=20)

        dossier_id = "dossier_" + uuid.uuid4().hex
        stamp = now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO evidence_dossiers
                (id, responsibility_id, claim, status, confidence, precheck_json,
                 declared_unknowns_json, unknowns_json, review_round_id,
                 promoted_memory_id, created_at, updated_at, reviewed_at)
                VALUES (?, ?, ?, 'hold', 0.0, ?, ?, ?, NULL, NULL, ?, ?, NULL)
                """,
                (
                    dossier_id,
                    responsibility_id,
                    normalized_claim,
                    self.db.json(precheck),
                    self.db.json(declared_unknowns),
                    self.db.json(declared_unknowns),
                    stamp,
                    stamp,
                ),
            )
            for position, observation_id in enumerate(unique_ids, start=1):
                conn.execute(
                    """
                    INSERT INTO evidence_dossier_observations
                    (dossier_id, observation_id, position)
                    VALUES (?, ?, ?)
                    """,
                    (dossier_id, observation_id, position),
                )
        return self.get_dossier(dossier_id)

    def get_dossier(self, dossier_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM evidence_dossiers WHERE id = ?", (dossier_id,))
        if not row:
            raise KeyError(dossier_id)
        row["precheck"] = json.loads(row.pop("precheck_json") or "{}")
        row["declared_unknowns"] = json.loads(
            row.pop("declared_unknowns_json") or "[]"
        )
        row["unknowns"] = json.loads(row.pop("unknowns_json") or "[]")
        observation_rows = self.db.all(
            """
            SELECT o.id
            FROM evidence_dossier_observations d
            JOIN evidence_observations o ON o.id = d.observation_id
            WHERE d.dossier_id = ?
            ORDER BY d.position
            """,
            (dossier_id,),
        )
        row["observations"] = [
            self.get_observation(item["id"]) for item in observation_rows
        ]
        reviews = self.db.all(
            """
            SELECT * FROM evidence_reviews
            WHERE dossier_id = ?
            ORDER BY created_at ASC
            """,
            (dossier_id,),
        )
        row["reviews"] = [self._decode_review(item) for item in reviews]
        return row

    def list_dossiers(
        self,
        *,
        responsibility_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if responsibility_id:
            clauses.append("responsibility_id = ?")
            params.append(responsibility_id)
        if status:
            if status not in VALID_VERDICTS:
                raise ValueError("Evidence dossier status must be pass, hold, or reject")
            clauses.append("status = ?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(limit, 500)))
        rows = self.db.all(
            f"""
            SELECT * FROM evidence_dossiers
            {where}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        for row in rows:
            row["precheck"] = json.loads(row.pop("precheck_json") or "{}")
            row["declared_unknowns"] = json.loads(
                row.pop("declared_unknowns_json") or "[]"
            )
            row["unknowns"] = json.loads(row.pop("unknowns_json") or "[]")
        return rows

    def review_packet(
        self,
        dossier_id: str,
        *,
        max_chars: int = 16_000,
    ) -> dict[str, Any]:
        dossier = self.get_dossier(dossier_id)
        fixed_cost = (
            len(dossier["claim"])
            + len(json.dumps(dossier["precheck"], ensure_ascii=False))
            + len(json.dumps(dossier["unknowns"], ensure_ascii=False))
            + 500
        )
        remaining = max(0, max_chars - fixed_cost)
        evidence: list[dict[str, Any]] = []
        for observation in dossier["observations"]:
            source = observation["source"]
            header_cost = len(observation["id"]) + len(source["locator"]) + 200
            if remaining <= header_cost:
                break
            available = min(6000, remaining - header_cost)
            if available <= 0:
                break
            body = observation["content"][:available]
            evidence.append(
                {
                    "id": observation["id"],
                    "source": {
                        "kind": source["kind"],
                        "locator": source["locator"],
                        "title": source["title"],
                    },
                    "observed_at": observation["observed_at"],
                    "content": body,
                }
            )
            remaining -= header_cost + len(body)

        return {
            "dossier_id": dossier["id"],
            "claim": dossier["claim"],
            "precheck": dossier["precheck"],
            "known_unknowns": dossier["unknowns"],
            "evidence": evidence,
        }

    def record_review(
        self,
        dossier_id: str,
        round_id: str,
        *,
        role: str,
        verdict: str,
        confidence: float,
        reasons: list[str],
        evidence_ids: list[str],
        unknowns: list[str],
        valid: bool,
        error: str | None = None,
    ) -> dict[str, Any]:
        if role not in REVIEW_ROLES:
            raise ValueError("Unknown evidence reviewer role")
        if verdict not in VALID_VERDICTS:
            raise ValueError("Unknown evidence verdict")

        review_id = "review_" + uuid.uuid4().hex
        self.db.execute(
            """
            INSERT INTO evidence_reviews
            (id, dossier_id, round_id, role, verdict, confidence, reasons_json,
             evidence_ids_json, unknowns_json, valid, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                dossier_id,
                round_id,
                role,
                verdict,
                max(0.0, min(1.0, confidence)),
                self.db.json(_clean_strings(reasons, limit=8)),
                self.db.json(
                    _clean_strings(evidence_ids, limit=20, item_limit=100)
                ),
                self.db.json(_clean_strings(unknowns, limit=12)),
                1 if valid else 0,
                (error or "")[:2000] or None,
                now_iso(),
            ),
        )
        row = self.db.one("SELECT * FROM evidence_reviews WHERE id = ?", (review_id,))
        if not row:
            raise RuntimeError("Evidence review insert failed")
        return self._decode_review(row)

    def finalize_round(self, dossier_id: str, round_id: str) -> dict[str, Any]:
        dossier = self.get_dossier(dossier_id)
        rows = self.db.all(
            """
            SELECT * FROM evidence_reviews
            WHERE dossier_id = ? AND round_id = ?
            ORDER BY created_at ASC
            """,
            (dossier_id, round_id),
        )
        reviews = [self._decode_review(row) for row in rows]
        by_role = {row["role"]: row for row in reviews}

        unknowns = list(dossier["declared_unknowns"])
        for review in reviews:
            unknowns.extend(review["unknowns"])
        unknowns = list(dict.fromkeys(item for item in unknowns if item))[:40]

        status = "hold"
        if set(by_role) == set(REVIEW_ROLES) and all(row["valid"] for row in reviews):
            verifier = by_role["verifier"]["verdict"]
            skeptic = by_role["skeptic"]["verdict"]
            integrator = by_role["integrator"]["verdict"]
            if (
                verifier == "reject"
                and skeptic == "reject"
            ) or (
                integrator == "reject"
                and (verifier == "reject" or skeptic == "reject")
            ):
                status = "reject"
            elif (
                verifier == "pass"
                and skeptic == "pass"
                and integrator == "pass"
                and not unknowns
            ):
                status = "pass"

        critical = [
            by_role[role]["confidence"]
            for role in ("verifier", "skeptic", "integrator")
            if role in by_role and by_role[role]["valid"]
        ]
        confidence = sum(critical) / len(critical) if critical else 0.0

        stamp = now_iso()
        self.db.execute(
            """
            UPDATE evidence_dossiers
            SET status = ?, confidence = ?, unknowns_json = ?,
                review_round_id = ?, updated_at = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (
                status,
                max(0.0, min(1.0, confidence)),
                self.db.json(unknowns),
                round_id,
                stamp,
                stamp,
                dossier_id,
            ),
        )
        return self.get_dossier(dossier_id)

    def promotable(self, dossier_id: str) -> bool:
        return self.get_dossier(dossier_id)["status"] == "pass"

    def mark_promoted(self, dossier_id: str, memory_id: str) -> dict[str, Any]:
        dossier = self.get_dossier(dossier_id)
        if dossier["status"] != "pass":
            raise ValueError("Only PASS evidence dossiers can be promoted")
        if dossier.get("promoted_memory_id"):
            return dossier
        self.db.execute(
            """
            UPDATE evidence_dossiers
            SET promoted_memory_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (memory_id, now_iso(), dossier_id),
        )
        return self.get_dossier(dossier_id)

    @staticmethod
    def _decode_source(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return item

    @staticmethod
    def _decode_observation(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        source = {
            "id": item.pop("source_id"),
            "kind": item.pop("source_kind"),
            "locator": item.pop("source_locator"),
            "title": item.pop("source_title"),
            "metadata": json.loads(item.pop("source_metadata_json") or "{}"),
        }
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        item["source"] = source
        return item

    @staticmethod
    def _decode_review(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["reasons"] = json.loads(item.pop("reasons_json") or "[]")
        item["evidence_ids"] = json.loads(item.pop("evidence_ids_json") or "[]")
        item["unknowns"] = json.loads(item.pop("unknowns_json") or "[]")
        item["valid"] = bool(item["valid"])
        return item
