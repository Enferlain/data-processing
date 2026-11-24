"""As-of review reports (bead data-processing-2ai, change
``add-asof-review-reports``): snapshot reconstruction, change windows,
reversal counting, mixed-precision ordering, cutoff validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.temporal import (
    change_report,
    review_state_snapshot,
    validate_cutoff,
)

JAN = "2026-01-15T12:00:00Z"
FEB = "2026-02-15T12:00:00Z"
MAR = "2026-03-15T12:00:00Z"
# Fractional-second precision inside a whole-second cutoff must not reorder.
JAN_FRACTIONAL = "2026-01-15T12:00:00.500Z"


def _seed(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database, database.transaction():
        connection = database.connection
        connection.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name) VALUES ('e621', 'e621')"
        )
        platform_id = int(
            connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'e621'"
            ).fetchone()[0]
        )
        for native in ("a", "b"):
            connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, availability,
                                          first_seen_at, last_seen_at)
                   VALUES (?, ?, 'available', '2026-01-01T00:00:00Z',
                           '2026-01-01T00:00:00Z')""",
                (platform_id, native),
            )
        # pair label decided in January (unsure), reversed in March (different);
        # the first decision carries its own verdict as prior (house convention)
        connection.execute(
            """INSERT INTO pair_labels (post_a_id, post_b_id, queue_signal, verdict,
                                        relation_note, labeled_at)
               VALUES (1, 2, 'same_artist_contrast', 'unsure', NULL, ?)""",
            (JAN,),
        )
        connection.execute(
            """INSERT INTO pair_label_decisions (pair_label_id, prior_verdict, verdict,
                                                  note, decided_at)
               VALUES (1, 'unsure', 'unsure', NULL, ?)""",
            (JAN,),
        )
        connection.execute(
            """INSERT INTO pair_label_decisions (pair_label_id, prior_verdict, verdict,
                                                  note, decided_at)
               VALUES (1, 'unsure', 'different', NULL, ?)""",
            (MAR,),
        )
        # a post candidate created in February with a March decision
        connection.execute(
            """INSERT INTO post_match_candidates (candidate_key, relation_kind,
                    subject_post_id, target_post_id, score, score_version,
                    created_at, updated_at)
               VALUES (?, 'same_work', 1, 2, 0, 'test-v1', ?, ?)""",
            ("k" * 64, FEB, FEB),
        )
        connection.execute(
            """INSERT INTO post_candidate_decisions (post_candidate_id, prior_state,
                    decision, evidence_generation, note, decided_at)
               VALUES (1, 'pending', 'confirmed', 1, NULL, ?)""",
            (MAR,),
        )
        # a relationship created in January, decided in February
        connection.execute(
            """INSERT INTO relationships (relationship_key, subject_kind, subject_id,
                    relation_kind, target_kind, target_id, epistemic_status,
                    review_state, created_at, updated_at)
               VALUES (?, 'post', 1, 'same_work', 'post', 2, 'reviewed',
                       'confirmed', ?, ?)""",
            ("r" * 64, JAN, FEB),
        )
        connection.execute(
            """INSERT INTO relationship_review_decisions (relationship_id, prior_state,
                    decision, note, decided_at)
               VALUES (1, 'pending', 'confirmed', NULL, ?)""",
            (FEB,),
        )


def test_snapshot_before_and_after_the_reversal(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    with CatalogDatabase(catalog) as database:
        february = review_state_snapshot(database.connection, FEB)
        assert february["pair_labels"]["by_signal_verdict"] == {
            "same_artist_contrast": {"unsure": 1}
        }
        assert february["pair_labels"]["reversals_so_far"] == 0
        # candidate exists (created in February) but is pending
        assert february["candidates"]["post"] == {"by_state": {"pending": 1}, "created": 1}
        # relationship at its February decision
        assert february["relationships"]["by_state"] == {"confirmed": 1}

        march = review_state_snapshot(database.connection, MAR)
        assert march["pair_labels"]["by_signal_verdict"] == {
            "same_artist_contrast": {"different": 1}
        }
        assert march["pair_labels"]["reversals_so_far"] == 1
        assert march["candidates"]["post"] == {"by_state": {"confirmed": 1}, "created": 1}

        january = review_state_snapshot(database.connection, JAN)
        # the February candidate did not exist yet; the February relationship
        # decision is invisible, leaving the birth state (pending)
        assert january["candidates"]["post"]["created"] == 0
        assert january["relationships"]["by_state"] == {"pending": 1}


def test_mixed_precision_cutoff_orders_correctly(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    with CatalogDatabase(catalog) as database:
        snapshot = review_state_snapshot(database.connection, JAN_FRACTIONAL)
    # the fractional January instant still falls inside the same whole day;
    # the March reversal stays invisible and the January decision counts
    assert snapshot["pair_labels"]["by_signal_verdict"] == {"same_artist_contrast": {"unsure": 1}}


def test_change_report_windows_partition_history(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    with CatalogDatabase(catalog) as database:
        before = change_report(database.connection, "2026-01-01T00:00:00Z", FEB)
        after = change_report(database.connection, FEB, "2026-04-01T00:00:00Z")

    assert before["pair_labels"] == {
        "decisions": 1,
        "first_time": 1,
        "reversals": 0,
        "by_verdict": {"unsure": 1},
    }
    assert before["relationships"]["decisions"] == 1
    assert before["candidates"]["post"]["created"] == 1

    assert after["pair_labels"] == {
        "decisions": 1,
        "first_time": 0,
        "reversals": 1,
        "by_verdict": {"different": 1},
    }
    assert after["candidates"]["post"]["decisions"] == 1
    assert after["candidates"]["post"]["created"] == 0


def test_cutoff_validation() -> None:
    assert validate_cutoff("2026-02-15T12:00:00Z") == "2026-02-15T12:00:00Z"
    assert validate_cutoff(" 2026-02-15T12:00:00Z ") == "2026-02-15T12:00:00Z"
    for bad in ("not-a-date", "2026-13-01T00:00:00Z", "2026-01-01T00:00:00", ""):
        with pytest.raises(ValueError):
            validate_cutoff(bad)


def test_reports_never_write(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    with CatalogDatabase(catalog) as database:
        review_state_snapshot(database.connection, FEB)
        change_report(database.connection, JAN, MAR)
        total_changes = database.connection.execute(
            """SELECT (SELECT count(*) FROM pair_labels)
                     + (SELECT count(*) FROM pair_label_decisions)
                     + (SELECT count(*) FROM post_match_candidates)
                     + (SELECT count(*) FROM relationships)"""
        ).fetchone()[0]
    assert total_changes == 5


def test_cli_surface_round_trips(tmp_path: Path, capsys) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    import json as _json

    from media_catalog.cli import main

    main(["as-of", str(catalog), "--at", FEB, "--json"])
    snapshot = _json.loads(capsys.readouterr().out)
    assert snapshot["pair_labels"]["by_signal_verdict"] == {"same_artist_contrast": {"unsure": 1}}
    main(["as-of", str(catalog), "--from", FEB, "--to", "2026-04-01T00:00:00Z", "--json"])
    changes = _json.loads(capsys.readouterr().out)
    assert changes["pair_labels"]["reversals"] == 1
    with pytest.raises(SystemExit, match="ISO-8601"):
        main(["as-of", str(catalog), "--at", "garbage", "--json"])
    with pytest.raises(SystemExit, match="together"):
        main(["as-of", str(catalog), "--from", FEB, "--json"])
    capsys.readouterr()
