from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from media_catalog.database import CatalogDatabase
from media_catalog.imports.common import CountMap, ImportReport, now, run_import
from media_catalog.records import (
    AccountRecord,
    AssetRecord,
    MediaOccurrenceRecord,
    PostRecord,
    RawRecord,
    normalize_timestamp,
)
from media_catalog.writer import CatalogWriter

REQUIRED_COLUMNS = {
    "accounts": {"author_id", "fetched_at", "raw_json"},
    "posts": {"post_id", "post_url", "imported_at", "fetch_status"},
    "media": {"post_id", "media_index", "media_type", "source_url"},
}


class XLikesDatabaseError(ValueError):
    def __init__(self, message: str, *, counts: CountMap | None = None) -> None:
        super().__init__(message)
        self.counts = counts


def import_x_likes_database(database: CatalogDatabase, source: Path) -> ImportReport:
    def import_records(
        writer: CatalogWriter, import_run_id: int, resolved_source: Path
    ) -> CountMap:
        connection = _open_read_only(resolved_source)
        try:
            _validate_schema(connection)
            return _import_rows(writer, connection, import_run_id, resolved_source.parent)
        finally:
            connection.close()

    return run_import(database, source, "x-likes-db", import_records)


def _open_read_only(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection
    except sqlite3.Error as error:
        raise XLikesDatabaseError("cannot open x-likes database read-only") from error


def _validate_schema(connection: sqlite3.Connection) -> None:
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    missing_tables = sorted(REQUIRED_COLUMNS.keys() - tables)
    if missing_tables:
        raise XLikesDatabaseError(
            f"unsupported x-likes schema: missing tables {', '.join(missing_tables)}"
        )
    for table, required in REQUIRED_COLUMNS.items():
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        missing = sorted(required - columns)
        if missing:
            raise XLikesDatabaseError(
                f"unsupported x-likes schema: {table} missing columns {', '.join(missing)}"
            )


def _import_rows(
    writer: CatalogWriter,
    connection: sqlite3.Connection,
    import_run_id: int,
    source_directory: Path,
) -> CountMap:
    account_rows = list(connection.execute("SELECT * FROM accounts ORDER BY author_id"))
    post_rows = list(connection.execute("SELECT * FROM posts ORDER BY post_id"))
    media_rows = list(connection.execute("SELECT * FROM media ORDER BY post_id, media_index"))
    counts = {
        "accounts": _counts(len(account_rows)),
        "posts": _counts(len(post_rows)),
        "observations": _counts(len(post_rows)),
        "media_occurrences": _counts(len(media_rows)),
        "assets": _counts(sum(1 for row in media_rows if _value(row, "sha256"))),
    }
    account_ids: dict[str, int] = {}
    for row in account_rows:
        author_id = str(row["author_id"])
        observed_at = _time(_value(row, "fetched_at"))
        raw_id = _store_legacy_raw(writer, row, "account", author_id, observed_at, import_run_id)
        result = writer.upsert_account(
            AccountRecord(
                "x",
                author_id,
                observed_at,
                canonical_url=_value(row, "profile_url"),
                handle=_value(row, "handle"),
                display_name=_value(row, "display_name"),
                bio=_value(row, "bio"),
                location=_value(row, "location"),
                website_url=_value(row, "website_url"),
                profile_url=_value(row, "profile_url"),
                avatar_url=_value(row, "avatar_url"),
                banner_url=_value(row, "banner_url"),
                followers=_value(row, "followers"),
                following=_value(row, "following"),
                verified=_bool(_value(row, "verified")),
                verification_type=_value(row, "verification_type"),
            ),
            raw_observation_id=raw_id,
        )
        account_ids[author_id] = result.id
        counts["accounts"][result.outcome] += 1

    post_ids: dict[str, int] = {}
    post_times: dict[str, str] = {}
    for row in post_rows:
        native_id = str(row["post_id"])
        observed_at = _time(_value(row, "fetched_at") or _value(row, "imported_at"))
        post_times[native_id] = observed_at
        raw_id = _store_legacy_raw(writer, row, "post", native_id, observed_at, import_run_id)
        result = writer.upsert_post(
            PostRecord(
                "x",
                native_id,
                observed_at,
                canonical_url=_value(row, "post_url"),
                text=_value(row, "post_text") or _value(row, "archive_text"),
                created_at=_optional_time(_value(row, "created_at")),
                availability=(
                    "unavailable" if _value(row, "fetch_status") == "unavailable" else "available"
                ),
                status=_value(row, "fetch_status"),
            ),
            raw_observation_id=raw_id,
        )
        post_ids[native_id] = result.id
        counts["posts"][result.outcome] += 1
        author_id = _value(row, "author_id")
        if author_id is not None and str(author_id) in account_ids:
            writer.add_participant(
                result.id, account_ids[str(author_id)], "author", raw_observation_id=raw_id
            )
        event = writer.add_observation(
            result.id,
            "liked",
            "x-likes-db",
            f"like:{native_id}",
            _time(_value(row, "imported_at")),
            import_run_id=import_run_id,
            raw_observation_id=raw_id,
        )
        counts["observations"][event.outcome] += 1

    seen_assets: set[str] = set()
    for row in media_rows:
        native_id = str(row["post_id"])
        post_id = post_ids.get(native_id)
        if post_id is None:
            raise XLikesDatabaseError(f"media references missing legacy post {native_id}")
        media_index = int(row["media_index"])
        result = writer.upsert_media(
            post_id,
            MediaOccurrenceRecord(
                f"x-likes:{media_index}",
                media_index,
                str(row["media_type"]),
                remote_url=str(row["source_url"]),
                width=_value(row, "width"),
                height=_value(row, "height"),
                alt_text=_value(row, "alt_text"),
                observed_at=post_times[native_id],
            ),
        )
        counts["media_occurrences"][result.outcome] += 1
        sha256 = _value(row, "sha256")
        if not sha256:
            continue
        normalized_sha = str(sha256).lower()
        asset_outcome = "existing" if normalized_sha in seen_assets else "inserted"
        if normalized_sha not in seen_assets:
            catalog_existing = writer.connection.execute(
                "SELECT 1 FROM assets WHERE verified_sha256 = ?", (normalized_sha,)
            ).fetchone()
            if catalog_existing is not None:
                asset_outcome = "existing"
        seen_assets.add(normalized_sha)
        local_path = _value(row, "local_path")
        writer.link_asset(
            result.id,
            AssetRecord(
                normalized_sha,
                _value(row, "md5"),
                _value(row, "phash"),
                _value(row, "file_size"),
                "legacy_reference",
                str(local_path) if local_path else None,
                post_times[native_id],
                "legacy_x_likes",
            ),
            relationship="reference",
        )
        counts["assets"][asset_outcome] += 1
        if local_path and not _legacy_path_exists(source_directory, str(local_path)):
            writer.connection.execute(
                """INSERT INTO import_diagnostics (
                       import_run_id, severity, record_key, code, message
                   ) VALUES (?, 'warning', ?, 'missing_legacy_file', ?)""",
                (
                    import_run_id,
                    f"{native_id}:{media_index}",
                    f"legacy media file is missing: {Path(str(local_path)).name}",
                ),
            )
    return counts


def _store_legacy_raw(
    writer: CatalogWriter,
    row: sqlite3.Row,
    object_kind: str,
    native_id: str,
    observed_at: str,
    import_run_id: int,
) -> int:
    raw_json = _value(row, "raw_json")
    if raw_json:
        payload = str(raw_json).encode()
    else:
        payload = json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str).encode()
    return writer.store_raw(
        RawRecord(payload, "application/json", object_kind, native_id, observed_at, "x-likes-db"),
        import_run_id=import_run_id,
    )


def _value(row: sqlite3.Row, name: str) -> object | None:
    try:
        return row[name]
    except IndexError:
        return None


def _bool(value: object) -> bool | None:
    return None if value is None else bool(value)


def _time(value: object) -> str:
    if isinstance(value, str) and value:
        return normalize_timestamp(value)
    return now()


def _optional_time(value: object) -> str | None:
    return _time(value) if isinstance(value, str) and value else None


def _legacy_path_exists(source_directory: Path, value: str) -> bool:
    path = Path(value)
    if not path.is_absolute():
        path = source_directory / path
    return path.is_file()


def _counts(source: int) -> dict[str, int]:
    return {
        key: source if key == "source" else 0
        for key in ("source", "inserted", "updated", "existing", "skipped", "failed")
    }
