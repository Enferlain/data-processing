"""The ``assets`` projection: one row per verified asset.

Content identity collapses exact byte-duplicates by construction (one row
per verified SHA-256); the representation-link count retains how many
catalog occurrences reference the bytes.  Emitted facts are the locally
verified side only — detected MIME/dimensions from byte inspection, never
the declared/legacy columns — and no storage location is ever emitted.
"""

from __future__ import annotations

import sqlite3

from media_catalog.projections.spec import ProjectionResult, enforce_allowlist

KIND = "assets"

ALLOWLIST = (
    "asset_id",
    "verified_sha256",
    "verified_md5",
    "phash",
    "byte_size",
    "verified_at",
    "verification_method",
    "detected_mime_type",
    "detected_width",
    "detected_height",
    "detected_frame_count",
    "representation_count",
    "legacy_assertion_count",
    "legacy_assertion_unassociated_count",
)

POLICIES = {
    "selection": "all verified assets",
    "ordering": "asset_id ascending",
    "dedup": "content_identity_by_sha256",
    "preferred_representation": "not_applicable_pending_phase_d",
    "field_source": "locally_verified_columns_only",
    "url_handling": "no_urls_emitted",
}

IDENTIFIERS = {
    "row_identifier": "asset_id",
    "content_identity": "verified_sha256",
    "evidence": "asset_id references assets; verified_sha256 is the content address",
}


def build(
    connection: sqlite3.Connection, *, limit: int, platform: str | None = None
) -> ProjectionResult:
    if platform is not None:
        raise ValueError("the assets projection does not support a platform filter")
    total = int(connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0])
    excluded_by_limit = max(0, total - limit)
    rows = [
        enforce_allowlist(dict(row), ALLOWLIST)
        for row in connection.execute(
            """SELECT a.asset_id, a.verified_sha256, a.verified_md5, a.phash,
                      a.byte_size, a.verified_at, a.verification_method,
                      a.detected_mime_type, a.detected_width, a.detected_height,
                      a.detected_frame_count,
                      (SELECT COUNT(DISTINCT oa.media_occurrence_id)
                         FROM occurrence_assets oa
                        WHERE oa.asset_id = a.asset_id) AS representation_count,
                      (SELECT COUNT(*)
                         FROM asset_legacy_assertions la
                        WHERE la.asset_id = a.asset_id) AS legacy_assertion_count,
                      (SELECT COUNT(*)
                         FROM asset_legacy_assertions la
                        WHERE la.asset_id = a.asset_id
                          AND la.associated_occurrence_id IS NULL)
                          AS legacy_assertion_unassociated_count
                 FROM assets a
             ORDER BY a.asset_id
                LIMIT ?""",
            (limit,),
        )
    ]
    selection_keys = [f"{row['asset_id']}:{row['verified_sha256']}" for row in rows]
    exclusions = (
        [{"reason": "excluded_by_limit", "count": excluded_by_limit}] if excluded_by_limit else []
    )
    return ProjectionResult(rows, selection_keys, len(rows), exclusions)
