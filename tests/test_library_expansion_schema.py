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
    AccountRecord,
    LibraryExpansionExecutionRecord,
    LibraryExpansionPlanRecord,
    LibraryExpansionPostRecord,
    LibraryExpansionProbeRecord,
    PostRecord,
    RemoteRunRecord,
)
from media_catalog.writer import CatalogWriter

NOW = "2026-08-12T20:00:00Z"


def _catalog_at_version(path: Path, version: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for number, _name, sql in available_migrations()[:version]:
            connection.executescript(sql)
            connection.execute(f"PRAGMA user_version = {number}")
        connection.commit()


def _seed(writer: CatalogWriter) -> tuple[int, int]:
    account_id = writer.upsert_account(AccountRecord("pixiv", "1001", NOW)).id
    post_id = writer.upsert_post(PostRecord("pixiv", "2001", NOW)).id
    return account_id, post_id


def _plan(account_id: int, *, digest: str = "a" * 64) -> LibraryExpansionPlanRecord:
    return LibraryExpansionPlanRecord(
        platform="pixiv",
        instance_host="",
        target_kind="account",
        target_account_id=account_id,
        target_attribution_id=None,
        seed_account_id=account_id,
        seed_post_id=None,
        seed_revision="seed-v1",
        authority_mode="explicit",
        authority_reference=None,
        selection_note="selected for this run",
        capability_key="pixiv-account-artworks",
        capability_version="library-expansion-v1",
        target_native_id="1001",
        target_revision="target-v1",
        adapter_version="pixiv-native-v1",
        schema_version="pixiv-v1",
        source_revision="source-v1",
        request_limit=2,
        page_limit=2,
        record_limit=20,
        time_limit_seconds=30,
        estimate_state="unknown",
        estimate_count=None,
        estimate_observed_at=None,
        estimate_source=None,
        exclusions_json="[]",
        plan_digest=digest,
        material_digest="b" * 64,
        created_at=NOW,
    )


def _remote_run(
    *, digest: str | None = "a" * 64, resumed_from: int | None = None
) -> RemoteRunRecord:
    return RemoteRunRecord(
        platform="pixiv",
        operation="list_account_posts",
        target="1001",
        adapter_version="pixiv-native-v1",
        schema_version="pixiv-v1",
        request_budget=2,
        page_budget=2,
        record_budget=20,
        time_budget_seconds=30,
        started_at=NOW,
        resumed_from_run_id=resumed_from,
        origin_kind="library_expansion" if digest is not None else None,
        origin_reference=digest,
    )


def test_fresh_schema_persists_immutable_library_provenance(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        account_id, post_id = _seed(writer)
        plan = _plan(account_id)
        plan_id = writer.record_library_expansion_plan(plan)
        assert writer.record_library_expansion_plan(plan) == plan_id

        probe_id = writer.record_library_expansion_probe(
            LibraryExpansionProbeRecord(
                plan_id,
                "pixiv-account-count",
                "library-expansion-v1",
                "pixiv-native-v1",
                "pixiv-v1",
                1,
                10,
                "unsupported",
                NOW,
                NOW,
            )
        )
        remote_run_id = writer.begin_remote_run(_remote_run())
        execution_id = writer.record_library_expansion_execution(
            LibraryExpansionExecutionRecord(plan_id, remote_run_id, "initial", NOW)
        )
        post_record = LibraryExpansionPostRecord(execution_id, post_id, NOW, details_required=True)
        expansion_post_id = writer.record_library_expansion_post(post_record)
        assert writer.record_library_expansion_post(post_record) == expansion_post_id

        with pytest.raises(sqlite3.IntegrityError, match="plans are immutable"):
            database.connection.execute("UPDATE library_expansion_plans SET request_limit = 3")
        with pytest.raises(sqlite3.IntegrityError, match="probes are immutable"):
            database.connection.execute(
                "UPDATE library_expansion_probes SET outcome = 'success' WHERE "
                "library_expansion_probe_id = ?",
                (probe_id,),
            )
        with pytest.raises(ValueError, match="different provenance"):
            writer.record_library_expansion_post(
                LibraryExpansionPostRecord(execution_id, post_id, NOW)
            )
        assert database.doctor()["ok"] is True


def test_schema_rejects_mismatched_targets_origins_and_lineage(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        account_id, _post_id = _seed(writer)
        plan_id = writer.record_library_expansion_plan(_plan(account_id))

        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                """INSERT INTO library_expansion_plans (
                       platform_id, target_kind, target_account_id, seed_account_id,
                       seed_revision, authority_mode, capability_key, capability_version,
                       target_native_id, target_revision, adapter_version, schema_version,
                       source_revision, request_limit, page_limit, record_limit,
                       time_limit_seconds, estimate_state, exclusions_json, plan_digest,
                       material_digest, created_at
                   ) SELECT platform_id, 'attribution', ?, ?, 'seed', 'explicit', 'cap', 'v1',
                            '1001', 'target', 'adapter', 'schema', 'source', 1, 1, 1, 1,
                            'unknown', '[]', ?, ?, ?
                       FROM platforms WHERE platform_key = 'pixiv'""",
                (account_id, account_id, "c" * 64, "d" * 64, NOW),
            )

        wrong_run_id = writer.begin_remote_run(_remote_run(digest="c" * 64))
        with pytest.raises(sqlite3.IntegrityError, match="origin does not match"):
            writer.record_library_expansion_execution(
                LibraryExpansionExecutionRecord(plan_id, wrong_run_id, "initial", NOW)
            )

        first_run_id = writer.begin_remote_run(_remote_run())
        first_execution_id = writer.record_library_expansion_execution(
            LibraryExpansionExecutionRecord(plan_id, first_run_id, "initial", NOW)
        )
        unrelated_resume_id = writer.begin_remote_run(_remote_run())
        with pytest.raises(sqlite3.IntegrityError, match="lineage is incompatible"):
            writer.record_library_expansion_execution(
                LibraryExpansionExecutionRecord(
                    plan_id,
                    unrelated_resume_id,
                    "resume",
                    NOW,
                    predecessor_execution_id=first_execution_id,
                )
            )


def test_v7_upgrade_preserves_catalog_and_remote_run_ids(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    _catalog_at_version(path, 7)
    with sqlite3.connect(path) as connection:
        platform_id = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO accounts (
                   account_id, platform_id, native_account_id, first_seen_at, last_seen_at
               ) VALUES (41, ?, '1001', ?, ?)""",
            (platform_id, NOW, NOW),
        )
        connection.execute(
            """INSERT INTO remote_runs (
                   remote_run_id, platform_id, operation, target, adapter_version,
                   schema_version, request_budget, page_budget, record_budget,
                   time_budget_seconds, started_at
               ) VALUES (55, ?, 'fetch_account', '1001', 'adapter-v1', 'schema-v1',
                         1, 1, 1, 1, ?)""",
            (platform_id, NOW),
        )
        connection.commit()

    with CatalogDatabase(path) as database:
        assert database.schema_version == current_schema_version() == 10
        row = database.connection.execute(
            "SELECT remote_run_id, origin_kind, origin_reference FROM remote_runs"
        ).fetchone()
        assert tuple(row) == (55, None, None)
        assert database.connection.execute("SELECT account_id FROM accounts").fetchone()[0] == 41
        assert database.doctor()["ok"] is True


def test_failed_library_migration_rolls_back_to_v7(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "broken.sqlite3"
    migrations = available_migrations()
    broken = (
        *migrations[:7],
        (8, "0008_broken_library.sql", "CREATE TABLE partial_library(x); INVALID SQL"),
    )
    monkeypatch.setattr(database_module, "available_migrations", lambda: broken)
    with pytest.raises(SchemaVersionError, match="0008_broken_library"):
        CatalogDatabase(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'partial_library'"
            ).fetchone()[0]
            == 0
        )
        assert list(connection.execute("PRAGMA foreign_key_check")) == []
