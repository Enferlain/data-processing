"""Labeling tool: pair queues and label recording (bead data-processing-w7j)."""

from __future__ import annotations

from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.labeling.queue import build_queue
from media_catalog.labeling.server import LabelingState

NOW = "2026-11-07T14:00:00Z"


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path):
        pass
    return path


def _seed_pair(catalog: Path, *, md5_a: str, md5_b: str, tag: str) -> tuple[int, int]:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        ids = []
        for index, md5 in enumerate((md5_a, md5_b)):
            platform = ("e621", "gelbooru")[index]
            connection.execute(
                "INSERT OR IGNORE INTO platforms (platform_key) VALUES (?)", (platform,)
            )
            platform_id = int(
                connection.execute(
                    "SELECT platform_id FROM platforms WHERE platform_key = ?", (platform,)
                ).fetchone()[0]
            )
            connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, availability,
                                          first_seen_at, last_seen_at)
                   VALUES (?, ?, 'available', ?, ?)""",
                (platform_id, f"{900 + index}", NOW, NOW),
            )
            post_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            connection.execute(
                """INSERT INTO media_occurrences
                       (post_id, source_key, media_index, media_type, role,
                        remote_url, declared_md5, availability, observed_at)
                   VALUES (?, 'seed', 0, 'original', 'original',
                           'https://example.invalid/a.jpg', ?, 'available', ?)""",
                (post_id, md5, NOW),
            )
            connection.execute(
                "INSERT OR IGNORE INTO tags (platform_id, name, category,"
                " normalization_version, created_at)"
                " VALUES ((SELECT platform_id FROM platforms WHERE platform_key='e621'),"
                " ?, 'artist', 'seed-v1', ?)",
                (tag, NOW),
            )
            tag_id = int(
                connection.execute("SELECT tag_id FROM tags WHERE name = ?", (tag,)).fetchone()[0]
            )
            connection.execute(
                "INSERT INTO post_tags (post_id, tag_id, first_seen_at, last_seen_at)"
                " VALUES (?, ?, ?, ?)",
                (post_id, tag_id, NOW, NOW),
            )
            ids.append(post_id)
        connection.commit()
        return ids[0], ids[1]


def test_identical_md5_cross_platform_queues(catalog: Path) -> None:
    a, b = _seed_pair(catalog, md5_a="a" * 32, md5_b="a" * 32, tag="artist_x")
    with CatalogDatabase(catalog) as database:
        queue = build_queue(database.connection)
    assert (a, b, "identical_md5") in {(p.post_a_id, p.post_b_id, p.queue_signal) for p in queue}


def test_same_artist_contrast_pairs_queue(catalog: Path) -> None:
    a, b = _seed_pair(catalog, md5_a="a" * 32, md5_b="b" * 32, tag="artist_x")
    with CatalogDatabase(catalog) as database:
        queue = build_queue(database.connection)
    signals = {(p.post_a_id, p.post_b_id): p.queue_signal for p in queue}
    assert signals.get((a, b)) == "same_artist_contrast"


def test_labels_record_with_history_and_exclude_requeue(catalog: Path) -> None:
    a, b = _seed_pair(catalog, md5_a="a" * 32, md5_b="a" * 32, tag="artist_x")
    with CatalogDatabase(catalog) as database:
        state = LabelingState(database.connection, catalog.parent)
        state.record(0, "variant", "text overlay removed", NOW)
        row = database.connection.execute(
            "SELECT verdict, relation_note FROM pair_labels WHERE post_a_id = ? AND post_b_id = ?",
            (a, b),
        ).fetchone()
        assert tuple(row) == ("variant", "text overlay removed")
        history = database.connection.execute(
            "SELECT prior_verdict, verdict FROM pair_label_decisions"
        ).fetchall()
        assert [tuple(h) for h in history] == [("variant", "variant")]
        # The labeled pair drops out of a rebuilt queue.
        assert all((p.post_a_id, p.post_b_id) != (a, b) for p in build_queue(database.connection))


def test_verdict_vocabulary_is_enforced(catalog: Path) -> None:
    _seed_pair(catalog, md5_a="a" * 32, md5_b="b" * 32, tag="artist_x")
    with (
        CatalogDatabase(catalog) as database,
        pytest.raises(ValueError, match="verdict"),
    ):
        LabelingState(database.connection, catalog.parent).record(0, "similar-ish", None, NOW)
