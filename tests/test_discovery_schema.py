from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase, SchemaVersionError


def test_foundation_catalog_upgrades_without_rewriting_existing_data(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    initial = resources.files("media_catalog.migrations").joinpath("0001_initial.sql").read_text()
    with sqlite3.connect(path) as connection:
        connection.executescript(initial)
        connection.execute("PRAGMA user_version = 1")
        platform_id = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'x'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO posts
               (platform_id, native_post_id, first_seen_at, last_seen_at)
               VALUES (?, 'kept', 'now', 'now')""",
            (platform_id,),
        )
    with CatalogDatabase(path) as database:
        assert database.schema_version == 2
        assert (
            database.connection.execute("SELECT native_post_id FROM posts").fetchone()[0] == "kept"
        )
        assert database.doctor()["ok"] is True


def test_migration_failure_rolls_back_and_keeps_prior_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import media_catalog.database as database_module

    path = tmp_path / "broken.sqlite3"
    migrations = database_module.available_migrations()
    broken = (*migrations[:-1], (2, "0002_broken.sql", "CREATE TABLE partial(x); INVALID"))
    monkeypatch.setattr(database_module, "available_migrations", lambda: broken)
    with pytest.raises(SchemaVersionError, match="0002_broken"):
        CatalogDatabase(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'partial'"
            ).fetchone()[0]
            == 0
        )


def test_discovery_constraints_enforce_instances_kinds_endpoints_and_foreign_keys(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        connection = database.connection
        platform = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO external_links
               (canonical_url, canonicalization_version, resolution_state)
               VALUES ('https://a.example/posts/1', 'url-canonicalizer-v1', 'recognized')"""
        )
        link_id = connection.execute("SELECT external_link_id FROM external_links").fetchone()[0]
        for host in ("a.example", "b.example"):
            connection.execute(
                """INSERT INTO platform_references
                   (external_link_id, platform_id, instance_host, object_kind,
                    native_identifier, canonical_target_url, recognizer_name, recognizer_version)
                   VALUES (?, ?, ?, 'post', '1', ?, 'fixture', 'fixture-v1')""",
                (link_id, platform, host, f"https://{host}/posts/1"),
            )
        assert connection.execute("SELECT COUNT(*) FROM platform_references").fetchone()[0] == 2
        x_id = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'x'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO accounts
               (platform_id, native_account_id, first_seen_at, last_seen_at)
               VALUES (?, 'subject', 'now', 'now')""",
            (x_id,),
        )
        account_id = connection.execute("SELECT account_id FROM accounts").fetchone()[0]
        post_reference = connection.execute(
            "SELECT platform_reference_id FROM platform_references LIMIT 1"
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="must be an account"):
            connection.execute(
                """INSERT INTO account_match_candidates
                   (candidate_key, subject_account_id, target_reference_id, relation_kind,
                    score_version, created_at, updated_at)
                   VALUES (?, ?, ?, 'same_identity', 'fixture-v1', 'now', 'now')""",
                ("a" * 64, account_id, post_reference),
            )
        account_link = connection.execute(
            """INSERT INTO external_links
               (canonical_url, canonicalization_version, resolution_state)
               VALUES ('https://pixiv.net/users/1', 'url-canonicalizer-v1', 'recognized')"""
        ).lastrowid
        pixiv = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
        ).fetchone()[0]
        account_reference = connection.execute(
            """INSERT INTO platform_references
               (external_link_id, platform_id, object_kind, native_identifier,
                canonical_target_url, recognizer_name, recognizer_version)
               VALUES (?, ?, 'account', '1', 'https://www.pixiv.net/users/1',
                       'pixiv-user', 'fixture-v1')""",
            (account_link, pixiv),
        ).lastrowid
        candidate_id = connection.execute(
            """INSERT INTO account_match_candidates
               (candidate_key, subject_account_id, target_reference_id, relation_kind,
                score_version, created_at, updated_at)
               VALUES (?, ?, ?, 'same_identity', 'fixture-v1', 'now', 'now')""",
            ("b" * 64, account_id, account_reference),
        ).lastrowid
        with pytest.raises(sqlite3.IntegrityError, match="must be an account"):
            connection.execute(
                """UPDATE account_match_candidates SET target_reference_id = ?
                   WHERE account_candidate_id = ?""",
                (post_reference, candidate_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO platform_references
                   (external_link_id, platform_id, instance_host, object_kind,
                    native_identifier, canonical_target_url, recognizer_name, recognizer_version)
                   VALUES (999, ?, 'x.example', 'post', '9', 'https://x.example/posts/9',
                           'fixture', 'fixture-v1')""",
                (platform,),
            )
