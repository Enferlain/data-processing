"""Operator tombstones: mark bad data as errored, never delete evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.tombstone import tombstone_lookup_run, tombstone_posts


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path):
        pass
    return path


def _seed_post(catalog: Path, native_id: str = "100") -> int:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        connection.execute(
            "INSERT INTO posts (platform_id, native_post_id, availability,"
            " first_seen_at, last_seen_at)"
            " VALUES ((SELECT platform_id FROM platforms WHERE platform_key = 'e621'),"
            " ?, 'available', '2026-11-05T00:00:00Z', '2026-11-05T00:00:00Z')",
            (native_id,),
        )
        post_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.commit()
        return post_id


def test_tombstone_posts_marks_without_deleting(catalog: Path) -> None:
    post_id = _seed_post(catalog)
    with CatalogDatabase(catalog) as database:
        result = tombstone_posts(database, [post_id], reason="degenerate query run 87")
    assert result["marked"] == [post_id]
    with CatalogDatabase(catalog) as database:
        row = database.connection.execute(
            "SELECT availability, status, deleted_at, title FROM posts WHERE post_id = ?",
            (post_id,),
        ).fetchone()
    assert row["status"] == "error-tombstone"
    assert row["availability"] == "unavailable"
    assert row["deleted_at"] is not None
    assert "degenerate query run 87" in row["title"]
    # The evidence row itself is intact.
    assert row is not None


def test_tombstone_posts_is_idempotent_and_reports_missing(catalog: Path) -> None:
    post_id = _seed_post(catalog)
    with CatalogDatabase(catalog) as database:
        first = tombstone_posts(database, [post_id], reason="first")
        second = tombstone_posts(database, [post_id, 999999], reason="first")
    assert first["marked"] == [post_id]
    assert second["marked"] == []
    assert second["already_tombstoned"] == [post_id]
    assert second["missing"] == [999999]


def test_tombstone_requires_a_reason(catalog: Path) -> None:
    post_id = _seed_post(catalog)
    with (
        CatalogDatabase(catalog) as database,
        pytest.raises(ValueError, match="reason"),
    ):
        tombstone_posts(database, [post_id], reason="  ")


def test_tombstone_lookup_run_marks_failed_with_diagnostic(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        connection.execute(
            "INSERT INTO posts (platform_id, native_post_id, availability,"
            " first_seen_at, last_seen_at)"
            " VALUES ((SELECT platform_id FROM platforms WHERE platform_key = 'e621'),"
            " '100', 'available', '2026-11-05T00:00:00Z', '2026-11-05T00:00:00Z')",
        )
        post_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            """INSERT INTO candidate_lookup_runs
                   (platform_id, instance_host, strategy, strategy_version,
                    adapter_version, schema_version, seed_post_id, seed_revision,
                    plan_digest, query_kind, material_digest, private_query_json,
                    status, request_limit, page_limit, result_limit,
                    time_limit_seconds, started_at, finished_at, result_count)
               VALUES ((SELECT platform_id FROM platforms WHERE platform_key = 'e621'),
                       '', 'verified_md5', 'v1', 'v1', 'v1',
                       ?, 'r1', ?, 'md5', ?, '{}', 'complete', 1, 1, 10, 10,
                       '2026-11-05T00:00:00Z', '2026-11-05T00:00:01Z', 1)""",
            (post_id, "a" * 64, "b" * 64),
        )
        run_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.commit()
        result = tombstone_lookup_run(database, run_id, reason="site-root query, fixed in 71ba216")
        assert result["status"] == "tombstoned"
        row = connection.execute(
            "SELECT status, termination_outcome, diagnostic_summary"
            " FROM candidate_lookup_runs WHERE candidate_lookup_run_id = ?",
            (run_id,),
        ).fetchone()
    assert row["status"] == "failed"
    assert "site-root query" in row["diagnostic_summary"]


def test_tombstone_lookup_run_rejects_unknown_run(catalog: Path) -> None:
    with (
        CatalogDatabase(catalog) as database,
        pytest.raises(ValueError, match="not found"),
    ):
        tombstone_lookup_run(database, 424242, reason="anything")
