"""Operator tombstones: mark bad catalog data as errored, never delete.

The evidence model is append-only — observation families carry immutability
triggers by design — so wrong data (a degenerate query's results, a bad
import) is corrected by marking, not removal: posts become unavailable
error-tombstones carrying the reason, and lookup runs are marked failed with
a diagnostic.  Consumers filter on availability; investigators find the full
story in the rows.  Nothing here deletes or rewrites immutable evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from media_catalog.database import CatalogDatabase

_TOMBSTONE_STATUS = "error-tombstone"
_REASON_LIMIT = 2000


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def tombstone_posts(
    database: CatalogDatabase,
    post_ids: list[int],
    *,
    reason: str,
) -> dict[str, Any]:
    if not reason.strip() or len(reason) > _REASON_LIMIT:
        raise ValueError("tombstone reason must be between 1 and 2000 characters")
    if not post_ids:
        raise ValueError("at least one post id is required")
    connection = database.connection
    now = _now()
    marked: list[int] = []
    already: list[int] = []
    missing: list[int] = []
    with database.transaction():
        for post_id in post_ids:
            if post_id <= 0:
                raise ValueError("post id must be positive")
            row = connection.execute(
                "SELECT status FROM posts WHERE post_id = ?", (post_id,)
            ).fetchone()
            if row is None:
                missing.append(post_id)
                continue
            if row["status"] == _TOMBSTONE_STATUS:
                already.append(post_id)
                continue
            connection.execute(
                """UPDATE posts
                      SET availability = 'unavailable', status = ?,
                          deleted_at = COALESCE(deleted_at, ?),
                          title = ?, updated_at = ?
                    WHERE post_id = ?""",
                (_TOMBSTONE_STATUS, now, f"tombstone: {reason}", now, post_id),
            )
            marked.append(post_id)
    return {
        "status": "tombstoned",
        "marked": marked,
        "already_tombstoned": already,
        "missing": missing,
        "reason": reason,
    }


def tombstone_lookup_run(
    database: CatalogDatabase,
    run_id: int,
    *,
    reason: str,
) -> dict[str, Any]:
    """Mark a lookup run failed with the operator's diagnostic.

    The run's inputs stay immutable (trigger-enforced); only the lifecycle
    status and diagnostic change, so every consumer sees the run as failed
    rather than as a trustworthy match source.
    """
    if not reason.strip() or len(reason) > _REASON_LIMIT:
        raise ValueError("tombstone reason must be between 1 and 2000 characters")
    if run_id <= 0:
        raise ValueError("lookup run id must be positive")
    connection = database.connection
    with database.transaction():
        row = connection.execute(
            "SELECT status, finished_at FROM candidate_lookup_runs"
            " WHERE candidate_lookup_run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"lookup run {run_id} not found")
        connection.execute(
            """UPDATE candidate_lookup_runs
                  SET status = 'failed',
                      termination_outcome = COALESCE(termination_outcome, 'malformed_response'),
                      diagnostic_summary = ?,
                      finished_at = COALESCE(finished_at, ?)
                WHERE candidate_lookup_run_id = ?""",
            (reason[:1000], _now(), run_id),
        )
    return {"status": "tombstoned", "lookup_run_id": run_id, "reason": reason}
