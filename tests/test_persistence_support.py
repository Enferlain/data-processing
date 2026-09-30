from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import media_catalog.persistence
from media_catalog.database import CatalogDatabase
from media_catalog.persistence import support
from media_catalog.records import AccountRecord, AdoptionRunRecord, ManagedRootRecord
from media_catalog.writer import CatalogWriter


def test_support_helpers_share_the_caller_connection(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        connection = support.caller_connection(database)
        assert connection is database.connection

        with pytest.raises(RuntimeError, match="force rollback"), database.transaction():
            connection.execute("CREATE TABLE probe_rollback (value INTEGER NOT NULL)")
            connection.execute("INSERT INTO probe_rollback (value) VALUES (1)")
            raise RuntimeError("force rollback")

        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'probe_rollback'"
            ).fetchone()[0]
            == 0
        )


def test_inserted_id_contract(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        connection = support.caller_connection(database)
        fresh_cursor = connection.cursor()
        with pytest.raises(sqlite3.DatabaseError, match="did not produce a row identifier"):
            support.inserted_id(fresh_cursor)

        with database.transaction():
            connection.execute("CREATE TABLE probe_ids (id INTEGER PRIMARY KEY, value TEXT)")
            insert_cursor = connection.execute("INSERT INTO probe_ids (value) VALUES ('a')")
            assert support.inserted_id(insert_cursor) == 1


def test_write_result_is_one_shared_type() -> None:
    from media_catalog import writer

    assert writer.WriteResult is support.WriteResult
    assert writer.WriteResult(id=1, outcome="inserted") == support.WriteResult(
        id=1, outcome="inserted"
    )


def test_persistence_package_never_commits_or_opens_connections() -> None:
    package_dir = Path(media_catalog.persistence.__file__).parent
    sources = list(package_dir.glob("*.py"))
    assert sources
    for source in sources:
        text = source.read_text()
        assert ".commit(" not in text, source.name
        assert ".executescript(" not in text, source.name
        assert "sqlite3.connect(" not in text, source.name
        assert "BEGIN" not in text, source.name


def test_delegated_storage_writes_share_the_caller_transaction(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)

        with pytest.raises(RuntimeError, match="force rollback"), database.transaction():
            writer.upsert_account(
                AccountRecord(
                    platform="pixiv",
                    native_id="123",
                    observed_at="2026-08-16T00:00:00Z",
                )
            )
            root_id = writer.register_managed_root(
                ManagedRootRecord(
                    root_kind="managed",
                    root_identity="dev:ino",
                    display_label="managed",
                )
            )
            writer.begin_adoption_run(
                AdoptionRunRecord(
                    managed_root_id=root_id,
                    managed_root_identity="dev:ino",
                    algorithm_version="adopt-v1",
                    started_at="2026-08-16T00:00:00Z",
                )
            )
            raise RuntimeError("force rollback")

        assert database.connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
        assert database.connection.execute("SELECT COUNT(*) FROM adoption_runs").fetchone()[0] == 0
