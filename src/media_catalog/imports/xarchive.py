from __future__ import annotations

import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, cast

from media_catalog.database import CatalogDatabase
from media_catalog.imports.common import CountMap, ImportReport, now, run_import
from media_catalog.records import AccountRecord, MediaOccurrenceRecord, PostRecord, RawRecord
from media_catalog.writer import CatalogWriter


class XArchiveError(ValueError):
    def __init__(self, message: str, *, counts: CountMap | None = None) -> None:
        super().__init__(message)
        self.counts = counts


def import_xarchive(database: CatalogDatabase, source: Path) -> ImportReport:
    def import_records(
        writer: CatalogWriter, import_run_id: int, resolved_source: Path
    ) -> CountMap:
        try:
            root = json.loads(resolved_source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise XArchiveError("cannot read xarchive JSON") from error
        if not isinstance(root, dict) or not isinstance(root.get("bookmarks"), list):
            raise XArchiveError("unsupported xarchive schema: expected a bookmarks array")
        metadata = root.get("export_metadata")
        exported_at = _timestamp(
            metadata.get("exported_at") if isinstance(metadata, dict) else None
        )
        counts: CountMap = {
            "posts": _counts(len(root["bookmarks"])),
            "accounts": _counts(0),
            "observations": _counts(len(root["bookmarks"])),
            "media_occurrences": _counts(0),
            "related_posts": _counts(0),
        }
        account_outcomes: dict[str, str] = {}
        try:
            for index, bookmark in enumerate(root["bookmarks"]):
                if not isinstance(bookmark, dict):
                    raise XArchiveError(f"bookmark[{index}] must be an object")
                tweet_id = bookmark.get("tweet_id")
                if not isinstance(tweet_id, str) or not tweet_id.strip():
                    raise XArchiveError(f"bookmark[{index}] is missing tweet_id")
                if tweet_id != tweet_id.strip():
                    raise XArchiveError(f"bookmark[{index}].tweet_id has surrounding whitespace")
                _import_bookmark(
                    writer,
                    import_run_id,
                    bookmark,
                    index,
                    tweet_id,
                    exported_at,
                    counts,
                    account_outcomes,
                )
        except XArchiveError as error:
            counts["posts"]["failed"] += 1
            error.counts = counts
            raise
        counts["accounts"]["source"] = len(account_outcomes)
        for outcome in account_outcomes.values():
            counts["accounts"][outcome] += 1
        return counts

    return run_import(database, source, "xarchive", import_records)


def _import_bookmark(
    writer: CatalogWriter,
    import_run_id: int,
    bookmark: dict[str, object],
    index: int,
    tweet_id: str,
    exported_at: str,
    counts: CountMap,
    account_outcomes: dict[str, str],
) -> None:
    raw = json.dumps(bookmark, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    raw_id = writer.store_raw(
        RawRecord(raw, "application/json", "post", tweet_id, exported_at, "xarchive"),
        import_run_id=import_run_id,
    )
    author_value = bookmark.get("author")
    author = cast(dict[str, Any], author_value) if isinstance(author_value, dict) else {}
    author_id = _string(author.get("user_id"))
    handle = _real_handle(_string(author.get("screen_name")), author_id)
    display_name = _real_name(_string(author.get("name")), author_id)
    account_id = None
    if author_id is not None:
        account_result = writer.upsert_account(
            AccountRecord(
                "x",
                author_id,
                exported_at,
                canonical_url=f"https://x.com/{handle}" if handle else None,
                handle=handle,
                display_name=display_name,
                bio=_string(author.get("description")),
                location=_string(author.get("location")),
                website_url=_string(author.get("url")),
                profile_url=_string(author.get("profile_url")),
                avatar_url=_string(author.get("profile_image_url")),
                banner_url=_string(author.get("profile_banner_url")),
                followers=_integer(author.get("followers_count")),
                following=_integer(author.get("following_count")),
                verified=(
                    author.get("verified") if isinstance(author.get("verified"), bool) else None
                ),
            ),
            raw_observation_id=raw_id,
        )
        account_id = account_result.id
        account_outcomes.setdefault(author_id, account_result.outcome)
    post_result = writer.upsert_post(
        PostRecord(
            "x",
            tweet_id,
            exported_at,
            canonical_url=(
                f"https://x.com/{handle}/status/{tweet_id}"
                if handle
                else f"https://x.com/i/status/{tweet_id}"
            ),
            text=_string(bookmark.get("full_text")),
            language=_string(bookmark.get("lang")),
            created_at=_optional_timestamp(bookmark, "created_at", index=index),
            availability=_string(bookmark.get("status")) or "available",
        ),
        raw_observation_id=raw_id,
    )
    post_id = post_result.id
    counts["posts"][post_result.outcome] += 1
    if account_id is not None:
        writer.add_participant(post_id, account_id, "author", raw_observation_id=raw_id)
    folders = bookmark.get("folders")
    collection = json.dumps(folders, ensure_ascii=False) if folders else None
    observation_result = writer.add_observation(
        post_id,
        "bookmarked",
        "xarchive",
        f"bookmark:{tweet_id}",
        exported_at,
        import_run_id=import_run_id,
        raw_observation_id=raw_id,
        collection_data=collection,
    )
    counts["observations"][observation_result.outcome] += 1
    media = bookmark.get("media")
    if media is None:
        media = []
    if not isinstance(media, list):
        raise XArchiveError(f"bookmark[{index}].media must be an array")
    counts["media_occurrences"]["source"] += len(media)
    for media_index, item in enumerate(media):
        if not isinstance(item, dict):
            raise XArchiveError(f"bookmark[{index}].media[{media_index}] must be an object")
        variants = item.get("variants")
        variants_json = (
            json.dumps(variants, ensure_ascii=False, sort_keys=True)
            if variants is not None
            else None
        )
        media_result = writer.upsert_media(
            post_id,
            MediaOccurrenceRecord(
                f"xarchive:{media_index}",
                media_index,
                _string(item.get("type")) or "unknown",
                remote_url=_string(item.get("url")),
                preview_url=_string(item.get("thumbnail_url")),
                width=_integer(item.get("width")),
                height=_integer(item.get("height")),
                duration_ms=_integer(item.get("duration_ms")),
                variants_json=variants_json,
                alt_text=_string(item.get("alt_text")),
                observed_at=exported_at,
            ),
            raw_observation_id=raw_id,
        )
        counts["media_occurrences"][media_result.outcome] += 1
    _add_relation(
        writer,
        post_id,
        bookmark.get("in_reply_to_tweet_id"),
        "reply",
        exported_at,
        raw_id,
        counts,
    )
    quoted = bookmark.get("quoted_tweet")
    if isinstance(quoted, dict):
        _add_relation(
            writer,
            post_id,
            quoted.get("tweet_id"),
            "quote",
            exported_at,
            raw_id,
            counts,
        )


def _add_relation(
    writer: CatalogWriter,
    source_post_id: int,
    target_native_id: object,
    relation_type: str,
    observed_at: str,
    raw_id: int,
    counts: CountMap,
) -> None:
    target_id = _string(target_native_id)
    if target_id is None:
        return
    result = writer.upsert_post(PostRecord("x", target_id, observed_at))
    counts["related_posts"]["source"] += 1
    counts["related_posts"][result.outcome] += 1
    writer.add_relation(source_post_id, result.id, relation_type, raw_observation_id=raw_id)


def _counts(source: int) -> dict[str, int]:
    return {
        key: source if key == "source" else 0
        for key in ("source", "inserted", "updated", "existing", "skipped", "failed")
    }


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value:
        return now()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            raise XArchiveError(f"invalid timestamp: {value!r}") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _optional_timestamp(record: dict[str, object], key: str, *, index: int) -> str | None:
    if key not in record or record[key] is None:
        return None
    value = record[key]
    if not isinstance(value, str) or not value:
        raise XArchiveError(f"bookmark[{index}].{key} must be a timestamp string")
    try:
        return _timestamp(value)
    except XArchiveError as error:
        raise XArchiveError(f"bookmark[{index}].{key}: {error}") from error


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _real_handle(value: str | None, user_id: str | None) -> str | None:
    return None if user_id is not None and value == f"user_{user_id}" else value


def _real_name(value: str | None, user_id: str | None) -> str | None:
    return None if user_id is not None and value == f"User {user_id}" else value
