"""Relationship review and epistemic-status transitions (operator surface)."""

from __future__ import annotations

from typing import Any

from media_catalog.database import CatalogDatabase
from media_catalog.records import validate_epistemic_status
from media_catalog.writer import CatalogWriter

_DECISIONS = {"confirm": "confirmed", "reject": "rejected", "pending": "pending"}


def review_relationship(
    database: CatalogDatabase,
    relationship_id: int,
    decision: str,
    *,
    note: str | None = None,
    clock: Any,
) -> dict[str, Any]:
    """Append a review decision; the relationship follows the latest decision."""

    if decision not in _DECISIONS:
        raise ValueError(f"decision must be one of {sorted(_DECISIONS)}")
    with database.transaction():
        result = CatalogWriter(database).record_relationship_review(
            relationship_id,
            decision=_DECISIONS[decision],
            decided_at=str(clock()),
            note=note,
        )
    return {
        "relationship_id": relationship_id,
        "decision_id": result.id,
        "decision": _DECISIONS[decision],
    }


def transition_relationship_status(
    database: CatalogDatabase,
    relationship_id: int,
    new_status: str,
    *,
    cause: str,
    clock: Any,
) -> dict[str, Any]:
    """Append a status transition (for example observed becoming verified)."""

    validate_epistemic_status(new_status)
    if not cause or len(cause) > 500:
        raise ValueError("a transition cause of 1-500 characters is required")
    with database.transaction():
        result = CatalogWriter(database).record_relationship_status(
            relationship_id, new_status=new_status, cause=cause, at=str(clock())
        )
    return {
        "relationship_id": relationship_id,
        "transition_id": result.id,
        "new_status": new_status,
    }
