from __future__ import annotations

import hashlib
import socket
import sqlite3
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.imports.x_likes_db import import_x_likes_database
from media_catalog.records import ManagedRootRecord, OccurrenceSourceRecord
from media_catalog.storage.adoption import adopt_assets, plan_adoption
from media_catalog.storage.queries import find_exact_duplicates
from media_catalog.writer import CatalogWriter
from x_likes.database import SCHEMA

NOW = "2026-08-09T00:00:00Z"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _md5(value: bytes) -> str:
    return hashlib.md5(value, usedforsecurity=False).hexdigest()


def _legacy_fixture(root: Path) -> Path:
    shared = b"duplicate local bytes"
    (root / "media").mkdir()
    (root / "media" / "first.bin").write_bytes(shared)
    (root / "media" / "second.bin").write_bytes(shared)
    (root / "media" / "without-hash.bin").write_bytes(b"unasserted local bytes")
    database = root / "likes.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO posts(post_id, post_url, imported_at, fetched_at, fetch_status) "
            "VALUES ('1', 'https://x.test/1', ?, ?, 'fetched')",
            (NOW, NOW),
        )
        for index, path in enumerate(("media/first.bin", "media/second.bin")):
            connection.execute(
                "INSERT INTO media(post_id, media_index, media_type, source_url, local_path, "
                "file_size, md5, sha256) VALUES ('1', ?, 'image', ?, ?, ?, ?, ?)",
                (
                    index,
                    f"https://x.test/{index}",
                    path,
                    len(shared),
                    _md5(shared),
                    _sha256(shared),
                ),
            )
        connection.execute(
            "INSERT INTO media(post_id, media_index, media_type, source_url, local_path) "
            "VALUES ('1', 2, 'image', 'https://x.test/2', 'media/without-hash.bin')"
        )
    return database


def test_x_likes_paths_adopt_offline_without_changing_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    legacy_database = _legacy_fixture(source_root)
    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    catalog_path = tmp_path / "catalog.sqlite3"
    source_snapshot = {
        path.relative_to(source_root): _sha256(path.read_bytes())
        for path in source_root.rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network attempted")),
    )

    with CatalogDatabase(catalog_path) as catalog:
        import_x_likes_database(catalog, legacy_database)
        original_sources = list(
            catalog.connection.execute(
                "SELECT media_occurrence_id, relative_path FROM occurrence_sources "
                "ORDER BY occurrence_source_id"
            )
        )
        assert [row["relative_path"] for row in original_sources] == [
            "media/first.bin",
            "media/second.bin",
            "media/without-hash.bin",
        ]

    plan = plan_adoption(catalog_path, source_root, managed_root)
    assert plan.planned_count == 3
    with CatalogDatabase(catalog_path) as catalog:
        first = adopt_assets(catalog, source_root, managed_root, plan=plan)
        assert first.status == "complete"
        assert first.completed_count == 3
        assert catalog.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 2
        assert (
            catalog.connection.execute("SELECT COUNT(*) FROM asset_locations").fetchone()[0] == 2
        )
        assert (
            catalog.connection.execute("SELECT COUNT(*) FROM occurrence_assets").fetchone()[0] == 3
        )
        duplicates = find_exact_duplicates(catalog)
        assert len(duplicates) == 1
        assert duplicates[0]["occurrence_count"] == 2

        second = adopt_assets(catalog, source_root, managed_root)
        assert second.status == "complete"
        assert set(second.outcomes) == {"existing"}
        assert catalog.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 2
        assert (
            catalog.connection.execute("SELECT COUNT(*) FROM asset_locations").fetchone()[0] == 2
        )
        assert (
            catalog.connection.execute("SELECT COUNT(*) FROM occurrence_assets").fetchone()[0] == 3
        )

    assert {
        path.relative_to(source_root): _sha256(path.read_bytes())
        for path in source_root.rglob("*")
        if path.is_file()
    } == source_snapshot
    managed_files = [path for path in (managed_root / "sha256").rglob("*") if path.is_file()]
    assert len(managed_files) == 2


