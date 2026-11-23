"""Series object-kind widening (bead data-processing-7jx, change
``add-series-references``): the migration preserves rows, the records layer
round-trips a series reference, and candidate guards still reject it."""

from __future__ import annotations

from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.records.common import OBJECT_KINDS, validate_object_kind


def test_object_kinds_admit_series() -> None:
    assert "series" in OBJECT_KINDS
    assert validate_object_kind("series") == "series"
    with pytest.raises(ValueError):
        validate_object_kind("set")


def test_series_reference_round_trips_and_guards_hold(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        connection = database.connection
        pixiv = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
        ).fetchone()
        assert pixiv is not None
        connection.execute(
            """INSERT INTO platform_references (
                   platform_id, instance_host, object_kind, identifier_kind,
                   native_identifier, canonical_target_url, recognizer_name,
                   recognizer_version)
               VALUES (?, '', 'series', 'stable_id', '987654',
                       'https://www.pixiv.net/artworks/series/987654',
                       'provider-metadata', 'provider-metadata-v1')""",
            (int(pixiv[0]),),
        )
        row = connection.execute(
            """SELECT object_kind, identifier_kind, native_identifier,
                      resolved_account_id, resolved_post_id
                 FROM platform_references WHERE native_identifier = '987654'"""
        ).fetchone()
        assert tuple(row) == ("series", "stable_id", "987654", None, None)
        reference_id = int(
            connection.execute(
                "SELECT platform_reference_id FROM platform_references"
                " WHERE native_identifier = '987654'"
            ).fetchone()[0]
        )
        # evidence-only: a post candidate targeting the series reference is
        # rejected by the recreated guard trigger
        with pytest.raises(Exception, match="post candidate target reference"):
            connection.execute(
                """INSERT INTO post_match_candidates (
                       candidate_key, relation_kind, subject_post_id, target_post_id,
                       target_reference_id, score, score_version, created_at, updated_at)
                   VALUES ('x', 'same_work', 1, 2, ?, 0, 'test-v1',
                           '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (reference_id,),
            )


def test_migration_preserves_existing_reference_rows(tmp_path: Path) -> None:
    """The rebuild keeps ids and identities of pre-existing references."""
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        connection = database.connection
        danbooru = int(
            connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
            ).fetchone()[0]
        )
        connection.execute(
            """INSERT INTO platform_references (
                   platform_id, instance_host, object_kind, identifier_kind,
                   native_identifier, canonical_target_url, recognizer_name,
                   recognizer_version)
               VALUES (?, '', 'post', 'stable_id', '999888',
                       'https://danbooru.donmai.us/posts/999888',
                       'danbooru-post', 'platform-recognizers-v1')""",
            (danbooru,),
        )
        expected = connection.execute(
            """SELECT platform_reference_id, object_kind, native_identifier
                 FROM platform_references WHERE native_identifier = '999888'"""
        ).fetchone()
    # schema_version already 41; re-open verifies the rebuilt table state
    with CatalogDatabase(catalog) as database:
        actual = database.connection.execute(
            """SELECT platform_reference_id, object_kind, native_identifier
                 FROM platform_references WHERE native_identifier = '999888'"""
        ).fetchone()
        assert tuple(actual) == tuple(expected)
        check = database.connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'platform_references'"
        ).fetchone()[0]
        assert "'series'" in check
        assert database.connection.execute("PRAGMA foreign_key_check").fetchall() == []
