from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase, SchemaVersionError
from media_catalog.discovery import DiscoveryService
from media_catalog.discovery.support import digest

NOW = "2026-08-06T00:00:00Z"


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
        assert database.schema_version == 3
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
    broken = (*migrations[:-1], (3, "0003_broken.sql", "CREATE TABLE partial(x); INVALID"))
    monkeypatch.setattr(database_module, "available_migrations", lambda: broken)
    with pytest.raises(SchemaVersionError, match="0003_broken"):
        CatalogDatabase(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
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
            reference_id = connection.execute(
                """INSERT INTO platform_references
                   (platform_id, instance_host, object_kind, identifier_kind,
                    native_identifier, canonical_target_url, recognizer_name, recognizer_version)
                   VALUES (?, ?, 'post', 'stable_id', '1', ?, 'fixture', 'fixture-v1')""",
                (platform, host, f"https://{host}/posts/1"),
            ).lastrowid
            connection.execute(
                """INSERT INTO external_link_references
                   (external_link_id, platform_reference_id) VALUES (?, ?)""",
                (link_id, reference_id),
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
               (platform_id, object_kind, identifier_kind, native_identifier,
                canonical_target_url, recognizer_name, recognizer_version)
               VALUES (?, 'account', 'stable_id', '1', 'https://www.pixiv.net/users/1',
                       'pixiv-user', 'fixture-v1')""",
            (pixiv,),
        ).lastrowid
        connection.execute(
            """INSERT INTO external_link_references
               (external_link_id, platform_reference_id) VALUES (?, ?)""",
            (account_link, account_reference),
        )
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
                """INSERT INTO external_link_references
                   (external_link_id, platform_reference_id) VALUES (999, ?)""",
                (post_reference,),
            )


def test_version_two_reference_upgrade_preserves_ids_and_backfills_association(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v2.sqlite3"
    migration_root = resources.files("media_catalog.migrations")
    with sqlite3.connect(path) as connection:
        for name in ("0001_initial.sql", "0002_cross_platform_discovery.sql"):
            connection.executescript(migration_root.joinpath(name).read_text())
        connection.execute("PRAGMA user_version = 2")
        pixiv = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
        ).fetchone()[0]
        link_id = connection.execute(
            """INSERT INTO external_links
               (canonical_url, canonicalization_version, resolution_state)
               VALUES ('https://www.pixiv.net/users/123', 'url-canonicalizer-v1', 'recognized')"""
        ).lastrowid
        reference_id = connection.execute(
            """INSERT INTO platform_references
               (external_link_id, platform_id, object_kind, native_identifier,
                canonical_target_url, recognizer_name, recognizer_version)
               VALUES (?, ?, 'account', '123', 'https://www.pixiv.net/users/123',
                       'pixiv-user', 'platform-recognizers-v1')""",
            (link_id, pixiv),
        ).lastrowid
        x_platform = connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = 'x'"
        ).fetchone()[0]
        account_id = connection.execute(
            """INSERT INTO accounts
               (platform_id, native_account_id, first_seen_at, last_seen_at)
               VALUES (?, 'source', 'now', 'now')""",
            (x_platform,),
        ).lastrowid
        snapshot_id = connection.execute(
            """INSERT INTO account_snapshots
               (account_id, observed_at, bio, snapshot_digest)
               VALUES (?, ?, 'https://www.pixiv.net/users/123', ?)""",
            (account_id, NOW, "s" * 64),
        ).lastrowid
        run_id = connection.execute(
            """INSERT INTO discovery_runs
               (extractor_version, canonicalizer_version, recognizer_version, scoring_version,
                started_at, finished_at, status)
               VALUES ('catalog-links-v1', 'url-canonicalizer-v1', 'platform-recognizers-v1',
                       'link-evidence-v1', ?, ?, 'complete')""",
            (NOW, NOW),
        ).lastrowid
        occurrence_digest = digest(
            "account",
            account_id,
            snapshot_id,
            None,
            "account.bio",
            "$.bio[0]",
            "https://www.pixiv.net/users/123",
            NOW,
        )
        observation_id = connection.execute(
            """INSERT INTO link_observations
               (external_link_id, discovery_run_id, subject_kind, subject_account_id,
                account_snapshot_id, source_context, json_path, original_url, observed_at,
                extractor_version, occurrence_digest)
               VALUES (?, ?, 'account', ?, ?, 'account.bio', '$.bio[0]', ?, ?,
                       'catalog-links-v1', ?)""",
            (
                link_id,
                run_id,
                account_id,
                snapshot_id,
                "https://www.pixiv.net/users/123",
                NOW,
                occurrence_digest,
            ),
        ).lastrowid
        legacy_candidate_key = digest(
            "account", account_id, "same_identity", pixiv, "", "account", "123"
        )
        candidate_id = connection.execute(
            """INSERT INTO account_match_candidates
               (candidate_key, subject_account_id, target_reference_id, relation_kind,
                current_state, score, score_version, evidence_generation, review_revision,
                created_at, updated_at)
               VALUES (?, ?, ?, 'same_identity', 'rejected', 70, 'link-evidence-v1', 1, 1,
                       ?, ?)""",
            (legacy_candidate_key, account_id, reference_id, NOW, NOW),
        ).lastrowid
        legacy_evidence_digest = digest(
            "account", legacy_candidate_key, occurrence_digest, "official_link"
        )
        evidence_id = connection.execute(
            """INSERT INTO match_evidence
               (evidence_digest, stance, evidence_kind, direction, strength, detector,
                detector_version, link_observation_id, platform_reference_id, observed_at,
                explanation)
               VALUES (?, 'supports', 'official_link', 'subject_to_target', 'strong',
                       'link-discovery', 'catalog-links-v1', ?, ?, ?, 'legacy evidence')""",
            (legacy_evidence_digest, observation_id, reference_id, NOW),
        ).lastrowid
        connection.execute(
            """INSERT INTO account_candidate_evidence (account_candidate_id, evidence_id)
               VALUES (?, ?)""",
            (candidate_id, evidence_id),
        )
        connection.execute(
            """INSERT INTO account_candidate_decisions
               (account_candidate_id, prior_state, decision, evidence_generation, note, decided_at)
               VALUES (?, 'pending', 'rejected', 1, 'keep this review', ?)""",
            (candidate_id, NOW),
        )

    with CatalogDatabase(path) as database:
        reference = database.connection.execute(
            """SELECT platform_reference_id, identifier_kind
               FROM platform_references"""
        ).fetchone()
        association = database.connection.execute(
            """SELECT external_link_id, platform_reference_id
               FROM external_link_references"""
        ).fetchone()
        assert database.schema_version == 3
        assert tuple(reference) == (reference_id, "stable_id")
        assert tuple(association) == (link_id, reference_id)
        assert (
            database.connection.execute(
                """SELECT target_reference_id FROM account_match_candidates
               WHERE account_candidate_id = ?""",
                (candidate_id,),
            ).fetchone()[0]
            == reference_id
        )
        assert database.doctor()["ok"] is True
        DiscoveryService(database).discover()
        candidate = database.connection.execute(
            """SELECT account_candidate_id, current_state, candidate_key
               FROM account_match_candidates"""
        ).fetchone()
        assert candidate["account_candidate_id"] == candidate_id
        assert candidate["current_state"] == "rejected"
        assert candidate["candidate_key"] != legacy_candidate_key
        assert (
            database.connection.execute("SELECT COUNT(*) FROM account_match_candidates").fetchone()[
                0
            ]
            == 1
        )
        assert database.connection.execute("SELECT COUNT(*) FROM match_evidence").fetchone()[0] == 1
        assert (
            database.connection.execute("SELECT evidence_id FROM match_evidence").fetchone()[0]
            == evidence_id
        )
        assert (
            database.connection.execute("SELECT note FROM account_candidate_decisions").fetchone()[
                0
            ]
            == "keep this review"
        )


def test_migration_foreign_key_check_rolls_back_invalid_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import media_catalog.database as database_module

    path = tmp_path / "invalid-fk.sqlite3"
    migrations = database_module.available_migrations()
    invalid = (
        *migrations[:-1],
        (
            3,
            "0003_invalid_fk.sql",
            """CREATE TABLE invalid_child(
                   platform_id INTEGER REFERENCES platforms(platform_id));
               INSERT INTO invalid_child(platform_id) VALUES (999999);""",
        ),
    )
    monkeypatch.setattr(database_module, "available_migrations", lambda: invalid)
    with pytest.raises(SchemaVersionError, match="foreign-key violation"):
        CatalogDatabase(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'invalid_child'"
            ).fetchone()[0]
            == 0
        )
