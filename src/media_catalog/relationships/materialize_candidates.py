"""Materialize confirmed post match candidates into relationship rows.

The operator bridge from the candidate/review ledger into the Phase D
relationship model: only confirmed candidates materialize, under a fixed
kind mapping (post-level kinds become post relationships; work-level kinds
resolve through the posts' deterministic work anchors).  Evidence carries
over through the shared ledger, provenance rides the decision ledger, and
the deterministic relationship key makes re-materialization idempotent.
Nothing here ever writes the candidate side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.records import RelationshipRecord
from media_catalog.writer import CatalogWriter

# Candidate relation kind -> (relationship kind, endpoint altitude).
_POST_LEVEL = {"sourced_from": "reposted_from", "repost_of": "reposted_from"}
_WORK_LEVEL = {"same_work": "same_work", "variant_of": "variant_of", "derived_from": "derived_from"}


@dataclass(frozen=True, slots=True)
class MaterializationItem:
    candidate_id: int
    outcome: str  # materialized | existing | refused
    reason: str | None
    relationship_id: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "outcome": self.outcome,
            **({"reason": self.reason} if self.reason else {}),
            **({"relationship_id": self.relationship_id} if self.relationship_id else {}),
        }


def _resolve(connection: Any, row: Any) -> tuple[str, int, str, str, int] | None:
    """Subject kind/id, relationship kind, target kind/id — or None when unusable."""

    subject_post = int(row["subject_post_id"])
    if row["target_post_id"] is None:
        return None
    target_post = int(row["target_post_id"])
    kind = row["relation_kind"]
    if kind in _POST_LEVEL:
        return "post", subject_post, _POST_LEVEL[kind], "post", target_post
    subject_work = connection.execute(
        "SELECT work_id FROM works WHERE origin_post_id = ?", (subject_post,)
    ).fetchone()
    target_work = connection.execute(
        "SELECT work_id FROM works WHERE origin_post_id = ?", (target_post,)
    ).fetchone()
    if subject_work is None or target_work is None:
        return None
    return (
        "work",
        int(subject_work[0]),
        _WORK_LEVEL[kind],
        "work",
        int(target_work[0]),
    )


def materialize_candidates(
    database: CatalogDatabase,
    *,
    candidate_id: int | None = None,
    clock: Any,
) -> dict[str, Any]:
    """Materialize confirmed post candidates into reviewed relationships."""

    now = str(clock())
    items: list[MaterializationItem] = []
    with database.transaction():
        writer = CatalogWriter(database)
        connection = database.connection
        clause = "WHERE pc.post_candidate_id = ?" if candidate_id is not None else ""
        values: tuple[Any, ...] = (candidate_id,) if candidate_id is not None else ()
        rows = connection.execute(
            f"""SELECT pc.post_candidate_id, pc.subject_post_id, pc.target_post_id,
                       pc.relation_kind, pc.current_state
                  FROM post_match_candidates pc {clause}
              ORDER BY pc.post_candidate_id""",
            values,
        ).fetchall()
        for row in rows:
            items.append(_materialize_one(writer, connection, row, now))
    if candidate_id is not None and not items:
        raise ValueError(f"candidate not found: post:{candidate_id}")
    counts: dict[str, int] = {}
    for item in items:
        counts[item.outcome] = counts.get(item.outcome, 0) + 1
    return {
        "count": len(items),
        "counts": dict(sorted(counts.items())),
        "results": [item.as_dict() for item in items],
    }


def _materialize_one(
    writer: CatalogWriter, connection: Any, row: Any, now: str
) -> MaterializationItem:
    candidate_id = int(row["post_candidate_id"])
    if row["current_state"] != "confirmed":
        return MaterializationItem(candidate_id, "refused", "candidate_not_confirmed", None)
    kind = row["relation_kind"]
    if kind == "unresolved":
        return MaterializationItem(candidate_id, "refused", "unresolved_relation_kind", None)
    resolved = _resolve(connection, row)
    if resolved is None:
        if row["target_post_id"] is None:
            return MaterializationItem(candidate_id, "refused", "target_reference_unresolved", None)
        return MaterializationItem(candidate_id, "refused", "work_anchor_missing", None)
    subject_kind, subject_id, relation_kind, target_kind, target_id = resolved

    result = writer.insert_relationship(
        RelationshipRecord(
            subject_kind=subject_kind,
            subject_id=subject_id,
            relation_kind=relation_kind,
            target_kind=target_kind,
            target_id=target_id,
            epistemic_status="reviewed",
            created_at=now,
        )
    )
    existing_state = None
    if result.outcome != "inserted":
        existing_state = connection.execute(
            "SELECT review_state FROM relationships WHERE relationship_id = ?",
            (result.id,),
        ).fetchone()
    # A fresh row always gets its provenance decision. An existing row gets
    # one only when no review has landed on it yet -- a seeded relationship
    # (observed, pending) is upgraded by the candidate's confirmation, while
    # an already-confirmed row keeps its original decision and gains only the
    # candidate's evidence.
    if result.outcome == "inserted" or (
        existing_state is not None and existing_state[0] == "pending"
    ):
        writer.record_relationship_review(
            result.id,
            decision="confirmed",
            decided_at=now,
            note=f"materialized from confirmed candidate post:{candidate_id}",
        )
    # Evidence top-up: attach any of the candidate's evidence not yet linked,
    # whether the relationship is new or already existed.
    for evidence in connection.execute(
        "SELECT evidence_id FROM post_candidate_evidence WHERE post_candidate_id = ?"
        " ORDER BY evidence_id",
        (candidate_id,),
    ):
        writer.attach_relationship_evidence(result.id, int(evidence[0]), now)
    outcome = "materialized" if result.outcome == "inserted" else "existing"
    return MaterializationItem(candidate_id, outcome, None, result.id)
