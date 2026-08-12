from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase, SchemaVersionError
from media_catalog.storage.verification import (
    VerificationError,
    verify_managed_storage,
)


def _identity(path: Path) -> str:
    info = path.stat()
    return f"{info.st_dev}:{info.st_ino}"


def _cas_path(root: Path, payload: bytes) -> tuple[str, Path]:
    digest = hashlib.sha256(payload).hexdigest()
    relative = f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"
    target = root / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    return relative, target


def _catalog(path: Path, managed: Path, locations: list[tuple[str, str, int | None]]) -> int:
    with CatalogDatabase(path) as database:
        identity = _identity(managed)
        with database.transaction():
            cursor = database.connection.execute(
                "INSERT INTO managed_roots(root_kind, root_identity, display_label, created_at) "
                "VALUES ('managed', ?, 'media', '2026-08-09T00:00:00Z')",
                (identity,),
            )
            root_id = int(cursor.lastrowid)
            for index, (relative, digest, byte_size) in enumerate(locations, start=1):
                database.connection.execute(
                    "INSERT INTO assets(asset_id, verified_sha256, byte_size, storage_kind, "
                    "verification_method) VALUES (?, ?, ?, 'managed', 'test')",
                    (index, digest, byte_size),
                )
                database.connection.execute(
                    "INSERT INTO asset_locations(asset_id, managed_root_id, relative_path, "
                    "location_kind, byte_size, recorded_sha256, created_at) "
                    "VALUES (?, ?, ?, 'managed', ?, ?, '2026-08-09T00:00:00Z')",
                    (index, root_id, relative, byte_size, digest),
                )
    return root_id


def test_verify_reports_valid_missing_corrupt_orphan_and_stale_without_mutation(
    tmp_path: Path,
) -> None:
    managed = tmp_path / "managed"
    managed.mkdir()
    payload = b"valid bytes"
    valid_relative, _ = _cas_path(managed, payload)
    digest = hashlib.sha256(payload).hexdigest()

    missing_payload = b"missing bytes"
    missing_digest = hashlib.sha256(missing_payload).hexdigest()
    missing_relative = f"sha256/{missing_digest[:2]}/{missing_digest[2:4]}/{missing_digest}"

    corrupt_digest = hashlib.sha256(b"the expected bytes").hexdigest()
    corrupt_relative = f"sha256/{corrupt_digest[:2]}/{corrupt_digest[2:4]}/{corrupt_digest}"
    corrupt_target = managed / corrupt_relative
    corrupt_target.parent.mkdir(parents=True)
    corrupt_target.write_bytes(b"corrupt bytes")
    corrupt_target.write_bytes(b"changed")

    orphan_relative, _ = _cas_path(managed, b"orphan bytes")
    (managed / "staging").mkdir()
    (managed / "staging" / "stale-stage").write_bytes(b"left over")

    catalog = tmp_path / "catalog.sqlite3"
    root_id = _catalog(
        catalog,
        managed,
        [
            (valid_relative, digest, len(payload)),
            (missing_relative, missing_digest, len(missing_payload)),
            (corrupt_relative, corrupt_digest, len(b"the expected bytes")),
        ],
    )
    before_catalog = catalog.read_bytes()
    before_stage = (managed / "staging" / "stale-stage").read_bytes()

    report = verify_managed_storage(catalog, managed, managed_root_id=root_id)

    assert len(report.valid) == 1
    assert len(report.missing) == 1
    assert len(report.corrupt) == 1
    assert any(f.relative_path == orphan_relative for f in report.orphaned)
    assert [f.relative_path for f in report.stale_staging] == ["staging/stale-stage"]
    assert report.ok is False
    assert catalog.read_bytes() == before_catalog
    assert (managed / "staging" / "stale-stage").read_bytes() == before_stage
    assert json.loads(report.to_json())["counts"]["orphaned"] == 1


def test_verify_rejects_symlinked_components_and_redacts_absolute_catalog_paths(
    tmp_path: Path,
) -> None:
    managed = tmp_path / "managed"
    managed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    payload = b"bytes"
    digest = hashlib.sha256(payload).hexdigest()
    (outside / digest).write_bytes(payload)
    (managed / "sha256").symlink_to(outside, target_is_directory=True)

    catalog = tmp_path / "catalog.sqlite3"
    root_id = _catalog(catalog, managed, [("/private/catalog/path", digest, len(payload))])
    report = verify_managed_storage(catalog, managed, managed_root_id=root_id)

    # The catalog path is rejected before any symlinked component is opened.
    assert report.unsafe
    assert "/private/catalog/path" not in report.to_json()


def test_verify_requires_registered_descriptor_identity(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    managed.mkdir()
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        root_id = int(
            database.connection.execute(
                "INSERT INTO managed_roots(root_kind, root_identity, display_label, created_at) "
                "VALUES ('managed', 'wrong:identity', 'media', '2026-08-09T00:00:00Z')"
            ).lastrowid
        )
    report = verify_managed_storage(catalog, managed, managed_root_id=root_id)
    assert report.counts["unsafe"] == 1
    assert "identity" in (report.unsafe[0].detail or "")


def test_verify_refuses_older_catalog_without_side_effects(tmp_path: Path) -> None:
    catalog = tmp_path / "old.sqlite3"
    managed = tmp_path / "managed"
    managed.mkdir()
    with sqlite3.connect(catalog) as connection:
        connection.execute("PRAGMA user_version = 3")
        connection.commit()
    before = catalog.read_bytes()
    with pytest.raises(SchemaVersionError):
        verify_managed_storage(catalog, managed)
    assert catalog.read_bytes() == before


def test_verify_requires_root_id_when_catalog_has_multiple_managed_roots(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    managed.mkdir()
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        identity = _identity(managed)
        database.connection.executemany(
            "INSERT INTO managed_roots(root_kind, root_identity, display_label, created_at) "
            "VALUES ('managed', ?, ?, '2026-08-09T00:00:00Z')",
            [(identity, "one"), (identity + ":2", "two")],
        )
    with pytest.raises(VerificationError):
        verify_managed_storage(catalog, managed)
