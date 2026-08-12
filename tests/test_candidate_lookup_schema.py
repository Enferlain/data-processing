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


def _catalog_at_version(path: Path, version: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        for number, _name, sql in available_migrations()[:version]:
            connection.executescript(sql)
            connection.execute(f"PRAGMA user_version = {number}")
            connection.commit()


def test_v6_upgrade_preserves_ids_and_adds_lookup_tables(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    _catalog_at_version(path, 6)
    with sqlite3.connect(path) as connection:
        platform_id = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'x'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO posts (
                   post_id, platform_id, native_post_id, first_seen_at, last_seen_at
               ) VALUES (42, ?, 'seed', '2026-08-11T00:00:00Z', '2026-08-11T00:00:00Z')""",
            (platform_id,),
        )
        connection.commit()
    with CatalogDatabase(path) as database:
        assert database.schema_version == current_schema_version()
        assert database.connection.execute("SELECT post_id FROM posts").fetchone()[0] == 42
        assert (
            database.connection.execute("SELECT COUNT(*) FROM candidate_lookup_runs").fetchone()[0]
            == 0
        )
        assert database.doctor()["ok"] is True


def test_failed_lookup_migration_rolls_back_to_v6(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "broken.sqlite3"
    migrations = available_migrations()
    broken = (
        *migrations[:6],
        (
            7,
            "0007_broken_candidate_lookup.sql",
            "CREATE TABLE partial_lookup(value TEXT); INVALID SQL",
        ),
    )
    monkeypatch.setattr(database_module, "available_migrations", lambda: broken)
    with pytest.raises(SchemaVersionError, match="0007_broken_candidate_lookup"):
        CatalogDatabase(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'partial_lookup'"
            ).fetchone()[0]
            == 0
        )
        assert list(connection.execute("PRAGMA foreign_key_check")) == []


def test_lookup_schema_enforces_seed_and_immutable_limits(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        platform_id = database.connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                """INSERT INTO candidate_lookup_runs (
                       platform_id, strategy, strategy_version, adapter_version, schema_version,
                       seed_revision, plan_digest, query_kind, material_digest,
                       private_query_json, request_limit, page_limit, result_limit,
                       time_limit_seconds, started_at
                   ) VALUES (?, 'source_post_url', 'lookup-v1', 'adapter-v1', 'schema-v1',
                             'revision', ?, 'source_post_url', ?, '{}', 1, 1, 1, 1,
                             '2026-08-11T00:00:00Z')""",
                (platform_id, "a" * 64, "b" * 64),
            )
