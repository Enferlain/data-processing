from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import media_catalog.database as database_module
from media_catalog.database import (
    CatalogDatabase,
    SchemaVersionError,
    available_migrations,
    current_schema_version,
)
from media_catalog.records import (
    AcquisitionAttemptRecord,
    AcquisitionLimits,
    AcquisitionPartialRecord,
    AcquisitionPlanItemRecord,
    AcquisitionPlanRecord,
    AcquisitionQuarantineRecord,
    AcquisitionRunItemRecord,
    AcquisitionRunRecord,
    AcquisitionVerificationRecord,
)
from media_catalog.writer import CatalogWriter

NOW = "2026-08-10T12:00:00Z"


def _v5_catalog(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for version, _name, sql in available_migrations()[:5]:
            connection.executescript(sql)
            connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()


def _seed_occurrence(connection: sqlite3.Connection) -> tuple[int, int, int, int]:
    platform_id = int(
        connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
        ).fetchone()[0]
    )
    connection.execute(
        """INSERT INTO posts (
               post_id, platform_id, native_post_id, first_seen_at, last_seen_at
           ) VALUES (41, ?, '99', ?, ?)""",
        (platform_id, NOW, NOW),
    )
    connection.execute(
        """INSERT INTO media_occurrences (
               media_occurrence_id, post_id, source_key, media_index, media_type,
               remote_url, observed_at
           ) VALUES (42, 41, '99:p0', 0, 'image', 'https://i.pximg.net/a.jpg', ?)""",
        (NOW,),
    )
    connection.execute(
        """INSERT INTO assets (
               asset_id, verified_sha256, storage_kind, verification_method
           ) VALUES (43, ?, 'managed', 'calculated')""",
        ("a" * 64,),
    )
    connection.execute(
        """INSERT INTO managed_roots (
               managed_root_id, root_kind, root_identity, display_label, created_at
           ) VALUES (44, 'managed', 'dev:ino', 'managed', ?)""",
        (NOW,),
    )
    return platform_id, 41, 42, 44


def _insert_plan(connection: sqlite3.Connection) -> tuple[int, int]:
    plan_id = int(
        connection.execute(
            """INSERT INTO media_acquisition_plans (
                   plan_version, selection_digest, requested_count, eligible_count,
                   satisfied_count, excluded_count, created_at
               ) VALUES ('plan-v1', ?, 1, 1, 0, 0, ?)""",
            ("b" * 64, NOW),
        ).lastrowid
    )
    item_id = int(
        connection.execute(
            """INSERT INTO media_acquisition_plan_items (
                   acquisition_plan_id, item_key, media_occurrence_id, variant_key,
                   material_digest, request_policy_key, request_policy_version,
                   eligibility, created_at
               ) VALUES (?, 'item-1', 42, 'primary', ?, 'pixiv-media', 'v1',
                         'eligible', ?)""",
            (plan_id, "c" * 64, NOW),
        ).lastrowid
    )
    return plan_id, item_id


