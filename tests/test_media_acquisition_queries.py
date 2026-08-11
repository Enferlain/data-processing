from __future__ import annotations

import sqlite3
from pathlib import Path

from media_catalog.acquisition import (
    AcquisitionQueryService,
    get_acquisition_plan,
    get_acquisition_run,
    list_acquisition_plans,
    list_acquisition_runs,
    list_retryable_acquisition_items,
)
from media_catalog.database import CatalogDatabase

NOW = "2026-08-10T13:00:00Z"


def _seed_query_run(connection: sqlite3.Connection) -> tuple[int, int]:
    platform_id = int(
        connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
        ).fetchone()[0]
    )
    connection.execute(
        """INSERT INTO posts (
               post_id, platform_id, native_post_id, first_seen_at, last_seen_at
           ) VALUES (1, ?, '99', ?, ?)""",
        (platform_id, NOW, NOW),
    )
    connection.execute(
        """INSERT INTO media_occurrences (
               media_occurrence_id, post_id, source_key, media_index, media_type,
               remote_url, observed_at
           ) VALUES (2, 1, '99:p0', 0, 'image',
                     'https://i.pximg.net/private-original.jpg?token=SECRET', ?)""",
        (NOW,),
    )
    connection.execute(
        """INSERT INTO managed_roots (
               managed_root_id, root_kind, root_identity, display_label, private_path, created_at
           ) VALUES (3, 'managed', 'dev:ino', 'managed', '/private/media', ?)""",
        (NOW,),
    )
    plan_id = int(
        connection.execute(
            """INSERT INTO media_acquisition_plans (
                   plan_version, selection_digest, requested_count, eligible_count,
                   satisfied_count, excluded_count, created_at
               ) VALUES ('plan-v1', ?, 1, 1, 0, 0, ?)""",
            ("a" * 64, NOW),
        ).lastrowid
    )
    plan_item_id = int(
        connection.execute(
            """INSERT INTO media_acquisition_plan_items (
                   acquisition_plan_id, item_key, media_occurrence_id, variant_key,
                   material_digest, request_policy_key, request_policy_version,
                   eligibility, created_at
               ) VALUES (?, 'item-1', 2, 'primary', ?, 'pixiv-media',
                         'pixiv-media-v1', 'eligible', ?)""",
            (plan_id, "b" * 64, NOW),
        ).lastrowid
    )
    run_id = int(
        connection.execute(
            """INSERT INTO media_acquisition_runs (
                   acquisition_plan_id, managed_root_id, status, termination_outcome,
                   max_items, max_item_bytes, max_total_bytes, max_attempts_per_item,
                   max_seconds, max_redirects, max_quarantine_bytes, concurrency,
                   planned_count, failed_count, received_bytes, quarantined_bytes,
                   started_at, finished_at
               ) VALUES (?, 3, 'partial', 'partial', 1, 1000, 1000, 2, 30, 3,
                         1000, 1, 1, 1, 10, 10, ?, ?)""",
            (plan_id, NOW, NOW),
        ).lastrowid
    )
    run_item_id = int(
        connection.execute(
            """INSERT INTO media_acquisition_run_items (
                   acquisition_run_id, acquisition_plan_item_id, state, outcome, retryable,
                   attempt_count, received_bytes, diagnostic, created_at, updated_at
               ) VALUES (?, ?, 'failed', 'timeout', 1, 1, 10, 'bounded failure', ?, ?)""",
            (run_id, plan_item_id, NOW, NOW),
        ).lastrowid
    )
    attempt_id = int(
        connection.execute(
            """INSERT INTO media_acquisition_attempts (
                   acquisition_run_item_id, attempt_number, state, outcome, retryable,
                   request_identity, request_policy_key, request_policy_version,
                   response_etag, received_bytes, diagnostic, started_at, finished_at
               ) VALUES (?, 1, 'failed', 'timeout', 1, ?, 'pixiv-media',
                         'pixiv-media-v1', '\"PRIVATE-ETAG\"', 10, 'timed out', ?, ?)""",
            (run_item_id, "c" * 64, NOW, NOW),
        ).lastrowid
    )
    connection.execute(
        """INSERT INTO media_acquisition_partials (
               acquisition_run_item_id, managed_root_id, managed_root_identity,
               staging_device, staging_inode, staging_name, request_identity, strong_etag,
               byte_count, prefix_sha256, prefix_md5, state, created_at, updated_at
           ) VALUES (?, 3, 'dev:ino', 42, 84, 'PRIVATE-partial-name', ?,
                     '\"PRIVATE-ETAG\"', 10, ?, ?, 'active', ?, ?)""",
        (run_item_id, "c" * 64, "d" * 64, "e" * 32, NOW, NOW),
    )
    connection.execute(
        """INSERT INTO media_acquisition_verifications (
               acquisition_run_item_id, claim_kind, declared_value, verified_value,
               comparison_result, created_at
           ) VALUES (?, 'md5', ?, ?, 'mismatched', ?)""",
        (run_item_id, "f" * 32, "0" * 32, NOW),
    )
    connection.execute(
        """INSERT INTO media_acquisition_quarantine (
               acquisition_run_item_id, acquisition_attempt_id, managed_root_id,
               quarantine_name, reason, byte_size, sha256, state, created_at
           ) VALUES (?, ?, 3, 'PRIVATE-quarantine-name', 'hash_mismatch', 10, ?,
                     'retained', ?)""",
        (run_item_id, attempt_id, "1" * 64, NOW),
    )
    return plan_id, run_id


def test_acquisition_queries_are_stable_and_redact_private_storage_and_urls(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        with database.transaction():
            plan_id, run_id = _seed_query_run(database.connection)
        service = AcquisitionQueryService(database)
        assert service.plans()[0]["acquisition_plan_id"] == plan_id
        plan = service.plan(plan_id)
        run = service.run(run_id)
        assert plan is not None and run is not None
        assert plan["items"][0]["platform"] == "pixiv"
        assert run["items"][0]["attempts"][0]["request_identity"] == "c" * 64
        assert run["items"][0]["partials"][0]["byte_count"] == 10
        assert run["items"][0]["quarantine"][0]["reason"] == "hash_mismatch"
        assert service.retryable_items(acquisition_run_id=run_id)[0]["outcome"] == "timeout"

        public = {"plan": plan, "run": run}
        rendered = str(public)
        assert "private-original" not in rendered
        assert "token=SECRET" not in rendered
        assert "/private/media" not in rendered
        assert "PRIVATE-partial-name" not in rendered
        assert "PRIVATE-quarantine-name" not in rendered
        assert "PRIVATE-ETAG" not in rendered
        assert "staging_name" not in rendered
        assert "quarantine_name" not in rendered
        assert "response_etag" not in rendered


def test_path_queries_are_read_only_and_retry_filtering_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        plan_id, run_id = _seed_query_run(database.connection)
    before = path.read_bytes(), tuple(sorted(item.name for item in tmp_path.iterdir()))

    assert list_acquisition_plans(path)[0]["acquisition_plan_id"] == plan_id
    assert get_acquisition_plan(path, plan_id) is not None
    assert list_acquisition_runs(path, status="partial")[0]["acquisition_run_id"] == run_id
    assert get_acquisition_run(path, run_id) is not None
    retryable = list_retryable_acquisition_items(path, acquisition_run_id=run_id)
    assert [row["acquisition_run_item_id"] for row in retryable] == [1]

    after = path.read_bytes(), tuple(sorted(item.name for item in tmp_path.iterdir()))
    assert after == before
