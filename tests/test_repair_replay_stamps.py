"""Replay-stamp repair tests (Bead data-processing-3qq).

A fact row is replay damage exactly when its timestamp equals a reprocess
run's started_at AND an identical-facts earlier twin exists.  The repair
deletes those rows (trigger surgery where the audit tier blocks deletes),
restores occurrence timestamps from their retained raw observations, and
recomputes current-projection fields from the surviving history.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

from media_catalog.database import CatalogDatabase

_SPEC = importlib.util.spec_from_file_location(
    "repair_replay_stamps",
    Path(__file__).parent.parent / "scripts" / "repair_replay_stamps.py",
)
repair = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(repair)

ORIG = "2026-10-05T19:08:28.765926Z"
REPLAY = "2026-10-08T04:33:19.655213Z"


def _damaged(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        connection.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name) "
            "VALUES ('danbooru', 'Danbooru')"
        )
        platform = int(
            connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
            ).fetchone()[0]
        )
        connection.execute(
            """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
               VALUES (?, '5001', ?, ?)""",
            (platform, ORIG, REPLAY),
        )
        post_id = int(
            connection.execute(
                "SELECT post_id FROM posts WHERE native_post_id = '5001'"
            ).fetchone()[0]
        )
        # The reprocess run whose wall-clock time was stamped as observation
        # time.
        connection.execute(
            """INSERT INTO remote_runs (platform_id, operation, target, adapter_version,
                   schema_version, request_budget, page_budget, record_budget,
                   time_budget_seconds, status, started_at, finished_at, origin_kind,
                   origin_reference)
               VALUES (?, 'fetch_post', '5001', 'v', 'v', 1, 1, 1, 60, 'complete',
                       ?, ?, 'reprocess', ?)""",
            (platform, REPLAY, REPLAY, "0" * 64),
        )
        # Original + replay duplicate metadata rows.
        for observed_at in (ORIG, REPLAY):
            connection.execute(
                """INSERT INTO post_metadata_observations (
                       post_id, score_total, favorite_count, observed_at, observation_digest)
                   VALUES (?, 11, 8, ?, ?)""",
                (post_id, observed_at, "a" * 64 if observed_at == ORIG else "b" * 64),
            )
        # Raw report kept the original time; the occurrence was stamped.
        connection.execute(
            "INSERT INTO raw_payloads (payload, sha256, byte_size, media_type) "
            "VALUES (x'7b7d', ?, 2, 'application/json')",
            ("c" * 64,),
        )
        payload = int(connection.execute("SELECT raw_payload_id FROM raw_payloads").fetchone()[0])
        connection.execute(
            """INSERT INTO raw_observations (platform_id, object_kind, native_id,
                   media_type, observed_at, adapter_version, schema_version, status,
                   raw_payload_id)
               VALUES (?, 'post', '5001', 'application/json', ?, 'v', 'v', 200, ?)""",
            (platform, ORIG, payload),
        )
        raw = int(
            connection.execute("SELECT raw_observation_id FROM raw_observations").fetchone()[0]
        )
        connection.execute(
            """INSERT INTO media_occurrences (post_id, source_key, media_index, media_type,
                   role, observed_at, raw_observation_id)
               VALUES (?, 'danbooru:5001:0', 0, 'image', 'original', ?, ?)""",
            (post_id, REPLAY, raw),
        )
        # Tag / post_tag with replay-stamped current fields and a replay
        # observation twin.
        connection.execute(
            "INSERT INTO tags (platform_id, provider_tag_id, name, category, "
            "normalization_version, created_at, last_observed_at) "
            "VALUES (?, 'artist_x', 'artist_x', 'artist', 'v1', ?, ?)",
            (platform, ORIG, REPLAY),
        )
        tag = int(connection.execute("SELECT tag_id FROM tags").fetchone()[0])
        connection.execute(
            "INSERT INTO post_tags (post_id, tag_id, first_seen_at, last_seen_at) "
            "VALUES (?, ?, ?, ?)",
            (post_id, tag, ORIG, REPLAY),
        )
        post_tag = int(connection.execute("SELECT post_tag_id FROM post_tags").fetchone()[0])
        for observed_at in (ORIG, REPLAY):
            connection.execute(
                """INSERT INTO post_tag_observations (
                       post_tag_id, observed_at, provider_spelling, observation_digest)
                   VALUES (?, ?, 'artist_x', ?)""",
                (post_tag, observed_at, "d" * 64 if observed_at == ORIG else "e" * 64),
            )
        # Account with replay-stamped snapshot twin.
        connection.execute(
            """INSERT INTO accounts (platform_id, native_account_id, first_seen_at, last_seen_at)
               VALUES (?, '77', ?, ?)""",
            (platform, ORIG, REPLAY),
        )
        account = int(connection.execute("SELECT account_id FROM accounts").fetchone()[0])
        for observed_at in (ORIG, REPLAY):
            connection.execute(
                """INSERT INTO account_snapshots (account_id, observed_at, snapshot_digest)
                   VALUES (?, ?, ?)""",
                (account, observed_at, "f" * 64),
            )
        connection.commit()


def test_replay_stamp_repair_dry_run_and_apply(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _damaged(catalog)
    plan = repair.plan_and_apply(catalog, apply=False)
    assert plan["applied"] is False
    assert plan["delete_history_rows"] == {
        "post_metadata_observations": 1,
        "account_snapshots": 1,
        "post_tag_observations": 1,
    }
    assert plan["occurrence_timestamps_from_raw"] == 1
    assert plan["current_fields_recomputable"] == {
        "posts.last_seen_at": 1,
        "tags.last_observed_at": 1,
        "post_tags.last_seen_at": 1,
        "accounts.last_seen_at": 1,
    }

    report = repair.plan_and_apply(catalog, apply=True)
    assert report["applied"] is True
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        replay = [
            row[0]
            for row in connection.execute(
                "SELECT started_at FROM remote_runs WHERE origin_kind = 'reprocess'"
            )
        ]
        marks = ",".join("?" * len(replay))
        for table, column in (
            ("post_metadata_observations", "observed_at"),
            ("account_snapshots", "observed_at"),
            ("post_tag_observations", "observed_at"),
            ("media_occurrences", "observed_at"),
            ("posts", "last_seen_at"),
            ("tags", "last_observed_at"),
            ("post_tags", "last_seen_at"),
            ("accounts", "last_seen_at"),
        ):
            assert (
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({marks})",
                    replay,
                ).fetchone()[0]
                == 0
            ), (table, column)
        # Originals survive; current fields point at them again.
        assert (
            connection.execute("SELECT COUNT(*) FROM post_metadata_observations").fetchone()[0] == 1
        )
        assert connection.execute("SELECT last_seen_at FROM posts").fetchone()[0] == ORIG
        assert connection.execute("SELECT observed_at FROM media_occurrences").fetchone()[0] == ORIG
        # Audit triggers on the touched history tables are back.
        for table in ("post_metadata_observations", "post_tag_observations"):
            triggers = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND tbl_name = ?",
                (table,),
            ).fetchone()[0]
            assert triggers == 2, table
        with pytest_raises(sqlite3.DatabaseError):
            connection.execute(
                "DELETE FROM post_metadata_observations WHERE observed_at = ?", (ORIG,)
            )


def pytest_raises(expected: type[BaseException]):
    class _ctx:
        def __enter__(self) -> None:
            return None

        def __exit__(self, exc_type, exc, tb) -> bool:
            assert exc_type is not None and issubclass(exc_type, expected), (
                "immutability trigger did not fire after repair"
            )
            return True

    return _ctx()
