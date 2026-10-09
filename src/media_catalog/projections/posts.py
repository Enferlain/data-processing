"""The ``posts`` projection: one row per post with its current facts.

Current mutable facts carry the evidence-layer pointer the catalog already
maintains (the raw observation behind the newest-observation-wins
resolution); participant summaries keep each role and review state exactly
as recorded, never overriding a review decision.  URLs are emitted origin
and path only.  Text content and raw payloads are deliberately omitted.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from media_catalog.projections.spec import ProjectionResult, enforce_allowlist, strip_url_query

KIND = "posts"

ALLOWLIST = (
    "post_id",
    "platform",
    "native_post_id",
    "canonical_url",
    "created_at",
    "updated_at",
    "rating",
    "availability",
    "status",
    "title",
    "provider_post_type",
    "language",
    "first_seen_at",
    "last_seen_at",
    "evidence_raw_observation_id",
    "occurrence_count",
    "participant_count",
    "participants",
)

PARTICIPANT_FIELDS = ("platform", "account_native_id", "role", "review_state")

POLICIES = {
    "selection": "all posts, or posts of one platform when a platform filter is given",
    "ordering": "post_id ascending",
    "dedup": "none_post_identity",
    "preferred_representation": "not_applicable_pending_phase_d",
    "field_source": "current_row_pointer",
    "url_handling": "origin_and_path_only",
}

IDENTIFIERS = {
    "row_identifier": "post_id",
    "platform_identity": "platform plus native_post_id",
    "evidence": (
        "post_id references posts; evidence_raw_observation_id points at the "
        "raw observation behind the current values"
    ),
}


def build(
    connection: sqlite3.Connection, *, limit: int, platform: str | None = None
) -> ProjectionResult:
    clauses = ""
    values: list[Any] = []
    if platform is not None:
        clauses = "WHERE pl.platform_key = ?"
        values.append(platform)
    total = int(
        connection.execute(
            f"""SELECT COUNT(*) FROM posts p
                 JOIN platforms pl ON pl.platform_id = p.platform_id {clauses}""",
            values,
        ).fetchone()[0]
    )
    unfiltered = int(connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
    rows = [
        _row(connection, record)
        for record in connection.execute(
            f"""SELECT p.post_id, pl.platform_key AS platform, p.native_post_id,
                       p.canonical_url, p.created_at, p.updated_at, p.rating,
                       p.availability, p.status, p.title, p.provider_post_type,
                       p.language, p.first_seen_at, p.last_seen_at,
                       p.raw_observation_id AS evidence_raw_observation_id,
                       (SELECT COUNT(*) FROM media_occurrences mo
                         WHERE mo.post_id = p.post_id) AS occurrence_count
                  FROM posts p
                  JOIN platforms pl ON pl.platform_id = p.platform_id
                  {clauses}
             ORDER BY p.post_id
                LIMIT ?""",
            [*values, limit],
        )
    ]
    selection_keys = [f"{row['post_id']}:{row['platform']}:{row['native_post_id']}" for row in rows]
    exclusions: list[dict[str, Any]] = []
    excluded_by_filter = unfiltered - total
    if excluded_by_filter:
        exclusions.append({"reason": "excluded_by_platform_filter", "count": excluded_by_filter})
    excluded_by_limit = max(0, total - limit)
    if excluded_by_limit:
        exclusions.append({"reason": "excluded_by_limit", "count": excluded_by_limit})
    return ProjectionResult(rows, selection_keys, len(rows), exclusions)


def _row(connection: sqlite3.Connection, record: sqlite3.Row) -> dict[str, Any]:
    row = dict(record)
    row["canonical_url"] = strip_url_query(row.get("canonical_url"))
    row["participants"] = _participants(connection, int(record["post_id"]))
    row["participant_count"] = len(row["participants"])
    return enforce_allowlist(row, ALLOWLIST)


def _participants(connection: sqlite3.Connection, post_id: int) -> list[dict[str, Any]]:
    return [
        enforce_allowlist(
            {
                "platform": record["platform_key"],
                "account_native_id": record["native_account_id"],
                "role": record["role"],
                "review_state": record["review_state"],
            },
            PARTICIPANT_FIELDS,
        )
        for record in connection.execute(
            """SELECT pl.platform_key, a.native_account_id, pp.role, pp.review_state
                 FROM post_participants pp
                 JOIN accounts a ON a.account_id = pp.account_id
                 JOIN platforms pl ON pl.platform_id = a.platform_id
                WHERE pp.post_id = ?
                ORDER BY a.native_account_id, pp.role""",
            (post_id,),
        )
    ]
