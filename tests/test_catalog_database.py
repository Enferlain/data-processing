from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import media_catalog.database as database_module
from media_catalog.database import CatalogDatabase, SchemaVersionError, current_schema_version


def _catalog_state(path: Path) -> tuple[bytes, int, tuple[str, ...]]:
    with sqlite3.connect(path) as connection:
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    directory = tuple(sorted(item.name for item in path.parent.iterdir()))
    return path.read_bytes(), schema_version, directory


def test_fresh_catalog_applies_current_migration(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        assert database.schema_version == current_schema_version()
        assert database.summary()["platforms"] == 7
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


def test_read_only_catalog_accepts_current_schema_without_writes(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path):
        pass
    before = _catalog_state(path)

    with CatalogDatabase.open_read_only(path) as database:
        assert database.schema_version == current_schema_version()
        assert database.search_backend == "like"
        assert database.connection.row_factory is sqlite3.Row
        assert database.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert database.connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert database.summary()["platforms"] == 7
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            database.connection.execute("CREATE TABLE should_not_exist(value TEXT)")

    assert _catalog_state(path) == before


def test_read_only_catalog_does_not_create_missing_path_or_parent(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "catalog.sqlite3"
    before = tuple(sorted(item.name for item in tmp_path.iterdir()))

    with pytest.raises(sqlite3.OperationalError, match="unable to open database"):
        CatalogDatabase.open_read_only(path)

    assert not path.exists()
    assert not path.parent.exists()
    assert tuple(sorted(item.name for item in tmp_path.iterdir())) == before


def test_read_only_catalog_fails_closed_for_wal_frames_without_shm(tmp_path: Path) -> None:
    path = tmp_path / "wal.sqlite3"
    with CatalogDatabase(path):
        pass
    writer = sqlite3.connect(path)
    try:
        writer.execute("PRAGMA journal_mode = WAL")
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute("CREATE TABLE wal_marker(value INTEGER)")
        writer.commit()
        wal_path = Path(f"{path}-wal")
        shm_path = Path(f"{path}-shm")
        assert wal_path.stat().st_size > 32
        shm_path.unlink()

        with pytest.raises(SchemaVersionError, match="WAL frames"):
            CatalogDatabase.open_read_only(path)
        assert not shm_path.exists()
        assert wal_path.exists()
    finally:
        writer.close()


def test_read_only_catalog_detects_wal_created_during_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "raced-wal.sqlite3"
    with CatalogDatabase(path):
        pass
    with sqlite3.connect(path) as checkpoint:
        checkpoint.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    original_check = CatalogDatabase._require_absent_wal
    calls = 0
    writer: sqlite3.Connection | None = None

    def create_wal_after_first_check(checked_path: Path) -> None:
        nonlocal calls, writer
        calls += 1
        original_check(checked_path)
        if calls == 1:
            writer = sqlite3.connect(path)
            writer.execute("PRAGMA journal_mode = WAL")
            writer.execute("PRAGMA wal_autocheckpoint = 0")
            writer.execute("CREATE TABLE raced_commit(value INTEGER)")
            writer.commit()
            Path(f"{path}-shm").unlink()

    monkeypatch.setattr(CatalogDatabase, "_require_absent_wal", create_wal_after_first_check)
    try:
        with pytest.raises(SchemaVersionError, match="WAL"):
            CatalogDatabase.open_read_only(path)
        assert calls == 2
        assert Path(f"{path}-wal").exists()
        assert not Path(f"{path}-shm").exists()
    finally:
        if writer is not None:
            writer.close()


def test_read_only_catalog_fails_closed_for_pending_rollback_journal(tmp_path: Path) -> None:
    path = tmp_path / "rollback.sqlite3"
    with CatalogDatabase(path):
        pass
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0] == "delete"
    journal_path = Path(f"{path}-journal")
    journal_path.write_bytes(b"pending rollback pages")
    database_before = path.read_bytes()
    journal_before = journal_path.read_bytes()

    with pytest.raises(SchemaVersionError, match="pending rollback journal"):
        CatalogDatabase.open_read_only(path)

    assert path.read_bytes() == database_before
    assert journal_path.read_bytes() == journal_before


def test_read_only_catalog_rejects_snapshot_over_memory_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "large.sqlite3"
    with CatalogDatabase(path):
        pass
    before = path.read_bytes()
    monkeypatch.setattr(database_module, "READ_ONLY_SNAPSHOT_LIMIT", len(before) - 1)

    with pytest.raises(SchemaVersionError, match="bounded read-only snapshot size"):
        CatalogDatabase.open_read_only(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "schema_version", [current_schema_version() - 1, current_schema_version() + 1]
)
def test_read_only_catalog_rejects_non_current_schema_without_writes(
    tmp_path: Path, schema_version: int
) -> None:
    path = tmp_path / f"schema-{schema_version}.sqlite3"
    with CatalogDatabase(path):
        pass
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute(f"PRAGMA user_version = {schema_version}")
    before = _catalog_state(path)

    with pytest.raises(SchemaVersionError, match=r"backup.*migration"):
        CatalogDatabase.open_read_only(path)

    assert _catalog_state(path) == before


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
