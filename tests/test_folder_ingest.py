"""Bulk local-folder ingest: idempotent bare-file seeds, no posts/identities."""

from __future__ import annotations

import io
from pathlib import Path

from media_catalog.database import CatalogDatabase
from media_catalog.imports.folder import ingest_folder


def _png(color: tuple[int, int, int]) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _directory(tmp_path: Path) -> Path:
    directory = tmp_path / "grabber"
    directory.mkdir()
    (directory / "aaa.png").write_bytes(_png((255, 0, 0)))
    (directory / "bbb.png").write_bytes(_png((0, 255, 0)))
    (directory / "aaa.png.txt").write_text("artist:someone, 1girl")
    (directory / "readme.md").write_text("not media")
    return directory


def test_folder_ingest_is_idempotent_and_creates_no_posts(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    directory = _directory(tmp_path)
    with CatalogDatabase(catalog) as database:
        first = ingest_folder(database, directory, note="grabber batch")
    assert first["media_files"] == 2
    assert first["materialized"] == 2
    assert first["existing"] == 0
    assert first["sidecar_files"] == 1
    assert first["other_files"] == 1
    assert first["failed_count"] == 0

    with CatalogDatabase(catalog) as database:
        connection = database.connection
        seeds = connection.execute(
            "SELECT count(*), count(DISTINCT verified_md5) FROM discovery_file_seeds"
        ).fetchone()
        assert seeds[0] == 2 and seeds[1] == 2
        # no posts, no platform identities from a folder scan
        assert connection.execute("SELECT count(*) FROM posts").fetchone()[0] == 0
        # identity is computed, never trusted: the seed md5 matches the bytes
        import hashlib

        expected = hashlib.md5(_png((255, 0, 0))).hexdigest()
        stored = {
            row[0] for row in connection.execute("SELECT verified_md5 FROM discovery_file_seeds")
        }
        assert expected in stored

    # rerun: same bytes are existing seeds, never duplicated
    with CatalogDatabase(catalog) as database:
        second = ingest_folder(database, directory)
    assert second["materialized"] == 0
    assert second["existing"] == 2
    with CatalogDatabase(catalog) as database:
        count = (
            CatalogDatabase(catalog)
            and database.connection.execute("SELECT count(*) FROM discovery_file_seeds").fetchone()[
                0
            ]
        )
    assert count == 2


def test_folder_ingest_rejects_missing_directory(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    import pytest

    with CatalogDatabase(catalog) as database, pytest.raises(ValueError, match="not a directory"):
        ingest_folder(database, tmp_path / "nope")
