from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase, SchemaVersionError, current_schema_version


def test_fresh_catalog_applies_current_migration(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        assert database.schema_version == current_schema_version() == 2
        assert database.summary()["platforms"] == 6
        assert database.doctor()["ok"] is True


def test_future_schema_is_rejected_without_rewriting_version(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 999")

    with pytest.raises(SchemaVersionError, match="newer than supported"):
        CatalogDatabase(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 999
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert not path.with_name(f"{path.name}-wal").exists()
    assert not path.with_name(f"{path.name}-shm").exists()


def test_platform_namespaces_allow_the_same_native_id(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        now = "2026-08-05T00:00:00Z"
        with database.transaction():
            platform_ids = {
                row["platform_key"]: row["platform_id"]
                for row in database.connection.execute(
                    "SELECT platform_id, platform_key FROM platforms"
                )
            }
            for platform_key in ("x", "pixiv"):
                database.connection.execute(
                    """INSERT INTO accounts
                       (platform_id, native_account_id, first_seen_at, last_seen_at)
                       VALUES (?, '123', ?, ?)""",
                    (platform_ids[platform_key], now, now),
                )
        count = database.connection.execute(
            "SELECT COUNT(*) FROM accounts WHERE native_account_id = '123'"
        ).fetchone()[0]
        assert count == 2


def test_foreign_keys_are_enabled(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        assert database.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                """INSERT INTO accounts
                   (platform_id, native_account_id, first_seen_at, last_seen_at)
                VALUES (999, 'no-platform', 'now', 'now')"""
            )


def test_reopening_current_catalog_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        original_tables = {
            row[0]
            for row in database.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    with CatalogDatabase(path) as database:
        assert database.schema_version == current_schema_version()
        assert original_tables <= {
            row[0]
            for row in database.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }


def test_search_has_same_shape_for_fts_and_like(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        platform_id = database.connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'x'"
        ).fetchone()[0]
        with database.transaction():
            database.connection.execute(
                """INSERT INTO posts (
                       platform_id, native_post_id, text_content, first_seen_at, last_seen_at
                   ) VALUES (?, '42', 'painted ocean light', 'now', 'now')""",
                (platform_id,),
            )
        like_result = database.search("ocean", backend="like")
        assert like_result == {
            "search_backend": "like",
            "results": [{"post": "x:42", "text": "painted ocean light"}],
        }
        if database.search_backend == "fts5":
            fts_result = database.search("ocean", backend="fts5")
            assert fts_result["results"] == like_result["results"]


def test_like_search_escapes_wildcards(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        platform_id = database.connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'x'"
        ).fetchone()[0]
        with database.transaction():
            database.connection.execute(
                """INSERT INTO posts (
                       platform_id, native_post_id, text_content, first_seen_at, last_seen_at
                   ) VALUES (?, '42', '100 percent', 'now', 'now')""",
                (platform_id,),
            )
        assert database.search("%", backend="like")["results"] == []


def test_like_and_fts_search_account_profile_fields(tmp_path: Path) -> None:
    from media_catalog.records import AccountRecord, PostRecord
    from media_catalog.writer import CatalogWriter

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            account = writer.upsert_account(
                AccountRecord("x", "7", "2026-08-05T00:00:00Z", bio="watercolor artist")
            )
            post = writer.upsert_post(PostRecord("x", "42", "2026-08-05T00:00:00Z"))
            writer.add_participant(post.id, account.id, "author")
        like_result = database.search("watercolor", backend="like")
        assert [item["post"] for item in like_result["results"]] == ["x:42"]
        if database.search_backend == "fts5":
            assert (
                database.search("watercolor", backend="fts5")["results"] == like_result["results"]
            )
