"""Read-only inspection queries for managed assets and adoption history."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from media_catalog.database import CatalogDatabase


def _redact_row_paths(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("storage_path", "private_path"):
        value = row.get(key)
        if isinstance(value, str) and value.startswith("/"):
            row[key] = "<redacted>"
    return row


def _connection(database: CatalogDatabase | Path | str) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, CatalogDatabase):
        snapshot = sqlite3.connect(":memory:")
        snapshot.row_factory = sqlite3.Row
        try:
            database.connection.backup(snapshot)
            snapshot.execute("PRAGMA query_only = ON")
        except BaseException:
            snapshot.close()
            raise
        return snapshot, True
    opened = CatalogDatabase.open_read_only(Path(database))
    return opened.connection, True


def _close_connection(connection: sqlite3.Connection, owned: bool) -> None:
    if owned:
        connection.close()

def list_assets(
    database: CatalogDatabase | Path | str,
    *,
    sha256: str | None = None,
    asset_id: int | None = None,
) -> list[dict[str, Any]]:
    """Read public asset metadata and managed locations.

    ``assets.storage_path`` predates occurrence-level provenance and may contain
    a private legacy filename or an arbitrary relative path.  It is deliberately
    omitted from this default query; legacy assertions are represented only by
    bounded counts/classification fields and the detail query's redacted
    assertion metadata.
    """

    connection, owned = _connection(database)
    try:
        clauses: list[str] = []
        values: list[Any] = []
        if sha256 is not None:
            clauses.append("a.verified_sha256 = ?")
            values.append(sha256.lower())
        if asset_id is not None:
            clauses.append("a.asset_id = ?")
            values.append(asset_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = connection.execute(
            f"""SELECT a.asset_id, a.verified_sha256, a.verified_md5, a.phash,
                              a.byte_size, a.mime_type, a.width, a.height, a.storage_kind,
                              a.verified_at, a.verification_method,
                              a.detected_mime_type, a.detected_width, a.detected_height,
                              a.detected_frame_count,
                              (SELECT COUNT(*) FROM asset_legacy_assertions la
                                WHERE la.asset_id = a.asset_id) AS legacy_assertion_count,
                              (SELECT COUNT(*) FROM asset_legacy_assertions la
                                WHERE la.asset_id = a.asset_id
                                  AND la.associated_occurrence_id IS NULL)
                                AS legacy_assertion_unassociated_count,
                              (SELECT MIN(la.assertion_kind) FROM asset_legacy_assertions la
                                WHERE la.asset_id = a.asset_id)
                                AS legacy_assertion_classification,
                              l.asset_location_id, l.managed_root_id, l.relative_path,
                              l.location_kind, l.byte_size AS location_byte_size,
                              l.recorded_sha256, r.display_label AS root_label
                         FROM assets a
                    LEFT JOIN asset_locations l ON l.asset_id = a.asset_id
                        AND l.location_kind <> 'legacy'
                    LEFT JOIN managed_roots r ON r.managed_root_id = l.managed_root_id
                        {where}
                     ORDER BY a.asset_id, l.asset_location_id""",
            values,
        )
        return [_redact_row_paths(dict(row)) for row in rows]
    finally:
        _close_connection(connection, owned)


def legacy_assertion_summary(
    database: CatalogDatabase | Path | str,
) -> dict[str, Any]:
    """Return bounded counts/classification for migrated legacy asset paths.

    The summary intentionally never returns ``legacy_path`` values.  It is safe
    for default list/show output and gives callers a stable way to explain the
    migration's ambiguous and currently unassociated assertions.
    """

    connection, owned = _connection(database)
    try:
        rows = list(
            connection.execute(
                """SELECT assertion_kind,
                              COUNT(*) AS count,
                              SUM(CASE WHEN associated_occurrence_id IS NULL THEN 1 ELSE 0 END)
                                AS unassociated_count
                         FROM asset_legacy_assertions
                     GROUP BY assertion_kind ORDER BY assertion_kind"""
            )
        )
        by_classification = {
            str(row["assertion_kind"]): int(row["count"]) for row in rows
        }
        return {
            "total": sum(by_classification.values()),
            "ambiguous": sum(
                count
                for kind, count in by_classification.items()
                if kind == "ambiguous_asset_path"
            ),
            "unassociated": sum(int(row["unassociated_count"] or 0) for row in rows),
            "by_classification": by_classification,
        }
    finally:
        _close_connection(connection, owned)


def get_asset(
    database: CatalogDatabase | Path | str, identifier: int | str
) -> dict[str, Any] | None:
    rows = list_assets(
        database,
        asset_id=identifier if isinstance(identifier, int) else None,
        sha256=identifier if isinstance(identifier, str) else None,
    )
    return rows[0] if rows else None


def get_asset_detail(
    database: CatalogDatabase | Path | str, identifier: int | str
) -> dict[str, Any] | None:
    """Return one asset with its locations, fingerprints, and occurrences."""

    asset = get_asset(database, identifier)
    if asset is None:
        return None
    asset_id = int(asset["asset_id"])
    connection, owned = _connection(database)
    try:
        locations = [
            dict(row)
            for row in connection.execute(
                """SELECT l.*, r.display_label AS root_label
                            FROM asset_locations l
                        LEFT JOIN managed_roots r ON r.managed_root_id = l.managed_root_id
                            WHERE l.asset_id = ? AND l.location_kind <> 'legacy'
                         ORDER BY l.asset_location_id""",
                (asset_id,),
            )
        ]
        legacy_assertions = [
            {
                "asset_legacy_assertion_id": row["asset_legacy_assertion_id"],
                "asset_id": row["asset_id"],
                "assertion_kind": row["assertion_kind"],
                "associated_occurrence_id": row["associated_occurrence_id"],
                "recorded_at": row["recorded_at"],
            }
            for row in connection.execute(
                """SELECT asset_legacy_assertion_id, asset_id, assertion_kind,
                                  associated_occurrence_id, recorded_at
                             FROM asset_legacy_assertions
                            WHERE asset_id = ? ORDER BY asset_legacy_assertion_id""",
                (asset_id,),
            )
        ]
        fingerprints = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM asset_fingerprints WHERE asset_id = ? "
                "ORDER BY asset_fingerprint_id",
                (asset_id,),
            )
        ]
        occurrences = [
            dict(row)
            for row in connection.execute(
                """SELECT oa.media_occurrence_id, oa.relationship, oa.verification_source,
                                  m.post_id, m.source_key, m.media_index
                             FROM occurrence_assets oa
                             JOIN media_occurrences m
                               ON m.media_occurrence_id = oa.media_occurrence_id
                            WHERE oa.asset_id = ? ORDER BY oa.media_occurrence_id""",
                (asset_id,),
            )
        ]
        return {
            "asset": asset,
            "locations": locations,
            "legacy_assertions": legacy_assertions,
            "fingerprints": fingerprints,
            "occurrences": occurrences,
        }
    finally:
        _close_connection(connection, owned)


def list_adoption_runs(
    database: CatalogDatabase | Path | str, *, status: str | None = None
) -> list[dict[str, Any]]:
    connection, owned = _connection(database)
    try:
        if status is None:
            rows = connection.execute("SELECT * FROM adoption_runs ORDER BY adoption_run_id DESC")
        else:
            rows = connection.execute(
                "SELECT * FROM adoption_runs WHERE status = ? ORDER BY adoption_run_id DESC",
                (status,),
            )
        return [dict(row) for row in rows]
    finally:
        _close_connection(connection, owned)


def get_adoption_run(
    database: CatalogDatabase | Path | str, run_id: int
) -> dict[str, Any] | None:
    connection, owned = _connection(database)
    try:
        run = connection.execute(
            "SELECT * FROM adoption_runs WHERE adoption_run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            return None
        items = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM adoption_items WHERE adoption_run_id = ? "
                "ORDER BY adoption_item_id",
                (run_id,),
            )
        ]
        attempts = [
            dict(row)
            for row in connection.execute(
                """SELECT aa.* FROM adoption_attempts aa
                         JOIN adoption_items ai ON ai.adoption_item_id = aa.adoption_item_id
                        WHERE ai.adoption_run_id = ?
                        ORDER BY aa.adoption_attempt_id""",
                (run_id,),
            )
        ]
        return {"run": dict(run), "items": items, "attempts": attempts}
    finally:
        _close_connection(connection, owned)


def list_failed_adoption_items(
    database: CatalogDatabase | Path | str, *, run_id: int | None = None
) -> list[dict[str, Any]]:
    connection, owned = _connection(database)
    try:
        if run_id is None:
            rows = connection.execute(
                "SELECT * FROM adoption_items "
                "WHERE outcome NOT IN ('adopted','adopted_exact_only','existing') "
                "ORDER BY adoption_item_id"
            )
        else:
            rows = connection.execute(
                "SELECT * FROM adoption_items WHERE adoption_run_id = ? "
                "AND outcome NOT IN ('adopted','adopted_exact_only','existing') "
                "ORDER BY adoption_item_id",
                (run_id,),
            )
        return [dict(row) for row in rows]
    finally:
        _close_connection(connection, owned)


def find_exact_duplicates(database: CatalogDatabase | Path | str) -> list[dict[str, Any]]:
    """Return assets referenced by more than one media occurrence."""

    connection, owned = _connection(database)
    try:
        rows = connection.execute(
            """SELECT a.verified_sha256 AS sha256, a.asset_id,
                      COUNT(DISTINCT oa.media_occurrence_id) AS occurrence_count,
                      GROUP_CONCAT(DISTINCT oa.media_occurrence_id) AS occurrence_ids
                 FROM assets a JOIN occurrence_assets oa ON oa.asset_id = a.asset_id
             GROUP BY a.asset_id, a.verified_sha256
               HAVING COUNT(DISTINCT oa.media_occurrence_id) > 1
             ORDER BY a.asset_id"""
        )
        return [dict(row) for row in rows]
    finally:
        _close_connection(connection, owned)


class AssetQueryService:
    """Convenience object for read-only asset/run inspection."""

    def __init__(self, database: CatalogDatabase | Path | str) -> None:
        self.database = database

    def assets(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list_assets(self.database, **kwargs)

    def legacy_assertion_summary(self) -> dict[str, Any]:
        return legacy_assertion_summary(self.database)

    def asset(self, identifier: int | str) -> dict[str, Any] | None:
        return get_asset(self.database, identifier)

    def asset_detail(self, identifier: int | str) -> dict[str, Any] | None:
        return get_asset_detail(self.database, identifier)

    def runs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list_adoption_runs(self.database, **kwargs)

    def run(self, run_id: int) -> dict[str, Any] | None:
        return get_adoption_run(self.database, run_id)

    def failures(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list_failed_adoption_items(self.database, **kwargs)

    def exact_duplicates(self) -> list[dict[str, Any]]:
        return find_exact_duplicates(self.database)


__all__ = [
    "AssetQueryService",
    "find_exact_duplicates",
    "get_adoption_run",
    "get_asset",
    "get_asset_detail",
    "legacy_assertion_summary",
    "list_adoption_runs",
    "list_assets",
    "list_failed_adoption_items",
]
