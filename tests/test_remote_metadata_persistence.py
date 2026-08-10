from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase, available_migrations, current_schema_version
from media_catalog.records import (
    AttributionRecord,
    MediaOccurrenceRecord,
    PostRecord,
    RawRecord,
    RemoteRequestRecord,
    RemoteRunRecord,
    TagObservationRecord,
)
from media_catalog.remote_queries import get_remote_run, list_attributions, list_post_tags
from media_catalog.writer import CatalogWriter

NOW = "2026-08-10T00:00:00Z"


def _v4_catalog(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        for version, _name, sql in available_migrations()[:4]:
            connection.executescript(sql)
            connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()


def test_remote_schema_fresh_and_v4_upgrade_preserve_existing_ids(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    _v4_catalog(path)
    with sqlite3.connect(path) as connection:
        platform = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO posts (
                   post_id, platform_id, native_post_id, first_seen_at, last_seen_at
               ) VALUES (41, ?, '99', ?, ?)""",
            (platform, NOW, NOW),
        )
        connection.commit()
    with CatalogDatabase(path) as database:
        assert database.schema_version == current_schema_version() == 5
        assert database.connection.execute("SELECT post_id FROM posts").fetchone()[0] == 41
        tables = {
            row[0]
            for row in database.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"remote_runs", "remote_requests", "tags", "attribution_entities"} <= tables
        assert database.doctor()["ok"] is True
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                """INSERT INTO remote_runs (
                       platform_id, operation, target, adapter_version, schema_version,
                       request_budget, page_budget, record_budget, time_budget_seconds, started_at
                   ) VALUES (?, 'bad', '1', 'v1', 'v1', 1, 1, 1, 1, ?)""",
                (platform, NOW),
            )


def test_remote_writer_keeps_distinct_observations_and_metadata_history(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        writer = CatalogWriter(database)
        with database.transaction():
            post_id = writer.upsert_post(
                PostRecord(
                    "pixiv",
                    "99",
                    NOW,
                    title="Known",
                    rating="safe",
                    provider_post_type="illust",
                )
            ).id
            run_ids = []
            raw_ids = []
            for index in (1, 2):
                run_id = writer.begin_remote_run(
                    RemoteRunRecord(
                        "pixiv", "fetch_post", "99", "adapter-v1", "schema-v1", 1, 1, 10, 10, NOW
                    )
                )
                request_id = writer.record_remote_request(
                    RemoteRequestRecord(
                        run_id,
                        1,
                        f"pixiv:fetch_post:99:{index}",
                        "fetch_post",
                        "99",
                        "success",
                        NOW,
                    )
                )
                raw_ids.append(
                    writer.store_raw(
                        RawRecord(
                            b'{"same":true}',
                            "application/json",
                            "post",
                            "99",
                            NOW,
                            platform="pixiv",
                            adapter_version="adapter-v1",
                            schema_version="schema-v1",
                        ),
                        remote_run_id=run_id,
                        remote_request_id=request_id,
                    )
                )
                run_ids.append(run_id)
            writer.upsert_tag(
                post_id,
                TagObservationRecord(
                    "pixiv", "general", "tag", "Tag", NOW, "provider-tag-v1", "Translated", 0
                ),
                raw_observation_id=raw_ids[0],
            )
            writer.upsert_tag(
                post_id,
                TagObservationRecord(
                    "pixiv", "general", "tag", "TAG", NOW, "provider-tag-v1", None, 1
                ),
                raw_observation_id=raw_ids[1],
            )
            attribution_id = writer.upsert_attribution(
                AttributionRecord(
                    "danbooru",
                    "7",
                    "adapter-v1",
                    NOW,
                    primary_name="artist_name",
                    other_names=("alias",),
                    urls=("https://example.test/artist",),
                ),
                raw_observation_id=raw_ids[0],
            ).id
            writer.upsert_post(PostRecord("pixiv", "99", NOW), raw_observation_id=raw_ids[1])
            writer.upsert_media(
                post_id,
                MediaOccurrenceRecord(
                    "99:p0",
                    0,
                    "image",
                    mime_type="image/png",
                    declared_file_size=123,
                    observed_at=NOW,
                ),
                raw_observation_id=raw_ids[0],
            )
        assert raw_ids[0] != raw_ids[1]
        assert database.connection.execute("SELECT COUNT(*) FROM raw_payloads").fetchone()[0] == 1
        assert (
            database.connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0]
            == 2
        )
        assert database.connection.execute("SELECT title FROM posts").fetchone()[0] == "Known"
        assert database.connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
        assert attribution_id > 0
        tags = list_post_tags(database, post_id)
        assert tags[0]["observation_count"] == 2
        assert list_attributions(database, platform="danbooru")[0]["name_count"] == 2
        public_run = get_remote_run(database, run_ids[0])
        assert public_run is not None
        assert "payload" not in str(public_run).lower()
        assert "continuation_json" not in str(public_run).lower()
