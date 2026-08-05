from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    AccountRecord,
    AssetRecord,
    MediaOccurrenceRecord,
    PostRecord,
    RawRecord,
)
from media_catalog.writer import CatalogWriter

NOW = "2026-08-05T00:00:00Z"


def test_writer_preserves_raw_profiles_roles_events_and_assets(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        raw = json.dumps({"unknown": {"future": True}}, separators=(",", ":")).encode()
        with database.transaction():
            raw_id = writer.store_raw(
                RawRecord(raw, "application/json", "post", "42", NOW, "fixture-v1")
            )
            account_id = writer.upsert_account(
                AccountRecord("x", "7", NOW, handle=None, display_name=None),
                raw_observation_id=raw_id,
            ).id
            post_id = writer.upsert_post(
                PostRecord("x", "42", NOW, text="ocean light"),
                raw_observation_id=raw_id,
            ).id
            writer.add_participant(post_id, account_id, "author", raw_observation_id=raw_id)
            writer.add_observation(post_id, "liked", "fixture", "like:42", NOW)
            writer.add_observation(post_id, "bookmarked", "fixture", "bookmark:42", NOW)
            occurrence_id = writer.upsert_media(
                post_id,
                MediaOccurrenceRecord(
                    "media:0",
                    0,
                    "image",
                    "https://example.test/image.jpg",
                    observed_at=NOW,
                ),
            ).id
            writer.link_asset(
                occurrence_id,
                AssetRecord(
                    "a" * 64,
                    "b" * 32,
                    "0123456789abcdef",
                    123,
                    "legacy_reference",
                    "media/image.jpg",
                    NOW,
                    "legacy_x_likes",
                ),
            )

        stored_raw = database.connection.execute("SELECT payload FROM raw_payloads").fetchone()[0]
        assert bytes(stored_raw) == raw
        snapshot = database.connection.execute(
            "SELECT handle, display_name FROM account_snapshots"
        ).fetchone()
        assert tuple(snapshot) == (None, None)
        assert (
            database.connection.execute("SELECT role FROM post_participants").fetchone()[0]
            == "author"
        )
        assert database.stats(event_type="liked")["matching_posts"] == 1
        assert database.stats(event_type="bookmarked")["matching_posts"] == 1
        assert database.summary()["media_occurrences"] == 1
        assert database.summary()["assets"] == 1


def test_account_snapshots_keep_history_and_deduplicate_same_source(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            writer.upsert_account(AccountRecord("x", "7", NOW, handle="first"))
            writer.upsert_account(AccountRecord("x", "7", NOW, handle="first"))
            writer.upsert_account(AccountRecord("x", "7", "2026-08-06T00:00:00Z", handle="second"))
        handles = [
            row[0]
            for row in database.connection.execute(
                "SELECT handle FROM account_snapshots ORDER BY account_snapshot_id"
            )
        ]
        assert handles == ["first", "second"]


def test_raw_payload_is_deduplicated_across_observations(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        record = RawRecord(b'{"same":true}', "application/json", "post", "42", NOW)
        with database.transaction():
            writer.store_raw(record)
            writer.store_raw(record)
        assert database.connection.execute("SELECT COUNT(*) FROM raw_payloads").fetchone()[0] == 1


def test_validation_rejects_invalid_roles_ids_and_hashes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="platform"):
        AccountRecord("Bad Platform", "7", NOW)
    with pytest.raises(ValueError, match="native identifier"):
        PostRecord("x", "", NOW)
    with pytest.raises(ValueError, match="64-character"):
        AssetRecord("bad", None, None, None, "legacy_reference", None, None, "fixture")

    with (
        CatalogDatabase(tmp_path / "catalog.sqlite3") as database,
        pytest.raises(ValueError, match="role"),
    ):
        CatalogWriter(database).add_participant(1, 1, "owner")


def test_catalog_operations_do_not_connect_to_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("catalog operation attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", fail_connect)
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            writer.upsert_post(PostRecord("x", "42", NOW, text="offline"))
        assert database.doctor()["ok"] is True
        assert database.search("offline", backend="like")["results"]


def test_observations_require_real_posts_and_reject_key_collisions(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with pytest.raises(sqlite3.IntegrityError):
            writer.add_observation(999, "liked", "fixture", "same", NOW)
        database.connection.rollback()
        with database.transaction():
            first = writer.upsert_post(PostRecord("x", "1", NOW)).id
            second = writer.upsert_post(PostRecord("x", "2", NOW)).id
            writer.add_observation(first, "liked", "fixture", "same", NOW)
            with pytest.raises(ValueError, match="belongs to another post"):
                writer.add_observation(second, "liked", "fixture", "same", NOW)


def test_older_records_do_not_regress_current_state(tmp_path: Path) -> None:
    newer = "2026-08-06T00:00:00Z"
    older = "2026-08-05T23:30:00+02:00"
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            post = writer.upsert_post(PostRecord("x", "42", newer, availability="deleted"))
            writer.upsert_post(PostRecord("x", "42", older, availability="available"))
        row = database.connection.execute(
            "SELECT availability, last_seen_at FROM posts WHERE post_id = ?", (post.id,)
        ).fetchone()
        assert tuple(row) == ("deleted", newer)


def test_hashes_are_canonical_and_asset_relationship_is_explicit(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            post_id = writer.upsert_post(PostRecord("x", "42", NOW)).id
            occurrence_id = writer.upsert_media(
                post_id, MediaOccurrenceRecord("0", 0, "image", observed_at=NOW)
            ).id
            asset = AssetRecord(
                "A" * 64,
                "B" * 32,
                None,
                1,
                "legacy_reference",
                "old.jpg",
                NOW,
                "legacy_x_likes",
            )
            writer.link_asset(occurrence_id, asset, relationship="reference")
            writer.link_asset(occurrence_id, asset, relationship="reference")
        stored = database.connection.execute(
            "SELECT verified_sha256, verified_md5 FROM assets"
        ).fetchone()
        assert tuple(stored) == ("a" * 64, "b" * 32)
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        assert (
            database.connection.execute("SELECT relationship FROM occurrence_assets").fetchone()[0]
            == "reference"
        )
