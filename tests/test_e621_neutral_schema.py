from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest

import media_catalog.database as database_module
from media_catalog.adapters import NormalizedItem, NormalizedPage, load_fixture_suite
from media_catalog.adapters.e621 import E621, E621Adapter
from media_catalog.database import CatalogDatabase, SchemaVersionError, available_migrations
from media_catalog.records import RawRecord, TagObservationRecord
from media_catalog.remote_queries import (
    RemoteQueryService,
    list_post_tags,
)
from media_catalog.remote_sync.persistence import NormalizedPageWriter
from media_catalog.writer import CatalogWriter

NOW = "2026-08-13T00:00:00Z"
FIXTURE = Path(__file__).parent / "fixtures" / "metadata_adapters" / "e621.json"


def _at_version(path: Path, version: int) -> None:
    with sqlite3.connect(path) as connection:
        for number, _name, sql in available_migrations()[:version]:
            connection.executescript(sql)
            connection.execute(f"PRAGMA user_version = {number}")
        connection.commit()


def _case(name: str):
    suite = load_fixture_suite(FIXTURE)
    return next(case for case in suite.cases if case.name == name)


def _adapter() -> E621Adapter:
    return E621Adapter(
        E621,
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
        clock=lambda: NOW,
    )


def test_v8_upgrade_adds_neutral_tables_without_changing_existing_ids(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    _at_version(path, 8)
    with sqlite3.connect(path) as connection:
        platform_id = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'e621'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO posts (post_id, platform_id, native_post_id, first_seen_at, last_seen_at) "
            "VALUES (91, ?, '5001', ?, ?)",
            (platform_id, NOW, NOW),
        )
        connection.commit()

    with CatalogDatabase(path) as database:
        assert database.schema_version == database_module.current_schema_version()
        assert database.connection.execute("SELECT post_id FROM posts").fetchone()[0] == 91
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM platforms WHERE platform_key = 'e621'"
            ).fetchone()[0]
            == 1
        )
        assert database.doctor()["ok"] is True
        tables = {
            row[0]
            for row in database.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "tag_observations",
            "tag_alias_observations",
            "post_metadata_observations",
            "post_pool_observations",
            "post_flag_observations",
        } <= tables


def test_failed_e621_migration_rolls_back_all_partial_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "broken.sqlite3"
    _at_version(path, 8)
    migrations = available_migrations()
    broken = (
        *migrations[:8],
        (9, "0009_broken_e621.sql", "CREATE TABLE partial_e621(x); INVALID SQL"),
    )
    monkeypatch.setattr(database_module, "available_migrations", lambda: broken)

    with pytest.raises(SchemaVersionError, match="0009_broken_e621"):
        CatalogDatabase(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'partial_e621'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'tag_observations'"
            ).fetchone()[0]
            == 0
        )
        assert list(connection.execute("PRAGMA foreign_key_check")) == []