def test_fresh_schema_has_constrained_acquisition_tables(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        tables = {
            row[0]
            for row in database.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "media_acquisition_plans",
            "media_acquisition_plan_items",
            "media_acquisition_runs",
            "media_acquisition_run_items",
            "media_acquisition_attempts",
            "media_acquisition_partials",
            "media_acquisition_verifications",
            "media_acquisition_quarantine",
        } <= tables
        _seed_occurrence(database.connection)
        plan_id, item_id = _insert_plan(database.connection)
        run_id = int(
            database.connection.execute(
                """INSERT INTO media_acquisition_runs (
                       acquisition_plan_id, managed_root_id, max_items, max_item_bytes,
                       max_total_bytes, max_attempts_per_item, max_seconds, max_redirects,
                       max_quarantine_bytes, concurrency, planned_count, started_at
                   ) VALUES (?, 44, 1, 1000, 1000, 2, 30, 3, 1000, 1, 1, ?)""",
                (plan_id, NOW),
            ).lastrowid
        )
        run_item_id = int(
            database.connection.execute(
                """INSERT INTO media_acquisition_run_items (
                       acquisition_run_id, acquisition_plan_item_id, created_at, updated_at
                   ) VALUES (?, ?, ?, ?)""",
                (run_id, item_id, NOW, NOW),
            ).lastrowid
        )
        database.connection.execute(
            """INSERT INTO media_acquisition_attempts (
                   acquisition_run_item_id, attempt_number, state, request_identity,
                   request_policy_key, request_policy_version, started_at
               ) VALUES (?, 1, 'running', ?, 'pixiv-media', 'v1', ?)""",
            (run_item_id, "d" * 64, NOW),
        )

        with pytest.raises(sqlite3.IntegrityError, match="plans are immutable"):
            database.connection.execute(
                "UPDATE media_acquisition_plans SET requested_count = 2 "
                "WHERE acquisition_plan_id = ?",
                (plan_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="inputs are immutable"):
            database.connection.execute(
                "UPDATE media_acquisition_runs SET max_items = 2 WHERE acquisition_run_id = ?",
                (run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                """INSERT INTO media_acquisition_partials (
                       acquisition_run_item_id, managed_root_id, managed_root_identity,
                       staging_device, staging_inode, staging_name, request_identity,
                       strong_etag, byte_count, prefix_sha256, prefix_md5, state,
                       created_at, updated_at
                   ) VALUES (?, 44, '44:45', 44, 45, '../escape', ?, 'W/\"weak\"',
                             0, ?, ?, 'active', ?, ?)""",
                (run_item_id, "d" * 64, "e" * 64, "f" * 32, NOW, NOW),
            )
        assert database.doctor()["ok"] is True


def test_v5_upgrade_preserves_catalog_ids_and_adds_acquisition_schema(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    _v5_catalog(path)
    with sqlite3.connect(path) as connection:
        _seed_occurrence(connection)
        connection.commit()

    with CatalogDatabase(path) as database:
        assert database.schema_version == current_schema_version() == 6
        assert database.connection.execute("SELECT post_id FROM posts").fetchone()[0] == 41
        assert (
            database.connection.execute(
                "SELECT media_occurrence_id FROM media_occurrences"
            ).fetchone()[0]
            == 42
        )
        assert database.connection.execute("SELECT asset_id FROM assets").fetchone()[0] == 43
        assert (
            database.connection.execute("SELECT managed_root_id FROM managed_roots").fetchone()[0]
            == 44
        )
        assert database.doctor()["ok"] is True


def test_acquisition_constraints_enforce_foreign_keys_and_active_partial_uniqueness(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        _seed_occurrence(database.connection)
        plan_id, item_id = _insert_plan(database.connection)
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                """INSERT INTO media_acquisition_plan_items (
                       acquisition_plan_id, item_key, media_occurrence_id, variant_key,
                       material_digest, request_policy_key, request_policy_version,
                       eligibility, created_at
                   ) VALUES (?, 'missing', 9999, 'primary', ?, 'pixiv-media', 'v1',
                             'eligible', ?)""",
                (plan_id, "c" * 64, NOW),
            )
        run_id = int(
            database.connection.execute(
                """INSERT INTO media_acquisition_runs (
                       acquisition_plan_id, managed_root_id, max_items, max_item_bytes,
                       max_total_bytes, max_attempts_per_item, max_seconds, max_redirects,
                       max_quarantine_bytes, concurrency, planned_count, started_at
                   ) VALUES (?, 44, 1, 1000, 1000, 1, 30, 1, 0, 1, 1, ?)""",
                (plan_id, NOW),
            ).lastrowid
        )
        run_item_id = int(
            database.connection.execute(
                """INSERT INTO media_acquisition_run_items (
                       acquisition_run_id, acquisition_plan_item_id, created_at, updated_at
                   ) VALUES (?, ?, ?, ?)""",
                (run_id, item_id, NOW, NOW),
            ).lastrowid
        )
        partial_values = (
            run_item_id,
            "44:45",
            44,
            45,
            "d" * 64,
            "e" * 64,
            "f" * 32,
            NOW,
            NOW,
        )
        database.connection.execute(
            """INSERT INTO media_acquisition_partials (
                   acquisition_run_item_id, managed_root_id, managed_root_identity,
                   staging_device, staging_inode, staging_name, request_identity,
                   strong_etag, byte_count, prefix_sha256, prefix_md5, state,
                   created_at, updated_at
               ) VALUES (?, 44, ?, ?, ?, 'partial-one', ?, '\"strong\"', 0, ?, ?,
                         'active', ?, ?)""",
            partial_values,
        )
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                """INSERT INTO media_acquisition_partials (
                       acquisition_run_item_id, managed_root_id, managed_root_identity,
                       staging_device, staging_inode, staging_name, request_identity,
                       strong_etag, byte_count, prefix_sha256, prefix_md5, state,
                       created_at, updated_at
                   ) VALUES (?, 44, ?, ?, ?, 'partial-two', ?, '\"strong\"', 0, ?, ?,
                             'active', ?, ?)""",
                partial_values,
            )


def test_failed_acquisition_migration_rolls_back_to_v5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "broken.sqlite3"
    migrations = available_migrations()
    broken = (
        *migrations[:-1],
        (
            6,
            "0006_broken_remote_media_acquisition.sql",
            "CREATE TABLE media_acquisition_partial_schema(value TEXT); INVALID SQL",
        ),
    )
    monkeypatch.setattr(database_module, "available_migrations", lambda: broken)

    with pytest.raises(SchemaVersionError, match="0006_broken_remote_media_acquisition"):
        CatalogDatabase(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE name = 'media_acquisition_partial_schema'"
            ).fetchone()[0]
            == 0
        )
        assert list(connection.execute("PRAGMA foreign_key_check")) == []


def test_acquisition_writer_advances_state_and_keeps_terminal_evidence_idempotent(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            _seed_occurrence(database.connection)
            plan_id = writer.create_acquisition_plan(
                AcquisitionPlanRecord("plan-v1", "b" * 64, 1, 1, 0, 0, NOW)
            )
            plan_item = AcquisitionPlanItemRecord(
                plan_id,
                "item-1",
                42,
                "primary",
                "c" * 64,
                "pixiv-media",
                "pixiv-media-v1",
                "eligible",
                NOW,
                declared_md5="1" * 32,
            )
            plan_item_id = writer.add_acquisition_plan_item(plan_item)
            assert writer.add_acquisition_plan_item(plan_item) == plan_item_id
            run_id = writer.begin_acquisition_run(
                AcquisitionRunRecord(
                    plan_id,
                    44,
                    AcquisitionLimits(1, 1000, 1000, 2, 30, 3, 1000),
                    1,
                    NOW,
                )
            )
            run_item_id = writer.record_acquisition_run_item(
                AcquisitionRunItemRecord(run_id, plan_item_id, "pending", NOW, NOW)
            )
            writer.record_acquisition_run_item(
                AcquisitionRunItemRecord(run_id, plan_item_id, "running", NOW, NOW)
            )
            running_attempt = AcquisitionAttemptRecord(
                run_item_id,
                1,
                "running",
                "d" * 64,
                "pixiv-media",
                "pixiv-media-v1",
                NOW,
            )
            attempt_id = writer.record_acquisition_attempt(running_attempt)
            partial_id = writer.save_acquisition_partial(
                AcquisitionPartialRecord(
                    run_item_id,
                    44,
                    "partial-one",
                    "d" * 64,
                    10,
                    "e" * 64,
                    "f" * 32,
                    "active",
                    NOW,
                    NOW,
                    "44:45",
                    44,
                    45,
                    '"strong"',
                )
            )
            writer.save_acquisition_partial(
                AcquisitionPartialRecord(
                    run_item_id,
                    44,
                    "partial-one",
                    "d" * 64,
                    10,
                    "e" * 64,
                    "f" * 32,
                    "consumed",
                    NOW,
                    NOW,
                    "44:45",
                    44,
                    45,
                    '"strong"',
                    partial_id,
                )
            )
            terminal_attempt = AcquisitionAttemptRecord(
                run_item_id,
                1,
                "complete",
                "d" * 64,
                "pixiv-media",
                "pixiv-media-v1",
                NOW,
                outcome="downloaded",
                status_code=200,
                received_bytes=10,
                response_size=10,
                finished_at=NOW,
            )
            assert writer.record_acquisition_attempt(terminal_attempt) == attempt_id
            assert writer.record_acquisition_attempt(terminal_attempt) == attempt_id
            completed_item = AcquisitionRunItemRecord(
                run_id,
                plan_item_id,
                "complete",
                NOW,
                NOW,
                outcome="downloaded",
                attempt_count=1,
                received_bytes=10,
                asset_id=43,
                sha256="a" * 64,
            )
            assert writer.record_acquisition_run_item(completed_item) == run_item_id
            assert writer.record_acquisition_run_item(completed_item) == run_item_id
            verification = AcquisitionVerificationRecord(
                run_item_id, "md5", "1" * 32, "2" * 32, "mismatched", NOW
            )
            verification_id = writer.record_acquisition_verification(verification)
            assert writer.record_acquisition_verification(verification) == verification_id
            quarantine = AcquisitionQuarantineRecord(
                run_item_id,
                44,
                "quarantine-one",
                "hash_mismatch",
                10,
                NOW,
                acquisition_attempt_id=attempt_id,
                sha256="a" * 64,
            )
            quarantine_id = writer.record_acquisition_quarantine(quarantine)
            assert writer.record_acquisition_quarantine(quarantine) == quarantine_id
            writer.finish_acquisition_run(
                run_id,
                status="complete",
                outcome="success",
                completed_count=1,
                failed_count=0,
                deferred_count=0,
                received_bytes=10,
                quarantined_bytes=10,
                finished_at=NOW,
            )
            writer.finish_acquisition_run(
                run_id,
                status="complete",
                outcome="success",
                completed_count=1,
                failed_count=0,
                deferred_count=0,
                received_bytes=10,
                quarantined_bytes=10,
                finished_at=NOW,
            )

        assert database.connection.execute(
            "SELECT state FROM media_acquisition_run_items"
        ).fetchone()[0] == "complete"
        assert database.connection.execute(
            "SELECT state FROM media_acquisition_attempts"
        ).fetchone()[0] == "complete"
        assert database.doctor()["ok"] is True


def test_acquisition_records_reject_unsafe_or_inconsistent_values() -> None:
    with pytest.raises(ValueError, match="counts"):
        AcquisitionPlanRecord("plan-v1", "a" * 64, 2, 1, 0, 0, NOW)
    with pytest.raises(ValueError, match="opaque path leaf"):
        AcquisitionPartialRecord(
            1,
            1,
            "../partial",
            "b" * 64,
            0,
            "c" * 64,
            "d" * 32,
            "active",
            NOW,
            NOW,
            "1:2",
            1,
            2,
        )
    with pytest.raises(ValueError, match="terminal acquisition attempt"):
        AcquisitionAttemptRecord(
            1,
            1,
            "failed",
            "b" * 64,
            "pixiv-media",
            "pixiv-media-v1",
            NOW,
            outcome="timeout",
        )
