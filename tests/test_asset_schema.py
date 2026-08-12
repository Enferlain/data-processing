from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase, available_migrations, current_schema_version
from media_catalog.imports.x_likes_db import import_x_likes_database
from media_catalog.records import (
    AdoptionAttemptRecord,
    AdoptionItemRecord,
    AdoptionLimits,
    AdoptionRunRecord,
    AssetFingerprintRecord,
    AssetLocationRecord,
    AssetRecord,
    ManagedRootRecord,
    MediaOccurrenceRecord,
    OccurrenceSourceRecord,
    PostRecord,
)
from media_catalog.storage.queries import get_asset_detail, legacy_assertion_summary, list_assets
from media_catalog.writer import CatalogWriter
from x_likes.database import SCHEMA

NOW = "2026-08-09T00:00:00Z"


def _v3_catalog(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for version, _name, sql in available_migrations()[:3]:
            connection.executescript(sql)
            connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()


def test_fresh_schema_exposes_asset_persistence_tables_and_constraints(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        tables = {
            row[0]
            for row in database.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "managed_roots",
            "asset_locations",
            "occurrence_sources",
            "asset_fingerprints",
            "asset_legacy_assertions",
            "adoption_runs",
            "adoption_items",
            "adoption_attempts",
        } <= tables
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                "INSERT INTO managed_roots(root_kind, root_identity, display_label, created_at) "
                "VALUES ('bad', 'identity', 'label', ?)",
                (NOW,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                "INSERT INTO adoption_attempts("
                "adoption_item_id, attempt_number, outcome, started_at) "
                "VALUES (999, 0, 'missing', ?)",
                (NOW,),
            )


def test_v3_upgrade_preserves_asset_ids_and_backfills_ambiguous_path(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    _v3_catalog(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO assets(asset_id, verified_sha256, storage_kind, storage_path, "
            "verification_method) VALUES (17, ?, 'legacy_reference', 'old/photo.jpg', 'legacy')",
            ("a" * 64,),
        )
        connection.commit()
    backup = path.read_bytes()

    with CatalogDatabase(path) as database:
        assert database.schema_version == current_schema_version()
        assert database.connection.execute("SELECT asset_id FROM assets").fetchone()[0] == 17
        assertion = database.connection.execute(
            "SELECT asset_id, legacy_path, assertion_kind, associated_occurrence_id "
            "FROM asset_legacy_assertions"
        ).fetchone()
        assert tuple(assertion) == (17, "old/photo.jpg", "ambiguous_asset_path", None)
        assert (
            database.connection.execute("SELECT COUNT(*) FROM occurrence_sources").fetchone()[0]
            == 0
        )
    assert path.read_bytes() != backup  # migration changes only the catalog copy, not the backup


def test_asset_queries_hide_legacy_paths_and_report_assertion_summary(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    _v3_catalog(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO assets(asset_id, verified_sha256, storage_kind, storage_path, "
            "verification_method) VALUES (17, ?, 'legacy_reference', 'old/photo.jpg', 'legacy')",
            ("a" * 64,),
        )
        connection.commit()
    with CatalogDatabase(path):
        pass

    rows = list_assets(path)
    assert rows[0]["legacy_assertion_count"] == 1
    assert rows[0]["legacy_assertion_unassociated_count"] == 1
    assert rows[0]["legacy_assertion_classification"] == "ambiguous_asset_path"
    assert "storage_path" not in rows[0]
    assert "old/photo.jpg" not in str(rows)
    detail = get_asset_detail(path, 17)
    assert detail is not None
    assert "storage_path" not in detail["asset"]
    assert detail["legacy_assertions"] == [
        {
            "asset_legacy_assertion_id": 1,
            "asset_id": 17,
            "assertion_kind": "ambiguous_asset_path",
            "associated_occurrence_id": None,
            "recorded_at": detail["legacy_assertions"][0]["recorded_at"],
        }
    ]
    assert "old/photo.jpg" not in str(detail)
    assert legacy_assertion_summary(path) == {
        "total": 1,
        "ambiguous": 1,
        "unassociated": 1,
        "by_classification": {"ambiguous_asset_path": 1},
    }


def test_writer_persists_roots_provenance_fingerprints_and_adoption_outcomes(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            source_root = writer.register_managed_root(
                ManagedRootRecord("source", "source-id", "source", created_at=NOW)
            )
            managed_root = writer.register_managed_root(
                ManagedRootRecord("managed", "managed-id", "media", created_at=NOW)
            )
            post = writer.upsert_post(PostRecord("x", "1", NOW)).id
            occurrence = writer.upsert_media(
                post,
                MediaOccurrenceRecord("media:0", 0, "image", observed_at=NOW),
            ).id
            writer.add_occurrence_source(
                OccurrenceSourceRecord(occurrence, "legacy_local", "images/a.jpg", NOW, source_root)
            )
            writer.link_asset(
                occurrence,
                AssetRecord("a" * 64, None, None, 4, "legacy_reference", None, NOW, "fixture"),
            )
            writer.add_asset_location(
                AssetLocationRecord(1, managed_root, "sha256/aa/bb/hash", byte_size=4)
            )
            run_id = writer.begin_adoption_run(
                AdoptionRunRecord(
                    managed_root,
                    "managed-id",
                    "adoption-v1",
                    NOW,
                    source_root,
                    "source-id",
                    limits=AdoptionLimits(4),
                )
            )
            item_id = writer.record_adoption_item(
                AdoptionItemRecord(run_id, "item-1", "missing", media_occurrence_id=occurrence)
            )
            writer.record_adoption_attempt(
                AdoptionAttemptRecord(item_id, 1, "missing", NOW, diagnostic="not found")
            )
            writer.add_asset_fingerprint(
                AssetFingerprintRecord(
                    1, "sha256", "a" * 64, "sha256", "sha256-v1", "adoption", "verified", NOW
                )
            )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM occurrence_sources").fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute("SELECT outcome FROM adoption_items").fetchone()[0]
            == "missing"
        )
        assert database.doctor()["ok"] is True


def test_writer_refuses_to_reassign_a_managed_location(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            root_id = writer.register_managed_root(
                ManagedRootRecord("managed", "managed-id", "media", created_at=NOW)
            )
            post = writer.upsert_post(PostRecord("x", "1", NOW)).id
            first_occurrence = writer.upsert_media(
                post, MediaOccurrenceRecord("media:0", 0, "image", observed_at=NOW)
            ).id
            second_occurrence = writer.upsert_media(
                post, MediaOccurrenceRecord("media:1", 1, "image", observed_at=NOW)
            ).id
            first_asset = writer.link_asset(
                first_occurrence,
                AssetRecord("a" * 64, None, None, 1, "managed", None, NOW, "calculated"),
            )
            second_asset = writer.link_asset(
                second_occurrence,
                AssetRecord("b" * 64, None, None, 1, "managed", None, NOW, "calculated"),
            )
            path = f"sha256/aa/aa/{'a' * 64}"
            writer.add_asset_location(AssetLocationRecord(first_asset, root_id, path))
            with pytest.raises(ValueError, match="another asset"):
                writer.add_asset_location(AssetLocationRecord(second_asset, root_id, path))


def test_x_likes_local_path_without_sha_is_occurrence_provenance(tmp_path: Path) -> None:
    source = tmp_path / "likes.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO posts(post_id, post_url, imported_at, fetched_at, fetch_status) "
            "VALUES ('1', 'https://x.test/1', ?, ?, 'fetched')",
            (NOW, NOW),
        )
        connection.execute(
            "INSERT INTO media(post_id, media_index, media_type, source_url, local_path) "
            "VALUES ('1', 0, 'image', 'https://x.test/image', 'media/no-sha.jpg')"
        )
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        import_x_likes_database(database, source)
        row = database.connection.execute(
            "SELECT source_kind, relative_path FROM occurrence_sources"
        ).fetchone()
        assert tuple(row) == ("legacy_local", "media/no-sha.jpg")
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
