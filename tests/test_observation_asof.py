"""As-of revision playback (bead data-processing-i94, change
add-observation-revision-asof-index): the playback index, its EXPLAIN
contract, and the pinned append-only enforcement on the two provenance
tables."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase

AS_OF_QUERY = """SELECT observation_revision_id, observed_at, collection_data,
                        import_run_id, raw_observation_id
                     FROM observation_revisions
                    WHERE observation_id = ?
                      AND observation_revision_id <= ?
                    ORDER BY observation_revision_id DESC
                    LIMIT 1"""


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    return tmp_path / "catalog.sqlite3"


def _seed_revision(connection: sqlite3.Connection) -> int:
    import_run = connection.execute(
        """INSERT INTO import_runs (source_kind, source_reference, source_digest,
                                   source_size, status, started_at)
           VALUES ('test', 'asof', ?, 1, 'complete', '2026-01-01T00:00:00Z')""",
        ("0" * 64,),
    )
    assert import_run.lastrowid is not None
    platform = connection.execute(
        "SELECT platform_id FROM platforms WHERE platform_key = 'gelbooru'"
    ).fetchone()
    assert platform is not None
    post = connection.execute(
        """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
           VALUES (?, 'asof-1', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
        (int(platform[0]),),
    )
    assert post.lastrowid is not None
    observation = connection.execute(
        """INSERT INTO observations (subject_kind, subject_id, event_type,
                                    source_kind, source_event_key, observed_at)
           VALUES ('post', ?, 'noted', 'test', 'asof:1', '2026-01-01T00:00:00Z')""",
        (int(post.lastrowid),),
    )
    assert observation.lastrowid is not None
    revision = connection.execute(
        """INSERT INTO observation_revisions
               (observation_id, observed_at, import_run_id)
           VALUES (?, '2026-01-01T00:00:00Z', ?)""",
        (int(observation.lastrowid), int(import_run.lastrowid)),
    )
    assert revision.lastrowid is not None
    # a retained source report: row-level triggers need a row to fire on
    payload = b"{}"
    digest = hashlib.sha256(payload).hexdigest()
    connection.execute(
        """INSERT INTO raw_payloads (sha256, media_type, payload, byte_size)
           VALUES (?, 'application/json', ?, ?)""",
        (digest, payload, len(payload)),
    )
    raw = connection.execute(
        """INSERT INTO raw_observations
               (raw_payload_id, platform_id, object_kind, native_id, media_type,
                observed_at)
           SELECT raw_payload_id, ?, 'post', 'asof-raw', 'application/json',
                  '2026-01-01T00:00:00Z'
             FROM raw_payloads WHERE sha256 = ?""",
        (int(platform[0]), digest),
    )
    assert raw.lastrowid is not None
    return int(revision.lastrowid)


def test_index_present_and_explain_is_a_seek(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        index_sql = connection.execute(
            """SELECT sql FROM sqlite_master
                WHERE type = 'index'
                  AND name = 'idx_observation_revisions_observation_playback'"""
        ).fetchone()
        assert index_sql is not None
        assert "observation_revision_id DESC" in str(index_sql[0])
        revision_id = 0
        with database.transaction():
            revision_id = _seed_revision(connection)
        plan_rows = connection.execute(
            f"EXPLAIN QUERY PLAN {AS_OF_QUERY}", (1, revision_id)
        ).fetchall()
        plan = " | ".join(str(row[3]) for row in plan_rows)
        assert "SCAN" not in plan.upper().replace("SEARCH", "")
        assert "USING INDEX idx_observation_revisions_observation_playback" in plan
        assert "TEMP B-TREE" not in plan


def test_provenance_tables_are_insert_only(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        with database.transaction():
            _seed_revision(connection)
        for statement in (
            "UPDATE observation_revisions SET observed_at = 'x'",
            "DELETE FROM observation_revisions",
            "UPDATE raw_observations SET native_id = 'x'",
            "DELETE FROM raw_observations",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                connection.execute(statement)
        connection.rollback()
