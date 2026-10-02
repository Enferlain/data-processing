"""Task 2.5 audit: the neutral schema covers every fixture-proven Gelbooru fact."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from media_catalog.adapters.fixtures import load_fixture_suite
from media_catalog.adapters.gelbooru import (
    ADAPTER_VERSION,
    DAPI_SCHEMA_VERSION,
    DAPI_TRANSPORT_VERSION,
)
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    AccountRecord,
    MediaOccurrenceRecord,
    PostRecord,
    RawRecord,
    RemoteRunRecord,
    TagObservationRecord,
)
from media_catalog.writer import CatalogWriter

NOW = "2026-10-01T00:00:00Z"
FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"


def _case(file_name: str, case_name: str):
    suite = load_fixture_suite(FIXTURES / file_name)
    return next(case for case in suite.cases if case.name == case_name)


def test_gelbooru_platform_seed_is_present_on_a_fresh_schema(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        row = database.connection.execute(
            "SELECT display_name FROM platforms WHERE platform_key = 'gelbooru'"
        ).fetchone()
        assert row is not None
        assert row[0] == "Gelbooru-compatible"
        assert database.doctor()["ok"] is True


def test_fixture_proven_post_round_trips_through_the_neutral_schema(tmp_path: Path) -> None:
    case = _case("gelbooru.json", "post_12370900")
    body = json.loads(case.response.payload)["post"][0]
    tag_spelling = body["tags"].split()[0]

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            raw_id = writer.store_raw(
                RawRecord(
                    case.response.payload,
                    "application/json",
                    "post",
                    str(body["id"]),
                    NOW,
                    platform="gelbooru",
                    adapter_version=ADAPTER_VERSION,
                    schema_version=DAPI_SCHEMA_VERSION,
                    transport_key=DAPI_TRANSPORT_VERSION,
                    transport_version=DAPI_TRANSPORT_VERSION,
                )
            )
            account = writer.upsert_account(
                AccountRecord("gelbooru", str(body["creator_id"]), NOW, handle=body["owner"])
            )
            post = writer.upsert_post(
                PostRecord(
                    "gelbooru",
                    str(body["id"]),
                    NOW,
                    canonical_url=(
                        f"https://gelbooru.com/index.php?page=post&s=view&id={body['id']}"
                    ),
                    created_at="2025-07-30T15:16:34Z",
                    rating=body["rating"],
                ),
                raw_observation_id=raw_id,
            )
            writer.add_participant(post.id, account.id, "uploader", raw_observation_id=raw_id)
            occurrence = writer.upsert_media(
                post.id,
                MediaOccurrenceRecord(
                    "gelbooru:0",
                    0,
                    "image",
                    remote_url=body["file_url"],
                    preview_url=body["preview_url"],
                    width=body["width"],
                    height=body["height"],
                    declared_md5=body["md5"],
                    observed_at=NOW,
                ),
                raw_observation_id=raw_id,
            )
            tag = writer.upsert_tag(
                post.id,
                TagObservationRecord(
                    "gelbooru",
                    "unknown",
                    tag_spelling,
                    tag_spelling,
                    NOW,
                    "gelbooru-tag-v1",
                ),
                raw_observation_id=raw_id,
            )
            post_again = writer.upsert_post(
                PostRecord(
                    "gelbooru",
                    str(body["id"]),
                    NOW,
                    canonical_url=(
                        f"https://gelbooru.com/index.php?page=post&s=view&id={body['id']}"
                    ),
                    created_at="2025-07-30T15:16:34Z",
                    rating=body["rating"],
                ),
                raw_observation_id=raw_id,
            )

        assert post_again.id == post.id and post_again.outcome == "existing"

        raw_row = database.connection.execute(
            """SELECT p.platform_key, r.transport_key, r.transport_version
               FROM raw_observations r JOIN platforms p ON p.platform_id = r.platform_id
               WHERE r.raw_observation_id = ?""",
            (raw_id,),
        ).fetchone()
        assert tuple(raw_row) == ("gelbooru", DAPI_TRANSPORT_VERSION, DAPI_TRANSPORT_VERSION)

        post_row = database.connection.execute(
            """SELECT p.platform_key, posts.rating, posts.created_at
               FROM posts JOIN platforms p ON p.platform_id = posts.platform_id
               WHERE posts.post_id = ?""",
            (post.id,),
        ).fetchone()
        assert tuple(post_row) == ("gelbooru", body["rating"], "2025-07-30T15:16:34Z")

        media_row = database.connection.execute(
            """SELECT declared_md5, width, height, remote_url FROM media_occurrences
               WHERE media_occurrence_id = ?""",
            (occurrence.id,),
        ).fetchone()
        assert tuple(media_row) == (
            body["md5"],
            body["width"],
            body["height"],
            body["file_url"],
        )

        participant = database.connection.execute(
            "SELECT role FROM post_participants WHERE post_id = ? AND account_id = ?",
            (post.id, account.id),
        ).fetchone()
        assert participant[0] == "uploader"

        tag_row = database.connection.execute(
            "SELECT category, name FROM tags WHERE tag_id = ?",
            (tag.id,),
        ).fetchone()
        assert tuple(tag_row) == ("unknown", tag_spelling)
        link = database.connection.execute(
            """SELECT COUNT(*) FROM post_tag_observations pto
               JOIN post_tags pt ON pt.post_tag_id = pto.post_tag_id
               WHERE pt.post_id = ?""",
            (post.id,),
        ).fetchone()[0]
        assert link >= 1

        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                "INSERT INTO post_participants (post_id, account_id, role) "
                "VALUES (999999, ?, 'uploader')",
                (account.id,),
            )
        database.connection.rollback()
        assert database.doctor()["ok"] is True


def test_fixture_proven_tag_metadata_round_trips_native_category_code(tmp_path: Path) -> None:
    case = _case("gelbooru.json", "tag_metadata")
    body = json.loads(case.response.payload)["tag"][0]

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        record = TagObservationRecord(
            "gelbooru",
            "unknown",
            body["name"],
            body["name"],
            NOW,
            "gelbooru-tag-v1",
            provider_tag_id=str(body["id"]),
            native_category=None,
            native_category_code=body["type"],
            post_count=body["count"],
        )
        with database.transaction():
            first = writer.upsert_tag_record(record)
            second = writer.upsert_tag_record(record)

        assert first.id == second.id
        assert second.outcome in {"existing", "updated"}

        row = database.connection.execute(
            """SELECT provider_tag_id, native_category, native_category_code, post_count, category
               FROM tags WHERE tag_id = ?""",
            (first.id,),
        ).fetchone()
        assert tuple(row) == (str(body["id"]), None, body["type"], body["count"], "unknown")
        assert b'"ambiguous"' in case.response.payload
        assert database.doctor()["ok"] is True


def test_gelbooru_remote_runs_carry_transport_identity_and_enforce_origin_triggers(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            run_id = writer.begin_remote_run(
                RemoteRunRecord(
                    "gelbooru",
                    "fetch_post",
                    "post:12370900",
                    ADAPTER_VERSION,
                    DAPI_SCHEMA_VERSION,
                    1,
                    1,
                    1,
                    60,
                    NOW,
                    transport_key=DAPI_TRANSPORT_VERSION,
                    transport_version=DAPI_TRANSPORT_VERSION,
                )
            )

        row = database.connection.execute(
            """SELECT p.platform_key, r.transport_key, r.transport_version, r.operation
               FROM remote_runs r JOIN platforms p ON p.platform_id = r.platform_id
               WHERE r.remote_run_id = ?""",
            (run_id,),
        ).fetchone()
        assert tuple(row) == (
            "gelbooru",
            DAPI_TRANSPORT_VERSION,
            DAPI_TRANSPORT_VERSION,
            "fetch_post",
        )

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            database.connection.execute(
                "UPDATE remote_runs SET origin_kind = 'manual' WHERE remote_run_id = ?",
                (run_id,),
            )
        database.connection.rollback()

        with pytest.raises(ValueError, match="unsupported library origin kind"):
            writer.begin_remote_run(
                RemoteRunRecord(
                    "gelbooru",
                    "fetch_post",
                    "post:12370900",
                    ADAPTER_VERSION,
                    DAPI_SCHEMA_VERSION,
                    1,
                    1,
                    1,
                    60,
                    NOW,
                    origin_kind="bogus_kind",
                    origin_reference="x",
                    transport_key=DAPI_TRANSPORT_VERSION,
                    transport_version=DAPI_TRANSPORT_VERSION,
                )
            )

        platform_id = database.connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'gelbooru'"
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                """INSERT INTO remote_runs (
                       platform_id, operation, target, adapter_version, schema_version,
                       request_budget, page_budget, record_budget, time_budget_seconds,
                       started_at, origin_kind, origin_reference
                   ) VALUES (?, 'fetch_post', 'post:1', 'av', 'sv', 1, 1, 1, 60, ?,
                             'bogus_kind', 'x')""",
                (platform_id, NOW),
            )
        database.connection.rollback()
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM remote_runs WHERE origin_kind IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
        assert database.doctor()["ok"] is True
