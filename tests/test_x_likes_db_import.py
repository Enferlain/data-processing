from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.imports.x_likes_db import XLikesDatabaseError, import_x_likes_database
from x_likes.database import SCHEMA

NOW = "2026-08-05T00:00:00Z"


def _create_legacy_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            """INSERT INTO accounts (
                   author_id, handle, display_name, bio, profile_url, avatar_url, banner_url,
                   location, website_url, followers, following, verified, verification_type,
                   fetched_at, raw_json
               ) VALUES ('7', 'artist', 'Artist', 'bio', 'https://x.com/artist', NULL, NULL,
                         NULL, 'https://artist.example', 10, 2, 1, 'blue', ?, ?)""",
            (NOW, json.dumps({"account_unknown": True})),
        )
        connection.execute(
            """INSERT INTO posts (
                   post_id, post_url, archive_text, author_id, author_handle, author_name,
                   post_text, created_at, imported_at, fetched_at, fetch_provider, fetch_status,
                   unavailable_reason, raw_json
               ) VALUES ('42', 'https://x.com/artist/status/42', 'archive text', '7', 'artist',
                         'Artist', 'post text', ?, ?, ?, 'fxtwitter', 'fetched', NULL, ?)""",
            (NOW, NOW, NOW, json.dumps({"post_unknown": True})),
        )
        connection.execute(
            """INSERT INTO posts (
                   post_id, post_url, archive_text, imported_at, fetched_at, fetch_provider,
                   fetch_status, unavailable_reason, raw_json
               ) VALUES ('43', 'https://x.com/i/status/43', NULL, ?, ?, 'fxtwitter',
                         'unavailable', 'deleted', ?)""",
            (NOW, NOW, json.dumps({"type": "tombstone"})),
        )
        connection.execute(
            """INSERT INTO media (
                   post_id, media_index, media_type, source_url, local_path, width, height,
                   alt_text, file_size, md5, sha256, phash
               ) VALUES ('42', 0, 'image', 'https://example.test/image.jpg',
                         'media/missing.jpg', 100, 200, 'alt', 123, ?, ?, ?)""",
            ("B" * 32, "A" * 64, "0123456789abcdef"),
        )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_x_likes_database_import_is_read_only_complete_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "likes.sqlite3"
    _create_legacy_database(source)
    before = _digest(source)
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        first = import_x_likes_database(database, source)
        second = import_x_likes_database(database, source)
        assert first.reused is False
        assert second.reused is True
        assert database.summary()["accounts"] == 1
        assert database.summary()["posts"] == 2
        assert database.stats(event_type="liked")["matching_posts"] == 2
        assert database.summary()["media_occurrences"] == 1
        assert database.summary()["assets"] == 1
        asset = database.connection.execute(
            """SELECT verified_sha256, verified_md5, storage_kind, verification_method
               FROM assets"""
        ).fetchone()
        assert tuple(asset) == (
            "a" * 64,
            "b" * 32,
            "legacy_reference",
            "legacy_x_likes",
        )
        assert (
            database.connection.execute("SELECT relationship FROM occurrence_assets").fetchone()[0]
            == "reference"
        )
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM import_diagnostics WHERE code = 'missing_legacy_file'"
            ).fetchone()[0]
            == 1
        )
        unavailable = database.connection.execute(
            "SELECT availability, status FROM posts WHERE native_post_id = '43'"
        ).fetchone()
        assert tuple(unavailable) == ("unavailable", "unavailable")
    assert _digest(source) == before


def test_x_likes_database_rejects_unsupported_schema_without_source_writes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "wrong.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
    before = _digest(source)
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with pytest.raises(XLikesDatabaseError, match="missing tables"):
            import_x_likes_database(database, source)
        assert database.summary()["posts"] == 0
        assert (
            database.connection.execute("SELECT status FROM import_runs").fetchone()[0] == "failed"
        )
    assert _digest(source) == before
