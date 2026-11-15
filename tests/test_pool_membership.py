"""Pool co-membership labeling family (bead data-processing-rip, change
add-pool-membership-evidence): provider-declared pool membership
(post_pool_observations, recorded by the existing metadata writer) enqueues
pairs within one platform namespace and never decides a verdict."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.labeling.queue import build_queue


def _insert_post(connection: sqlite3.Connection, platform_id: int, native: str) -> int:
    post = connection.execute(
        """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
           VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
        (platform_id, native),
    )
    connection.execute(
        """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                              media_type, remote_url, observed_at)
           VALUES (?, 'pm:p', 0, 'image/png', 'https://example.invalid/s.png',
                   '2026-01-01T00:00:00Z')""",
        (int(post.lastrowid),),
    )
    return int(post.lastrowid)


def _observe_pool(connection: sqlite3.Connection, post_id: int, pool: str, digest: str) -> None:
    connection.execute(
        """INSERT INTO post_pool_observations
               (post_id, pool_native_id, observed_at, observation_digest)
           VALUES (?, ?, '2026-02-01T00:00:00Z', ?)""",
        (post_id, pool, digest),
    )


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        connection = database.connection
        e621 = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'e621'"
        ).fetchone()
        gelbooru = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'gelbooru'"
        ).fetchone()
        assert e621 is not None and gelbooru is not None
        e621_id, gelbooru_id = int(e621[0]), int(gelbooru[0])
        # e621: two posts share a pool, one is poolless; gelbooru: same numeric
        # pool id in a different platform namespace must never pair across.
        shared_a = _insert_post(connection, e621_id, "9001")
        shared_b = _insert_post(connection, e621_id, "9002")
        _insert_post(connection, e621_id, "9003")
        other_platform = _insert_post(connection, gelbooru_id, "7001")
        _observe_pool(connection, shared_a, "48507", "a" * 64)
        _observe_pool(connection, shared_b, "48507", "b" * 64)
        _observe_pool(connection, other_platform, "48507", "c" * 64)
    return path


def _pool_pairs(queue) -> list[tuple[int, int]]:
    return [
        (candidate.post_a_id, candidate.post_b_id)
        for candidate in queue
        if candidate.queue_signal == "pool_member"
    ]


def test_family_enqueues_within_platform_only(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        ids = {
            str(row[0]): int(row[1])
            for row in connection.execute("SELECT native_post_id, post_id FROM posts")
        }
        queue = build_queue(connection, limit=50)
        # the house add() helper emits each pair twice; compare as a set
        assert set(_pool_pairs(queue)) == {(ids["9001"], ids["9002"])}
        # the poolless post and the other-platform post join nothing
        # building the queue never writes a verdict
        assert (
            connection.execute(
                "SELECT count(*) FROM pair_labels WHERE queue_signal = 'pool_member'"
            ).fetchone()[0]
            == 0
        )


def test_labeled_pairs_never_reenqueue(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        pairs = _pool_pairs(build_queue(connection, limit=50))
        assert pairs, "expected the co-membership pair"
        a, b = pairs[0]
        connection.execute(
            """INSERT INTO pair_labels (post_a_id, post_b_id, queue_signal, verdict,
                                        relation_note, labeled_at)
               VALUES (?, ?, 'pool_member', 'variant', 'same pool, separate pages',
                       '2026-11-16T00:00:00Z')""",
            (a, b),
        )
        connection.commit()
        assert _pool_pairs(build_queue(connection, limit=50)) == []
