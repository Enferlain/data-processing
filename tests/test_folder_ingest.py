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
    assert first["sidecar_parsed"] == 1
    assert first["sidecar_orphan"] == 0
    assert first["sidecar_pool_tags"] == 0
    assert first["other_files"] == 1

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

        # the sidecar is retained as parsed operator-supplied evidence on
        # its seed (bead data-processing-h6d): one import run, one raw
        # observation, tags categorized, no provider tag tables touched
        assert (
            connection.execute(
                "SELECT count(*) FROM import_runs WHERE source_kind = 'folder_sidecar'"
            ).fetchone()[0]
            == 1
        )
        raw = connection.execute(
            """SELECT r.payload FROM raw_observations o
                JOIN raw_payloads r USING(raw_payload_id)
               WHERE o.object_kind = 'sidecar_tags'"""
        ).fetchone()
        assert raw is not None
        import json as _json

        document = _json.loads(raw[0])
        tags = {entry["name"]: entry["category"] for entry in document["tags"]}
        assert tags == {"someone": "artist", "1girl": "general"}
        assert connection.execute("SELECT count(*) FROM post_tags").fetchone()[0] == 0

    # rerun: same bytes are existing seeds, never duplicated
    with CatalogDatabase(catalog) as database:
        second = ingest_folder(database, directory)
    assert second["materialized"] == 0
    assert second["existing"] == 2
    assert second["sidecar_parsed"] == 1
    with CatalogDatabase(catalog) as database:
        count = database.connection.execute("SELECT count(*) FROM discovery_file_seeds").fetchone()[
            0
        ]
        # the rerun reuses the completed sidecar import run and the raw
        # attach is conflict-idempotent: still exactly one observation
        raw_count = database.connection.execute(
            "SELECT count(*) FROM raw_observations WHERE object_kind = 'sidecar_tags'"
        ).fetchone()[0]
    assert count == 2
    assert raw_count == 1


def test_folder_ingest_parses_pool_metatags_and_skips_orphan_sidecars(
    tmp_path: Path,
) -> None:
    """Pool metatags are counted for the pool bead; a sidecar without a
    media twin is counted as orphan and never opened."""
    from media_catalog.imports.sidecar import parse_sidecar

    parsed = parse_sidecar(
        "character:cyrene (demiurge) (honkai: star rail),"
        " copyright:honkai: star rail, meta:absurdres, pool:12345,"
        " pool:notanumber, species:kemono_comic, 1girl, lilitiaoyi\n"
    )
    assert dict(parsed.tags)["cyrene (demiurge) (honkai: star rail)"] == "character"
    assert dict(parsed.tags)["honkai: star rail"] == "copyright"
    assert dict(parsed.tags)["absurdres"] == "meta"
    assert dict(parsed.tags)["kemono_comic"] == "unknown"
    assert dict(parsed.tags)["1girl"] == "general"
    assert dict(parsed.tags)["lilitiaoyi"] == "general"
    assert parsed.pool_ids == ("12345",)

    catalog = tmp_path / "catalog.sqlite3"
    directory = tmp_path / "grabber2"
    directory.mkdir()
    (directory / "ccc.png").write_bytes(_png((0, 255, 0)))
    (directory / "ccc.png.txt").write_text("pool:777, artist:x")
    (directory / "orphan.jpg.txt").write_text("artist:nobody")
    with CatalogDatabase(catalog) as database:
        result = ingest_folder(database, directory)
    assert result["media_files"] == 1
    assert result["sidecar_files"] == 2
    assert result["sidecar_parsed"] == 1
    assert result["sidecar_orphan"] == 1
    assert result["sidecar_pool_tags"] == 1


def test_folder_ingest_rejects_missing_directory(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    import pytest

    with CatalogDatabase(catalog) as database, pytest.raises(ValueError, match="not a directory"):
        ingest_folder(database, tmp_path / "nope")
