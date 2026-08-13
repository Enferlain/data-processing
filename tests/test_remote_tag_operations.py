from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

import media_catalog.database as database_module
from media_catalog.adapters import (
    AdapterOperation,
    NormalizedItem,
    NormalizedPage,
    load_fixture_suite,
)
from media_catalog.adapters.e621 import E621, E621Adapter
from media_catalog.database import CatalogDatabase, SchemaVersionError, available_migrations
from media_catalog.records import RawRecord, RemoteRequestRecord, RemoteRunRecord
from media_catalog.remote_sync import (
    BudgetExhausted,
    BudgetTracker,
    MetadataSyncService,
    SyncLimits,
)
from media_catalog.writer import CatalogWriter

NOW = "2026-08-13T00:00:00Z"
FIXTURE = Path(__file__).parent / "fixtures" / "metadata_adapters" / "e621.json"
SUITE = load_fixture_suite(FIXTURE)


def _fixture_body(name: str) -> object:
    case = next(case for case in SUITE.cases if case.name == name)
    return json.loads(case.response.payload)


def _at_version(path: Path, version: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for number, _name, sql in available_migrations()[:version]:
            connection.executescript(sql)
            connection.execute(f"PRAGMA user_version = {number}")
        connection.commit()


def _seed_v9_remote_rows(path: Path) -> None:
    _at_version(path, 9)
    with sqlite3.connect(path) as connection:
        platform_id = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'e621'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO remote_runs (
                   remote_run_id, platform_id, operation, target, adapter_version,
                   schema_version, request_budget, page_budget, record_budget,
                   time_budget_seconds, started_at
               ) VALUES (101, ?, 'fetch_post', '5001', 'e621-native-v1', 'e621-json-v1',
                         2, 2, 2, 2, ?)""",
            (platform_id, NOW),
        )
        connection.execute(
            """INSERT INTO remote_checkpoints (
                   remote_checkpoint_id, remote_run_id, operation, target,
                   continuation_adapter, continuation_version, continuation_json,
                   committed_at
               ) VALUES (202, 101, 'fetch_post', '5001', 'e621', 'e621-keyset-v1',
                         '{"adapter":"e621","version":"e621-keyset-v1","value":{}}', ?)""",
            (NOW,),
        )
        connection.execute(
            """INSERT INTO remote_requests (
                   remote_request_id, remote_run_id, attempt_number, request_identity,
                   operation, target, status_code, outcome, request_started_at
               ) VALUES (303, 101, 1, 'e621:fetch_post:5001', 'fetch_post', '5001',
                         200, 'success', ?)""",
            (NOW,),
        )
        connection.commit()


@pytest.mark.parametrize(
    ("operation", "object_kind", "target"),
    [("fetch_tag", "tag", "fox"), ("fetch_tag_alias", "tag_alias", "old_fox")],
)
def test_fresh_schema_persists_tag_operations_and_raw_kinds(
    tmp_path: Path, operation: str, object_kind: str, target: str
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            run_id = writer.begin_remote_run(
                RemoteRunRecord(
                    "e621", operation, target, "e621-native-v1", "e621-json-v1", 1, 1, 1, 1, NOW
                )
            )
            request_id = writer.record_remote_request(
                RemoteRequestRecord(
                    run_id,
                    1,
                    f"e621:{operation}:{target}",
                    operation,
                    target,
                    "success",
                    NOW,
                    status_code=200,
                    object_kind=object_kind,
                    native_id=target,
                )
            )
            writer.store_raw(
                RawRecord(
                    b"{}",
                    "application/json",
                    object_kind,
                    target,
                    NOW,
                    platform="e621",
                    adapter_version="e621-native-v1",
                    schema_version="e621-json-v1",
                ),
                remote_run_id=run_id,
                remote_request_id=request_id,
            )

        row = database.connection.execute(
            "SELECT operation FROM remote_runs WHERE remote_run_id = ?", (run_id,)
        ).fetchone()
        assert row[0] == operation
        assert tuple(
            database.connection.execute(
                "SELECT operation, object_kind FROM remote_requests WHERE remote_request_id = ?",
                (request_id,),
            ).fetchone()
        ) == (operation, object_kind)
        assert (
            database.connection.execute(
                "SELECT object_kind FROM raw_observations WHERE remote_request_id = ?",
                (request_id,),
            ).fetchone()[0]
            == object_kind
        )
        assert database.doctor()["ok"] is True


@pytest.mark.parametrize(
    ("operation", "target", "fixture", "object_kind", "table"),
    [
        (AdapterOperation.FETCH_TAG, "fox", "tag_record", "tag", "tag_observations"),
        (
            AdapterOperation.FETCH_TAG_ALIAS,
            "old_fox",
            "active_alias",
            "tag_alias",
            "tag_alias_observations",
        ),
    ],
)
def test_tag_operations_sync_with_raw_kind_and_record_budget(
    tmp_path: Path,
    operation: AdapterOperation,
    target: str,
    fixture: str,
    object_kind: str,
    table: str,
) -> None:
    body = _fixture_body(fixture)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(body).encode(),
        )

    adapter = E621Adapter(
        E621,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = MetadataSyncService(
            database,
            adapter,
            minimum_interval_seconds=0.0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ).synchronize(
            operation,
            target,
            limits=SyncLimits(1, 1, 1, 10),
        )
        assert (result.status, result.outcome, result.record_count) == ("complete", "success", 1)
        assert (
            database.connection.execute(
                "SELECT object_kind FROM raw_observations ORDER BY raw_observation_id"
            ).fetchone()[0]
            == object_kind
        )
        assert database.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1


def test_v9_upgrade_preserves_remote_ids_and_foreign_keys(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    _seed_v9_remote_rows(path)

    with CatalogDatabase(path) as database:
        assert database.schema_version == database_module.current_schema_version()
        assert (
            database.connection.execute("SELECT remote_run_id FROM remote_runs").fetchone()[0]
            == 101
        )
        assert (
            database.connection.execute(
                "SELECT remote_checkpoint_id FROM remote_checkpoints"
            ).fetchone()[0]
            == 202
        )
        assert (
            database.connection.execute("SELECT remote_request_id FROM remote_requests").fetchone()[
                0
            ]
            == 303
        )
        assert database.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                """INSERT INTO remote_requests (
                       remote_run_id, attempt_number, request_identity, operation,
                       target, outcome, request_started_at
                   ) VALUES (999999, 1, 'e621:fetch_tag:fox', 'fetch_tag', 'fox',
                             'success', ?)""",
                (NOW,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            database.connection.execute(
                "UPDATE remote_runs SET origin_kind = 'library_expansion', "
                "origin_reference = ? WHERE remote_run_id = 101",
                ("a" * 64,),
            )
        assert database.doctor()["ok"] is True


def test_failed_remote_tag_migration_rolls_back_without_partial_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "broken.sqlite3"
    _seed_v9_remote_rows(path)
    migrations = available_migrations()
    broken = (
        *migrations[:9],
        (10, "0010_broken_remote_tag.sql", "CREATE TABLE partial_remote_tag(x); INVALID SQL"),
    )
    monkeypatch.setattr(database_module, "available_migrations", lambda: broken)

    with pytest.raises(SchemaVersionError, match="0010_broken_remote_tag"):
        CatalogDatabase(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'partial_remote_tag'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT sql FROM sqlite_master WHERE name = 'remote_runs'")
            .fetchone()[0]
            .find("fetch_tag")
            == -1
        )
        assert connection.execute("SELECT remote_run_id FROM remote_runs").fetchone()[0] == 101
        assert (
            connection.execute("SELECT remote_checkpoint_id FROM remote_checkpoints").fetchone()[0]
            == 202
        )
        assert (
            connection.execute("SELECT remote_request_id FROM remote_requests").fetchone()[0] == 303
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO remote_runs (
                       platform_id, operation, target, adapter_version, schema_version,
                       request_budget, page_budget, record_budget, time_budget_seconds,
                       started_at
                   ) VALUES (1, 'fetch_tag', 'fox', 'e621-native-v1', 'e621-json-v1',
                             1, 1, 1, 1, ?)""",
                (NOW,),
            )


@pytest.mark.parametrize("object_kind", ["tag", "tag_alias"])
def test_tag_page_record_budget_admits_one_top_level_record(object_kind: str) -> None:
    page = NormalizedPage(
        (
            NormalizedItem(object_kind, "1", {}),
            NormalizedItem("tag_observation", "1:observation", {}),
        )
    )
    budget = BudgetTracker(SyncLimits(2, 2, 1, 10), monotonic=lambda: 0.0)
    budget.commit_page(page.record_count)
    assert budget.records == 1
    with pytest.raises(BudgetExhausted, match="record"):
        budget.commit_page(page.record_count)