def test_e621_facts_are_typed_queryable_idempotent_and_immutable(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        adapter = _adapter()
        post_page = adapter.normalize(_case("normal_post").response)
        tag_page = adapter.normalize(_case("tag_record").response)
        alias_page = adapter.normalize(_case("active_alias").response)
        artist_page = adapter.normalize(_case("artist_record").response)
        with database.transaction():
            raw_post = writer.store_raw(
                RawRecord(
                    _case("normal_post").response.payload,
                    "application/json",
                    "post",
                    "5001",
                    NOW,
                    platform="e621",
                    adapter_version="e621-native-v1",
                    schema_version="e621-json-v1",
                )
            )
            raw_tag = writer.store_raw(
                RawRecord(
                    _case("tag_record").response.payload,
                    "application/json",
                    "tag",
                    "7001",
                    NOW,
                    platform="e621",
                    adapter_version="e621-native-v1",
                    schema_version="e621-json-v1",
                )
            )
            raw_alias = writer.store_raw(
                RawRecord(
                    _case("active_alias").response.payload,
                    "application/json",
                    "tag_alias",
                    "8001",
                    NOW,
                    platform="e621",
                    adapter_version="e621-native-v1",
                    schema_version="e621-json-v1",
                )
            )
            raw_artist = writer.store_raw(
                RawRecord(
                    _case("artist_record").response.payload,
                    "application/json",
                    "attribution",
                    "6001",
                    NOW,
                    platform="e621",
                    adapter_version="e621-native-v1",
                    schema_version="e621-json-v1",
                )
            )
            page_writer = NormalizedPageWriter(writer)
            page_writer.write_with_result(
                post_page,
                observed_at=NOW,
                raw_observation_id=raw_post,
                adapter_version="e621-native-v1",
            )
            page_writer.write_with_result(
                tag_page,
                observed_at=NOW,
                raw_observation_id=raw_tag,
                adapter_version="e621-native-v1",
            )
            page_writer.write_with_result(
                alias_page,
                observed_at=NOW,
                raw_observation_id=raw_alias,
                adapter_version="e621-native-v1",
            )
            page_writer.write_with_result(
                artist_page,
                observed_at=NOW,
                raw_observation_id=raw_artist,
                adapter_version="e621-native-v1",
            )
            page_writer.write_with_result(
                post_page,
                observed_at=NOW,
                raw_observation_id=raw_post,
                adapter_version="e621-native-v1",
            )

        assert (
            database.connection.execute("SELECT COUNT(*) FROM tag_observations").fetchone()[0] == 1
        )
        tag_row = database.connection.execute(
            "SELECT native_category, native_category_code, post_count FROM tags "
            "WHERE provider_tag_id = '7001'"
        ).fetchone()
        assert tuple(tag_row) == ("species", 5, 4321)
        assert (
            database.connection.execute("SELECT COUNT(*) FROM tag_alias_observations").fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM post_metadata_observations"
            ).fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM post_pool_observations").fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM post_flag_observations").fetchone()[0]
            == 3
        )
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM attribution_snapshots WHERE group_name = 'group_x'"
            ).fetchone()[0]
            == 1
        )

        post_id = database.connection.execute(
            "SELECT post_id FROM posts WHERE native_post_id = '5001'"
        ).fetchone()[0]
        assert list_post_tags(database, post_id)
        assert RemoteQueryService(database).tag_aliases(platform="e621")[0]["status"] == "active"
        assert RemoteQueryService(database).post_metadata(post_id)[0]["score_total"] == 18
        assert RemoteQueryService(database).post_pools(post_id)[0]["pool_native_id"] == "77001"

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            database.connection.execute("UPDATE tag_alias_observations SET status = 'pending'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            database.connection.execute("DELETE FROM post_metadata_observations")
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                "INSERT INTO post_pool_observations "
                "(post_id, pool_native_id, observed_at, observation_digest) "
                "VALUES (999999, 'bad', ?, ?)",
                (NOW, "a" * 64),
            )
        assert database.doctor()["ok"] is True


def test_e621_post_metadata_observation_keeps_changed_score_history(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        adapter = _adapter()
        page = adapter.normalize(_case("normal_post").response)
        with database.transaction():
            raw = writer.store_raw(
                RawRecord(
                    _case("normal_post").response.payload,
                    "application/json",
                    "post",
                    "5001",
                    NOW,
                    platform="e621",
                )
            )
            page_writer = NormalizedPageWriter(writer)
            page_writer.write(
                page, observed_at=NOW, raw_observation_id=raw, adapter_version="e621-native-v1"
            )
            post = next(item for item in page.items if item.object_kind == "post")
            changed = dict(post.data)
            changed["score"] = {"up": 21, "down": 2, "total": 19}
            changed_page = NormalizedPage((NormalizedItem("post", "5001", changed),))
            page_writer.write(
                changed_page,
                observed_at="2026-08-14T00:00:00Z",
                raw_observation_id=raw,
                adapter_version="e621-native-v1",
            )
        scores = database.connection.execute(
            "SELECT score_total FROM post_metadata_observations "
            "ORDER BY post_metadata_observation_id"
        ).fetchall()
        assert [row[0] for row in scores] == [18, 19]


def test_standalone_tag_name_cannot_change_provider_identity(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            writer.upsert_tag_record(
                TagObservationRecord(
                    "e621",
                    "artist",
                    "stable_artist",
                    "stable_artist",
                    NOW,
                    "provider-tag-v1",
                    provider_tag_id="7001",
                    native_category="artist",
                    native_category_code=1,
                )
            )
            with pytest.raises(ValueError, match="another provider tag id"):
                writer.upsert_tag_record(
                    TagObservationRecord(
                        "e621",
                        "artist",
                        "stable_artist",
                        "stable_artist",
                        NOW,
                        "provider-tag-v1",
                        provider_tag_id="7002",
                        native_category="artist",
                        native_category_code=1,
                    )
                )

        row = database.connection.execute(
            "SELECT provider_tag_id FROM tags WHERE name = 'stable_artist'"
        ).fetchone()
        assert row[0] == "7001"
