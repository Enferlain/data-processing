"""Read-only, redacted browsing of normalized media occurrences."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from media_catalog.acquisition.planning import (
    AcquisitionSelection,
    evaluate_occurrence_variant,
    resolve_occurrence_variants,
)
from media_catalog.database import CatalogDatabase

DatabaseSource = CatalogDatabase | Path | str

MAX_PAGE_SIZE = 200
MAX_RELATED_ITEMS = 100


def _connection(database: DatabaseSource) -> sqlite3.Connection:
    if isinstance(database, CatalogDatabase):
        snapshot = sqlite3.connect(":memory:")
        snapshot.row_factory = sqlite3.Row
        try:
            database.connection.backup(snapshot)
            snapshot.execute("PRAGMA query_only = ON")
        except BaseException:
            snapshot.close()
            raise
        return snapshot
    return CatalogDatabase.open_read_only(Path(database)).connection


def _bounded_text(value: str | None, name: str, *, maximum: int = 500) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum} characters")
    return normalized


def _stable_reference(value: str, name: str) -> tuple[str, str]:
    platform, separator, native_id = value.partition(":")
    if not separator or not platform or not native_id:
        raise ValueError(f"{name} must use PLATFORM:NATIVE_ID")
    if len(platform) > 200 or len(native_id) > 500:
        raise ValueError(f"{name} is too long")
    return platform, native_id


def _variant_projection(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[list[dict[str, Any]], int, bool]:
    variants, _variant_error = resolve_occurrence_variants(dict(row))
    keys = sorted(variants) or ["primary"]
    total = len(keys)
    shown = keys[:MAX_RELATED_ITEMS]
    projected: list[dict[str, Any]] = []
    for key in shown:
        item = evaluate_occurrence_variant(
            connection,
            AcquisitionSelection(int(row["media_occurrence_id"]), key),
        )
        projected.append(
            {
                "key": key,
                "selection": f"{row['media_occurrence_id']}:{key}",
                "request_policy_key": (item.request_policy.key if item.request_policy else None),
                "request_policy_version": (
                    item.request_policy.version if item.request_policy else None
                ),
                "eligibility": item.eligibility,
                "exclusion_reason": item.exclusion_reason,
                "satisfied_asset_id": item.satisfied_asset_id,
            }
        )
    return projected, total, total > len(shown)


def _occurrence_projection(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, Any]:
    variants, variant_count, variants_truncated = _variant_projection(connection, row)
    return {
        "media_occurrence_id": int(row["media_occurrence_id"]),
        "post": {
            "post_id": int(row["post_id"]),
            "platform": str(row["platform_key"]),
            "native_post_id": str(row["native_post_id"]),
            "availability": str(row["post_availability"]),
        },
        "source_key": str(row["source_key"]),
        "media_index": int(row["media_index"]),
        "media_type": str(row["media_type"]),
        "role": row["role"],
        "availability": str(row["availability"]),
        "observed_at": str(row["observed_at"]),
        "declared": {
            "sha256": row["declared_sha256"],
            "md5": row["declared_md5"],
            "file_size": row["declared_file_size"],
            "mime_type": row["mime_type"],
            "width": row["width"],
            "height": row["height"],
        },
        "raw_observation_id": row["raw_observation_id"],
        "linked": int(row["asset_count"]) > 0,
        "asset_count": int(row["asset_count"]),
        "variants": variants,
        "variant_count": variant_count,
        "variants_truncated": variants_truncated,
    }


def _base_select() -> str:
    return """SELECT mo.*, p.native_post_id, p.availability AS post_availability,
                     platform.platform_key,
                     (SELECT COUNT(*) FROM occurrence_assets oa
                       WHERE oa.media_occurrence_id = mo.media_occurrence_id) AS asset_count
                FROM media_occurrences mo
                JOIN posts p USING(post_id)
                JOIN platforms platform ON platform.platform_id = p.platform_id"""


def list_media_occurrences(
    database: DatabaseSource,
    *,
    platform: str | None = None,
    author: str | None = None,
    post: int | str | None = None,
    availability: str | None = None,
    linked: bool | None = None,
    expansion_plan_id: int | None = None,
    limit: int = 100,
    after: int | None = None,
) -> dict[str, Any]:
    """Return one bounded, redacted row per occurrence in stable ID order."""

    if limit <= 0 or limit > MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if after is not None and after < 0:
        raise ValueError("after must not be negative")
    if expansion_plan_id is not None and expansion_plan_id <= 0:
        raise ValueError("expansion plan id must be positive")
    platform = _bounded_text(platform, "platform", maximum=200)
    availability = _bounded_text(availability, "availability", maximum=100)
    author_parts = _stable_reference(author, "author") if author is not None else None
    post_id: int | None = None
    post_parts: tuple[str, str] | None = None
    if post is not None:
        if isinstance(post, int) or (isinstance(post, str) and post.isdecimal()):
            post_id = int(post)
            if post_id <= 0:
                raise ValueError("post id must be positive")
        elif isinstance(post, str):
            post_parts = _stable_reference(post, "post")
        else:
            raise ValueError("post must be a positive id or PLATFORM:NATIVE_ID")

    clauses = ["mo.media_occurrence_id > ?"]
    values: list[object] = [after or 0]
    if platform is not None:
        clauses.append("platform.platform_key = ?")
        values.append(platform)
    if author_parts is not None:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM post_participants pp
                JOIN accounts author_account USING(account_id)
                JOIN platforms author_platform
                  ON author_platform.platform_id = author_account.platform_id
                WHERE pp.post_id = p.post_id AND pp.role = 'author'
                  AND author_platform.platform_key = ?
                  AND author_account.native_account_id = ?
            )"""
        )
        values.extend(author_parts)
    if post_id is not None:
        clauses.append("p.post_id = ?")
        values.append(post_id)
    elif post_parts is not None:
        clauses.extend(("platform.platform_key = ?", "p.native_post_id = ?"))
        values.extend(post_parts)
    if availability is not None:
        clauses.append("mo.availability = ?")
        values.append(availability)
    if linked is not None:
        predicate = "EXISTS" if linked else "NOT EXISTS"
        clauses.append(
            f"""{predicate} (
                SELECT 1 FROM occurrence_assets linked_asset
                WHERE linked_asset.media_occurrence_id = mo.media_occurrence_id
            )"""
        )
    if expansion_plan_id is not None:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM library_expansion_posts expansion_post
                JOIN library_expansion_executions expansion_execution
                  USING(library_expansion_execution_id)
                WHERE expansion_post.post_id = p.post_id
                  AND expansion_execution.library_expansion_plan_id = ?
            )"""
        )
        values.append(expansion_plan_id)
    values.append(limit + 1)

    connection = _connection(database)
    try:
        rows = list(
            connection.execute(
                _base_select()
                + " WHERE "
                + " AND ".join(clauses)
                + " ORDER BY mo.media_occurrence_id LIMIT ?",
                values,
            )
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        results = [_occurrence_projection(connection, row) for row in page]
        continuation = int(page[-1]["media_occurrence_id"]) if has_more and page else None
        return {
            "filters": {
                "platform": platform,
                "author": author,
                "post": post,
                "availability": availability,
                "linked": linked,
                "expansion_plan_id": expansion_plan_id,
            },
            "limit": limit,
            "after": after,
            "continuation": continuation,
            "has_more": has_more,
            "count": len(results),
            "results": results,
        }
    finally:
        connection.close()


def _authors(connection: sqlite3.Connection, post_id: int) -> dict[str, Any]:
    rows = list(
        connection.execute(
            """SELECT pp.account_id, pp.role, pp.confidence, pp.review_state,
                      pp.raw_observation_id, platform.platform_key,
                      account.native_account_id, account.availability,
                      snapshot.handle, snapshot.display_name
                 FROM post_participants pp
                 JOIN accounts account USING(account_id)
                 JOIN platforms platform ON platform.platform_id = account.platform_id
            LEFT JOIN account_snapshots snapshot
                   ON snapshot.account_snapshot_id = (
                       SELECT candidate.account_snapshot_id
                         FROM account_snapshots candidate
                        WHERE candidate.account_id = account.account_id
                        ORDER BY candidate.observed_at DESC,
                                 candidate.account_snapshot_id DESC LIMIT 1
                   )
                WHERE pp.post_id = ? AND pp.role = 'author'
                ORDER BY pp.account_id LIMIT ?""",
            (post_id, MAX_RELATED_ITEMS + 1),
        )
    )
    return {
        "count": len(rows),
        "truncated": len(rows) > MAX_RELATED_ITEMS,
        "results": [
            {
                "account_id": int(row["account_id"]),
                "platform": str(row["platform_key"]),
                "native_account_id": str(row["native_account_id"]),
                "role": str(row["role"]),
                "availability": str(row["availability"]),
                "confidence": row["confidence"],
                "review_state": str(row["review_state"]),
                "raw_observation_id": row["raw_observation_id"],
                "handle": row["handle"],
                "display_name": row["display_name"],
            }
            for row in rows[:MAX_RELATED_ITEMS]
        ],
    }


def _assets(connection: sqlite3.Connection, occurrence_id: int) -> dict[str, Any]:
    rows = list(
        connection.execute(
            """SELECT oa.asset_id, oa.relationship, oa.verification_source,
                      asset.verified_sha256, asset.verified_md5, asset.byte_size,
                      asset.storage_kind, asset.verified_at, asset.verification_method,
                      asset.detected_mime_type, asset.detected_width,
                      asset.detected_height, asset.detected_frame_count
                 FROM occurrence_assets oa JOIN assets asset USING(asset_id)
                WHERE oa.media_occurrence_id = ?
                ORDER BY oa.asset_id, oa.relationship LIMIT ?""",
            (occurrence_id, MAX_RELATED_ITEMS + 1),
        )
    )
    selected = rows[:MAX_RELATED_ITEMS]
    asset_ids = sorted({int(row["asset_id"]) for row in selected})
    fingerprints: dict[int, list[dict[str, Any]]] = defaultdict(list)
    fingerprint_truncated: dict[int, bool] = {}
    for asset_id in asset_ids:
        fingerprint_rows = list(
            connection.execute(
                """SELECT fingerprint_kind, fingerprint_value, algorithm,
                          algorithm_version, verification_status, observed_at
                     FROM asset_fingerprints WHERE asset_id = ?
                    ORDER BY asset_fingerprint_id LIMIT ?""",
                (asset_id, MAX_RELATED_ITEMS + 1),
            )
        )
        fingerprint_truncated[asset_id] = len(fingerprint_rows) > MAX_RELATED_ITEMS
        for fingerprint in fingerprint_rows[:MAX_RELATED_ITEMS]:
            fingerprints[asset_id].append(
                {
                    "kind": str(fingerprint["fingerprint_kind"]),
                    "value": str(fingerprint["fingerprint_value"]),
                    "algorithm": str(fingerprint["algorithm"]),
                    "algorithm_version": str(fingerprint["algorithm_version"]),
                    "verification_status": str(fingerprint["verification_status"]),
                    "observed_at": str(fingerprint["observed_at"]),
                }
            )
    return {
        "count": len(rows),
        "truncated": len(rows) > MAX_RELATED_ITEMS,
        "results": [
            {
                "asset_id": int(row["asset_id"]),
                "relationship": str(row["relationship"]),
                "verification_source": str(row["verification_source"]),
                "verified": {
                    "sha256": str(row["verified_sha256"]),
                    "md5": row["verified_md5"],
                    "byte_size": row["byte_size"],
                    "storage_kind": str(row["storage_kind"]),
                    "verified_at": row["verified_at"],
                    "verification_method": str(row["verification_method"]),
                    "detected_mime_type": row["detected_mime_type"],
                    "detected_width": row["detected_width"],
                    "detected_height": row["detected_height"],
                    "detected_frame_count": row["detected_frame_count"],
                },
                "fingerprints": fingerprints[int(row["asset_id"])][:MAX_RELATED_ITEMS],
                "fingerprints_truncated": fingerprint_truncated[int(row["asset_id"])],
            }
            for row in selected
        ],
    }


def _sources(connection: sqlite3.Connection, occurrence_id: int) -> dict[str, Any]:
    rows = list(
        connection.execute(
            """SELECT occurrence_source_id, source_kind, managed_root_id, recorded_at
                 FROM occurrence_sources WHERE media_occurrence_id = ?
                 ORDER BY occurrence_source_id LIMIT ?""",
            (occurrence_id, MAX_RELATED_ITEMS + 1),
        )
    )
    return {
        "count": len(rows),
        "truncated": len(rows) > MAX_RELATED_ITEMS,
        "results": [dict(row) for row in rows[:MAX_RELATED_ITEMS]],
    }


def get_media_occurrence(
    database: DatabaseSource,
    media_occurrence_id: int,
) -> dict[str, Any] | None:
    """Return bounded occurrence detail without URLs, raw payloads, or paths."""

    if media_occurrence_id <= 0:
        raise ValueError("media occurrence id must be positive")
    connection = _connection(database)
    try:
        row = connection.execute(
            _base_select() + " WHERE mo.media_occurrence_id = ?",
            (media_occurrence_id,),
        ).fetchone()
        if row is None:
            return None
        occurrence = _occurrence_projection(connection, row)
        return {
            "occurrence": occurrence,
            "authors": _authors(connection, int(row["post_id"])),
            "assets": _assets(connection, media_occurrence_id),
            "sources": _sources(connection, media_occurrence_id),
        }
    finally:
        connection.close()


class MediaQueryService:
    """Small public facade for offline occurrence browsing."""

    def __init__(self, database: DatabaseSource) -> None:
        self.database = database

    def list(
        self,
        *,
        platform: str | None = None,
        author: str | None = None,
        post: int | str | None = None,
        availability: str | None = None,
        linked: bool | None = None,
        expansion_plan_id: int | None = None,
        limit: int = 100,
        after: int | None = None,
    ) -> dict[str, Any]:
        return list_media_occurrences(
            self.database,
            platform=platform,
            author=author,
            post=post,
            availability=availability,
            linked=linked,
            expansion_plan_id=expansion_plan_id,
            limit=limit,
            after=after,
        )

    def show(self, media_occurrence_id: int) -> dict[str, Any] | None:
        return get_media_occurrence(self.database, media_occurrence_id)


__all__ = [
    "MAX_PAGE_SIZE",
    "MAX_RELATED_ITEMS",
    "MediaQueryService",
    "get_media_occurrence",
    "list_media_occurrences",
]
