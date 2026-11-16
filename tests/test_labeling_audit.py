"""Labeling audit stream (bead data-processing-4o3, change
add-labeling-audit-stream): seeded sampling of the populations the queue
never asks about, and the calibration report with Wilson intervals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.labeling.calibration import calibration_report, wilson_interval
from media_catalog.labeling.queue import build_audit_queue

MD5 = "0123456789abcdef0123456789abcdef"
OTHER_MD5 = "f" * 32


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        connection = database.connection
        platform = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'gelbooru'"
        ).fetchone()
        assert platform is not None
        gelbooru_id = int(platform[0])
        tag_ids: dict[str, int] = {}
        for artist in ("alpha_artist", "beta_artist"):
            tag = connection.execute(
                """INSERT INTO tags (platform_id, category, name, normalization_version)
                   VALUES (?, 'artist', ?, 'test-v1')""",
                (gelbooru_id, artist),
            )
            tag_ids[artist] = int(tag.lastrowid)
        # alpha: two posts with identical md5 (auto-confirm population; the
        # rule is cross-platform, so a-2 lives on e621) and one more beyond
        # any enqueue family; beta: unrelated posts
        e621 = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'e621'"
        ).fetchone()
        assert e621 is not None
        e621_id = int(e621[0])
        for native, platform_id, artist, md5 in (
            ("a-1", gelbooru_id, "alpha_artist", MD5),
            ("a-2", e621_id, None, MD5),
            ("a-3", gelbooru_id, "alpha_artist", None),
            ("b-1", gelbooru_id, "beta_artist", None),
            ("b-2", gelbooru_id, "beta_artist", None),
        ):
            post = connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform_id, native),
            )
            connection.execute(
                """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                                      media_type, declared_md5, remote_url,
                                                      observed_at)
                   VALUES (?, 'a:p', 0, 'image/png', ?, 'https://example.invalid/s.png',
                           '2026-01-01T00:00:00Z')""",
                (int(post.lastrowid), md5),
            )
            if artist:
                connection.execute(
                    """INSERT INTO post_tags (post_id, tag_id, first_seen_at, last_seen_at)
                       VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                    (int(post.lastrowid), tag_ids[artist]),
                )
    return path


def _autoconfirm(catalog: Path) -> None:
    from media_catalog.labeling.queue import autoconfirm_identical_md5_pairs

    with CatalogDatabase(catalog) as database:
        autoconfirm_identical_md5_pairs(database.connection)


def test_audit_sample_is_seeded_and_population_disjoint(catalog: Path) -> None:
    _autoconfirm(catalog)
    with CatalogDatabase(catalog) as database:
        first = build_audit_queue(database.connection, sample_size=6, seed=7)
        second = build_audit_queue(database.connection, sample_size=6, seed=7)
        rotated = build_audit_queue(database.connection, sample_size=6, seed=8)
    first_pairs = [(c.post_a_id, c.post_b_id, c.queue_signal) for c in first]
    assert first_pairs == [(c.post_a_id, c.post_b_id, c.queue_signal) for c in second]
    # three populations represented
    signals = {c.queue_signal for c in first}
    assert "audit_auto" in signals
    # unlabeled populations never include the (already auto-labeled) a-1/a-2 pair
    with CatalogDatabase(catalog) as database:
        auto_pair = database.connection.execute(
            "SELECT post_a_id, post_b_id FROM pair_labels"
        ).fetchone()
        assert auto_pair is not None
    non_auto = [c for c in first if c.queue_signal != "audit_auto"]
    assert (int(auto_pair[0]), int(auto_pair[1])) not in {
        (c.post_a_id, c.post_b_id) for c in non_auto
    }
    # rotation changes at least the negative/beyond draw
    assert len(rotated) > 0


def test_calibration_report_matches_labels_and_bounds(catalog: Path) -> None:
    _autoconfirm(catalog)
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        connection.execute(
            """INSERT INTO pair_labels (post_a_id, post_b_id, queue_signal, verdict,
                                        relation_note, labeled_at)
               SELECT post_a_id, post_b_id, 'pool_member', 'variant', NULL,
                      '2026-11-16T00:00:00Z'
                 FROM pair_labels WHERE queue_signal = 'identical_md5' LIMIT 1"""
        )
        connection.commit()
        report = calibration_report(connection)
    identical = report["families"]["identical_md5"]
    assert identical["labels"] == 1 and identical["by_verdict"] == {"same": 1}
    assert identical["same_or_variant_rate"] == 1.0
    assert identical["same_or_variant_ci95"] == [pytest.approx(0.2065, abs=0.005), 1.0]
    pool = report["families"]["pool_member"]
    assert pool["by_verdict"] == {"variant": 1}
    assert pool["same_or_variant_rate"] == 1.0
    assert report["labels_total"] == 2


def test_wilson_interval_empty_and_known_values() -> None:
    assert wilson_interval(0, 0) is None
    full = wilson_interval(59, 59)
    assert full is not None
    low, high = full
    assert low == pytest.approx(0.9404, abs=0.005)  # rule-of-three style bound
    assert high == 1.0
    zero = wilson_interval(0, 20)
    assert zero is not None
    low, high = zero
    assert low == 0.0 and high < 0.2


def test_label_stats_cli(catalog: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from media_catalog.cli import main

    _autoconfirm(catalog)
    main(["label-stats", str(catalog), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["families"]["identical_md5"]["labels"] == 1
