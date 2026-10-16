"""The ``works`` projection: variant-family grouping per work anchor.

One row per materialized work listing its representations (roles and
verified byte links).  The preferred-representation policy excludes
thumbnail and preview roles and prefers the upstream original, then the
largest locally verified area — stated in the manifest, applied here.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from media_catalog.projections.spec import ProjectionResult, enforce_allowlist

KIND = "works"

ALLOWLIST = (
    "work_id",
    "work_kind",
    "origin_platform",
    "origin_native_post_id",
    "representations",
    "preferred_representation",
    "same_work_count",
)

REPRESENTATION_FIELDS = ("media_occurrence_id", "role", "verified_sha256")

THUMBNAIL_ROLES = ("sample", "preview")

POLICIES = {
    "selection": "all materialized works",
    "ordering": "work_id ascending",
    "dedup": "none_work_identity",
    "preferred_representation": (
        "exclude_sample_and_preview_roles_then_original_role_then_largest_verified_area"
    ),
    "field_source": "work_anchors_occurrence_roles_verified_asset_hashes",
    "url_handling": "no_urls_emitted",
}

IDENTIFIERS = {
    "row_identifier": "work_id",
    "platform_identity": "origin_platform plus origin_native_post_id",
    "evidence": (
        "work_id references works; representations reference media_occurrences "
        "and their verified asset hashes"
    ),
}


def build(
    connection: sqlite3.Connection, *, limit: int, platform: str | None = None
) -> ProjectionResult:
    if platform is not None:
        raise ValueError("the works projection does not support a platform filter")
    total = int(connection.execute("SELECT COUNT(*) FROM works").fetchone()[0])
    excluded_by_limit = max(0, total - limit)
    work_rows = connection.execute(
        """SELECT w.work_id, w.work_kind, pl.platform_key AS origin_platform,
                  op.native_post_id AS origin_native_post_id
             FROM works w
             JOIN posts op ON op.post_id = w.origin_post_id
             JOIN platforms pl ON pl.platform_id = op.platform_id
         ORDER BY w.work_id
            LIMIT ?""",
        (limit,),
    ).fetchall()
    rows = [_row(connection, record) for record in work_rows]
    selection_keys = [f"{row['work_id']}" for row in rows]
    exclusions = (
        [{"reason": "excluded_by_limit", "count": excluded_by_limit}] if excluded_by_limit else []
    )
    return ProjectionResult(rows, selection_keys, len(rows), exclusions)


def _row(connection: sqlite3.Connection, record: sqlite3.Row) -> dict[str, Any]:
    work_id = int(record["work_id"])
    representations = [
        enforce_allowlist(
            {
                "media_occurrence_id": int(rep["media_occurrence_id"]),
                "role": str(rep["role"]) if rep["role"] is not None else None,
                "verified_sha256": (
                    str(rep["verified_sha256"]) if rep["verified_sha256"] else None
                ),
            },
            REPRESENTATION_FIELDS,
        )
        for rep in connection.execute(
            """SELECT mo.media_occurrence_id, mo.role, a.verified_sha256
                 FROM work_representations wr
                 JOIN media_occurrences mo ON mo.media_occurrence_id = wr.media_occurrence_id
                 LEFT JOIN occurrence_assets oa
                   ON oa.media_occurrence_id = mo.media_occurrence_id
                  AND oa.relationship = 'exact_bytes'
                 LEFT JOIN assets a ON a.asset_id = oa.asset_id
                WHERE wr.work_id = ?
             ORDER BY mo.media_occurrence_id""",
            (work_id,),
        )
    ]
    same_work_count = int(
        connection.execute(
            """SELECT COUNT(*) FROM relationships
                WHERE relation_kind = 'same_work'
                  AND (subject_kind = 'work' AND subject_id = ?
                       OR target_kind = 'work' AND target_id = ?)""",
            (work_id, work_id),
        ).fetchone()[0]
    )
    row = {
        "work_id": work_id,
        "work_kind": str(record["work_kind"]),
        "origin_platform": str(record["origin_platform"]),
        "origin_native_post_id": str(record["origin_native_post_id"]),
        "representations": representations,
        "preferred_representation": _preferred(connection, work_id),
        "same_work_count": same_work_count,
    }
    return enforce_allowlist(row, ALLOWLIST)


def _preferred(connection: sqlite3.Connection, work_id: int) -> dict[str, Any] | None:
    """Stated policy: exclude thumbnail roles, prefer the original role, then
    the largest locally verified area, then the lowest occurrence id."""

    row = connection.execute(
        """SELECT mo.media_occurrence_id, mo.role,
                  (a.detected_width * a.detected_height) AS area
             FROM work_representations wr
             JOIN media_occurrences mo ON mo.media_occurrence_id = wr.media_occurrence_id
             LEFT JOIN occurrence_assets oa
               ON oa.media_occurrence_id = mo.media_occurrence_id
              AND oa.relationship = 'exact_bytes'
             LEFT JOIN assets a ON a.asset_id = oa.asset_id
            WHERE wr.work_id = ?
              AND (mo.role IS NULL OR mo.role NOT IN ('sample', 'preview'))
         ORDER BY (mo.role = 'original') DESC,
                  (a.detected_width * a.detected_height) DESC,
                  mo.media_occurrence_id
            LIMIT 1""",
        (work_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "media_occurrence_id": int(row["media_occurrence_id"]),
        "role": str(row["role"]) if row["role"] is not None else None,
    }