def test_x_likes_import_after_adoption_preserves_managed_verification(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    legacy_database = _legacy_fixture(source_root)
    # Seed occurrence/source provenance first, then adopt bytes without any
    # imported exact assertions.  A later source refresh supplies a conflicting
    # legacy MD5 and exercises the writer merge policy.
    with sqlite3.connect(legacy_database) as connection:
        connection.execute("UPDATE media SET md5 = NULL, sha256 = NULL")
    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    catalog_path = tmp_path / "catalog.sqlite3"

    with CatalogDatabase(catalog_path) as catalog:
        import_x_likes_database(catalog, legacy_database)
        assert catalog.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
        adopted = adopt_assets(catalog, source_root, managed_root)
        assert adopted.status == "complete"
        managed = catalog.connection.execute(
            """SELECT verified_md5, byte_size, storage_kind, verified_at,
                              verification_method
                         FROM assets ORDER BY asset_id LIMIT 1"""
        ).fetchone()
        assert tuple(managed)[1:] == (
            len(b"duplicate local bytes"),
            "managed",
            managed[3],
            "adoption",
        )
        managed_md5 = str(managed[0])
        managed_verified_at = str(managed[3])

    with sqlite3.connect(legacy_database) as connection:
        connection.execute(
            "UPDATE media SET md5 = ?, file_size = ?, sha256 = ? WHERE media_index = 0",
            ("f" * 32, 1, _sha256(b"duplicate local bytes")),
        )

    with CatalogDatabase(catalog_path) as catalog:
        report = import_x_likes_database(catalog, legacy_database)
        assert report.reused is False
        after = catalog.connection.execute(
            """SELECT verified_md5, byte_size, storage_kind, verified_at,
                             verification_method
                        FROM assets ORDER BY asset_id LIMIT 1"""
        ).fetchone()
        assert tuple(after) == (
            managed_md5,
            len(b"duplicate local bytes"),
            "managed",
            managed_verified_at,
            "adoption",
        )
        # The conflicting legacy claim remains occurrence/fingerprint
        # provenance instead of replacing the verified managed values.
        declared = catalog.connection.execute(
            "SELECT declared_md5 FROM media_occurrences WHERE source_key = 'x-likes:0'"
        ).fetchone()[0]
        assert declared == "f" * 32
        assert catalog.connection.execute(
            """SELECT fingerprint_value FROM asset_fingerprints
                WHERE fingerprint_kind = 'md5' AND verification_status = 'legacy'
                  AND fingerprint_value = ?""",
            ("f" * 32,),
        ).fetchone()[0] == "f" * 32


def test_gallery_dl_output_remains_untrusted_until_normal_adoption_succeeds(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "gallery-dl-staging"
    source_root.mkdir()
    relative_path = "gallery-dl-output.bin"
    payload = b"externally produced bytes are not preverified"
    (source_root / relative_path).write_bytes(payload)
    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    catalog_path = tmp_path / "catalog.sqlite3"
    source_info = source_root.stat()

    with CatalogDatabase(catalog_path) as catalog:
        writer = CatalogWriter(catalog)
        with catalog.transaction():
            platform_id = int(
                catalog.connection.execute(
                    "SELECT platform_id FROM platforms WHERE platform_key = 'x'"
                ).fetchone()[0]
            )
            post_id = int(
                catalog.connection.execute(
                    """INSERT INTO posts (
                           platform_id, native_post_id, first_seen_at, last_seen_at
                       ) VALUES (?, 'gallery-dl-fixture', ?, ?)""",
                    (platform_id, NOW, NOW),
                ).lastrowid
            )
            occurrence_id = int(
                catalog.connection.execute(
                    """INSERT INTO media_occurrences (
                           post_id, source_key, media_index, media_type, observed_at
                       ) VALUES (?, 'gallery-dl:0', 0, 'binary', ?)""",
                    (post_id, NOW),
                ).lastrowid
            )
            source_id = writer.register_managed_root(
                ManagedRootRecord(
                    "source",
                    f"{source_info.st_dev}:{source_info.st_ino}",
                    "gallery-dl-staging",
                    str(source_root),
                    NOW,
                )
            )
            writer.add_occurrence_source(
                OccurrenceSourceRecord(
                    occurrence_id,
                    "legacy_local",
                    relative_path,
                    NOW,
                    source_id,
                )
            )
        assert catalog.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0

    plan = plan_adoption(catalog_path, source_root, managed_root)
    assert plan.planned_count == 1
    assert not list((managed_root / "sha256").rglob("*"))
    with CatalogDatabase(catalog_path) as catalog:
        adopted = adopt_assets(catalog, source_root, managed_root, plan=plan)
        assert adopted.status == "complete"
        asset = catalog.connection.execute("SELECT * FROM assets").fetchone()
        assert asset["verified_sha256"] == _sha256(payload)
        assert asset["verified_md5"] == _md5(payload)
        assert asset["verification_method"] == "adoption"
        location = catalog.connection.execute(
            "SELECT relative_path FROM asset_locations"
        ).fetchone()[0]
        assert (managed_root / location).read_bytes() == payload
