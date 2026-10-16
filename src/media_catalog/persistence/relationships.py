"""Relationship-model writes behind the CatalogWriter facade.

Components receive the caller's ``CatalogDatabase`` and use its connection;
they never own transactions.  Inserts are idempotent through the
deterministic relationship key; review decisions and status transitions
append their rows and move only the relationship's current state fields
(the identity columns are trigger-immutable).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.persistence.support import WriteResult, caller_connection
from media_catalog.records import (
    RelationshipRecord,
    WorkRecord,
    validate_review_state,
)


class RelationshipWrites:
    def __init__(self, database: CatalogDatabase) -> None:
        self.connection = caller_connection(database)

    def materialize_work(self, record: WorkRecord) -> WriteResult:
        """Insert the deterministic work anchor unless it already exists."""

        existing = self.connection.execute(
            "SELECT work_id FROM works WHERE origin_post_id = ?",
            (record.origin_post_id,),
        ).fetchone()
        if existing is not None:
            return WriteResult(int(existing[0]), "existing")
        self.connection.execute(
            "INSERT INTO works (origin_post_id, work_kind, created_at) VALUES (?, ?, ?)",
            (record.origin_post_id, record.work_kind, record.created_at),
        )
        work_id = int(self.connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        return WriteResult(work_id, "inserted")

    def link_work_representation(
        self, work_id: int, media_occurrence_id: int, added_at: str
    ) -> WriteResult:
        cursor = self.connection.execute(
            """INSERT INTO work_representations (work_id, media_occurrence_id, added_at)
               VALUES (?, ?, ?) ON CONFLICT DO NOTHING""",
            (work_id, media_occurrence_id, added_at),
        )
        row = self.connection.execute(
            """SELECT work_id FROM work_representations
                WHERE work_id = ? AND media_occurrence_id = ?""",
            (work_id, media_occurrence_id),
        ).fetchone()
        return WriteResult(int(row[0]), "inserted" if cursor.rowcount else "existing")

    def insert_relationship(self, record: RelationshipRecord) -> WriteResult:
        cursor = self.connection.execute(
            """INSERT INTO relationships (
                   relationship_key, subject_kind, subject_id, relation_kind,
                   target_kind, target_id, epistemic_status, review_state,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
               ON CONFLICT(relationship_key) DO NOTHING""",
            (
                record.relationship_key,
                record.subject_kind,
                record.subject_id,
                record.relation_kind,
                record.target_kind,
                record.target_id,
                record.epistemic_status,
                record.created_at,
                record.created_at,
            ),
        )
        row = self.connection.execute(
            "SELECT relationship_id FROM relationships WHERE relationship_key = ?",
            (record.relationship_key,),
        ).fetchone()
        if row is None:  # pragma: no cover - the insert above guarantees the row
            raise RuntimeError("failed to store relationship")
        return WriteResult(int(row[0]), "inserted" if cursor.rowcount else "existing")

    def attach_evidence(self, relationship_id: int, evidence_id: int, added_at: str) -> WriteResult:
        cursor = self.connection.execute(
            """INSERT INTO relationship_evidence (relationship_id, evidence_id, added_at)
               VALUES (?, ?, ?) ON CONFLICT DO NOTHING""",
            (relationship_id, evidence_id, added_at),
        )
        return WriteResult(relationship_id, "inserted" if cursor.rowcount else "existing")

    def insert_evidence(
        self,
        *,
        evidence_kind: str,
        direction: str,
        strength: str,
        detector: str,
        detector_version: str,
        observed_at: str,
        explanation: str,
        components: dict[str, Any] | None = None,
        platform_reference_id: int | None = None,
    ) -> int:
        """Insert one generic evidence row (deduplicated by its digest)."""

        payload = json.dumps(
            {
                "evidence_kind": evidence_kind,
                "direction": direction,
                "strength": strength,
                "detector": detector,
                "detector_version": detector_version,
                "explanation": explanation,
                "components": components or {},
                "platform_reference_id": platform_reference_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self.connection.execute(
            """INSERT INTO match_evidence (
                   evidence_digest, stance, evidence_kind, direction, strength, detector,
                   detector_version, link_observation_id, platform_reference_id, observed_at,
                   explanation, components_json
               ) VALUES (?, 'supports', ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
               ON CONFLICT(evidence_digest) DO NOTHING""",
            (
                digest,
                evidence_kind,
                direction,
                strength,
                detector,
                detector_version,
                platform_reference_id,
                observed_at,
                explanation,
                json.dumps(components or {}, sort_keys=True, ensure_ascii=False),
            ),
        )
        row = self.connection.execute(
            "SELECT evidence_id FROM match_evidence WHERE evidence_digest = ?", (digest,)
        ).fetchone()
        if row is None:  # pragma: no cover - the insert above guarantees the row
            raise RuntimeError("failed to store evidence")
        return int(row[0])

    def record_review_decision(
        self,
        relationship_id: int,
        *,
        decision: str,
        decided_at: str,
        note: str | None = None,
    ) -> WriteResult:
        """Append a review decision and move the relationship's review state."""

        validate_review_state(decision)
        current = self._require_relationship(relationship_id)
        prior_state = str(current["review_state"])
        prior_status = str(current["epistemic_status"])
        self.connection.execute(
            """INSERT INTO relationship_review_decisions (
                   relationship_id, prior_state, decision, note, decided_at
               ) VALUES (?, ?, ?, ?, ?)""",
            (relationship_id, prior_state, decision, note, decided_at),
        )
        self.connection.execute(
            "UPDATE relationships SET review_state = ?, updated_at = ? WHERE relationship_id = ?",
            (decision, decided_at, relationship_id),
        )
        if decision == "confirmed" and prior_status != "reviewed":
            self.connection.execute(
                """INSERT INTO relationship_status_history (
                       relationship_id, prior_status, new_status, cause, at
                   ) VALUES (?, ?, 'reviewed', 'review decision', ?)""",
                (relationship_id, prior_status, decided_at),
            )
            self.connection.execute(
                "UPDATE relationships SET epistemic_status = 'reviewed' WHERE relationship_id = ?",
                (relationship_id,),
            )
        decision_id = int(self.connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        return WriteResult(decision_id, "inserted")

    def record_status_transition(
        self, relationship_id: int, *, new_status: str, cause: str, at: str
    ) -> WriteResult:
        """Append a status transition and move the current epistemic status."""

        current = self._require_relationship(relationship_id)
        prior_status = str(current["epistemic_status"])
        if prior_status == new_status:
            raise ValueError(f"relationship {relationship_id} is already {new_status}")
        self.connection.execute(
            """INSERT INTO relationship_status_history (
                   relationship_id, prior_status, new_status, cause, at
               ) VALUES (?, ?, ?, ?, ?)""",
            (relationship_id, prior_status, new_status, cause, at),
        )
        self.connection.execute(
            "UPDATE relationships SET epistemic_status = ?, updated_at = ? "
            "WHERE relationship_id = ?",
            (new_status, at, relationship_id),
        )
        history_id = int(self.connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        return WriteResult(history_id, "inserted")

    def _require_relationship(self, relationship_id: int) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT review_state, epistemic_status FROM relationships WHERE relationship_id = ?",
            (relationship_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"relationship {relationship_id} not found")
        return row
