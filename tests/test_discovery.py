from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.discovery import DiscoveryService
from media_catalog.records import AccountRecord, PostRecord, RawRecord
from media_catalog.writer import CatalogWriter

NOW = "2026-08-06T00:00:00Z"


def _catalog(path: Path) -> CatalogDatabase:
    database = CatalogDatabase(path)
    writer = CatalogWriter(database)
    raw = json.dumps(
        {
            "entities": {"urls": [{"expanded_url": "https://pixiv.net/artworks/133416234"}]},
            "card": {"card_url": "https://linktr.ee/example"},
            "quoted_tweet": {"source_url": "https://danbooru.donmai.us/post/show/9714844"},
        },
        sort_keys=True,
    ).encode()
    with database.transaction():
        raw_id = writer.store_raw(RawRecord(raw, "application/json", "post", "42", NOW))
        account = writer.upsert_account(
            AccountRecord(
                "x",
                "7",
                NOW,
                bio="Elsewhere https://www.pixiv.net/en/users/27631291",
                website_url="https://linktr.ee/example",
                profile_url="https://x.com/example",
            ),
            raw_observation_id=raw_id,
        )
        post = writer.upsert_post(
            PostRecord(
                "x",
                "42",
                NOW,
                canonical_url="https://x.com/example/status/42",
                text="source https://gelbooru.com/index.php?page=post&s=view&id=12370900",
            ),
            raw_observation_id=raw_id,
        )
        writer.add_participant(post.id, account.id, "author")
    return database


def test_offline_discovery_preserves_provenance_contexts_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", fail_connect)
    with _catalog(tmp_path / "catalog.sqlite3") as database:
        raw_before = bytes(
            database.connection.execute("SELECT payload FROM raw_payloads").fetchone()[0]
        )
        first = DiscoveryService(database).discover()
        first_counts = {
            table: database.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "external_links",
                "link_observations",
                "platform_references",
                "account_match_candidates",
                "post_match_candidates",
                "match_evidence",
            )
        }
        second = DiscoveryService(database).discover()
        second_counts = {
            table: database.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in first_counts
        }
        assert first.status == second.status == "complete"
        assert second_counts == first_counts
        assert second.counts["existing"] == first_counts["link_observations"]
        assert (
            bytes(database.connection.execute("SELECT payload FROM raw_payloads").fetchone()[0])
            == raw_before
        )
        contexts = {
            row[0]
            for row in database.connection.execute("SELECT source_context FROM link_observations")
        }
        assert {
            "account.bio",
            "account.website",
            "account.profile",
            "post.canonical",
            "post.text",
            "post.entity",
            "post.card",
            "post.quote",
        } <= contexts
        originals = database.connection.execute(
            """SELECT original_url, original_query, canonical_url FROM link_observations
               JOIN external_links USING (external_link_id)
               WHERE original_url LIKE '%gelbooru%'"""
        ).fetchone()
        assert originals[1] == "page=post&s=view&id=12370900"
        assert "id=12370900" in originals[2]
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM post_match_candidates WHERE current_state <> 'pending'"
            ).fetchone()[0]
            == 0
        )


def test_link_queries_filter_without_exposing_raw_payload(tmp_path: Path) -> None:
    with _catalog(tmp_path / "private-name.sqlite3") as database:
        service = DiscoveryService(database)
        service.discover()
        result = service.links(platform="pixiv", object_kind="post")
        assert result["filters"] == {"platform": "pixiv", "object_kind": "post"}
        assert len(result["results"]) == 1
        encoded = json.dumps(result)
        assert '"entities": {' not in encoded
        assert str(tmp_path) not in encoded


def test_url_aliases_keep_independent_links_to_one_semantic_reference(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            writer.upsert_account(
                AccountRecord(
                    "x",
                    "1",
                    NOW,
                    bio=("https://pixiv.net/users/123 https://www.pixiv.net/en/users/123"),
                )
            )
        service = DiscoveryService(database)
        service.discover()
        results = service.links(platform="pixiv", object_kind="account")["results"]
        assert len(results) == 2
        assert {item["native_identifier"] for item in results} == {"123"}
        assert {item["identifier_kind"] for item in results} == {"stable_id"}
        assert (
            database.connection.execute("SELECT COUNT(*) FROM platform_references").fetchone()[0]
            == 1
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM external_link_references").fetchone()[
                0
            ]
            == 2
        )
        service.discover()
        assert len(service.links(platform="pixiv")["results"]) == 2


def test_handle_account_references_remain_queryable_without_identity_candidates(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            writer.upsert_account(
                AccountRecord("x", "1", NOW, bio="Elsewhere https://x.com/AnotherArtist")
            )
        service = DiscoveryService(database)
        service.discover()
        links = service.links(platform="x", object_kind="account")["results"]
        assert len(links) == 1
        assert links[0]["identifier_kind"] == "handle"
        assert links[0]["native_identifier"] == "anotherartist"
        assert service.candidates(kind="account")["results"] == []


def test_self_links_remain_observations_without_candidates(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            writer.upsert_post(
                PostRecord("x", "42", NOW, canonical_url="https://x.com/name/status/42")
            )
        service = DiscoveryService(database)
        service.discover()
        assert (
            database.connection.execute("SELECT COUNT(*) FROM link_observations").fetchone()[0] == 1
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM post_match_candidates").fetchone()[0]
            == 0
        )


def test_review_history_is_append_only_and_confirmation_materializes_empty_account(
    tmp_path: Path,
) -> None:
    with _catalog(tmp_path / "catalog.sqlite3") as database:
        service = DiscoveryService(database)
        service.discover()
        candidate_id = database.connection.execute(
            """SELECT c.account_candidate_id FROM account_match_candidates c
               JOIN platform_references r ON r.platform_reference_id = c.target_reference_id
               JOIN platforms p ON p.platform_id = r.platform_id
               WHERE p.platform_key = 'pixiv'"""
        ).fetchone()[0]
        account_match = next(
            item
            for item in service.candidates(kind="account")["results"]
            if item["account_candidate_id"] == candidate_id
        )
        match_ref = account_match["match_ref"]
        generation = account_match["evidence_generation"]
        rejected = service.review(
            match_ref, "rejected", note="check later", expected_generation=generation
        )
        assert rejected["decision"] == "rejected"
        service.discover()
        assert service.candidate(match_ref)["candidate"]["current_state"] == "rejected"
        confirmed = service.review(match_ref, "confirmed", note="verified profile link")
        assert confirmed["identity_id"] is not None
        service.discover()
        shown = service.candidate(match_ref)
        assert [item["decision"] for item in shown["history"]] == ["rejected", "confirmed"]
        pixiv = database.connection.execute(
            """SELECT a.account_id, a.availability FROM accounts a
               JOIN platforms p USING (platform_id)
               WHERE p.platform_key = 'pixiv' AND a.native_account_id = '27631291'"""
        ).fetchone()
        assert pixiv["availability"] == "unknown"
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM account_snapshots WHERE account_id = ?",
                (pixiv["account_id"],),
            ).fetchone()[0]
            == 0
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM identity_accounts").fetchone()[0] == 2
        )
        with pytest.raises(ValueError, match="stale review"):
            service.review(match_ref, "pending", expected_generation=generation + 1)
        revision = shown["candidate"]["review_revision"]
        writer = CatalogWriter(database)
        with database.transaction():
            unrelated = writer.upsert_account(AccountRecord("x", "unrelated", NOW)).id
            unrelated_identity = database.connection.execute(
                "INSERT INTO identities (created_at, label) VALUES (?, 'keep-me')", (NOW,)
            ).lastrowid
            database.connection.execute(
                """INSERT INTO identity_accounts (identity_id, account_id, added_at)
                   VALUES (?, ?, ?)""",
                (unrelated_identity, unrelated, NOW),
            )
        service.review(match_ref, "rejected", expected_revision=revision)
        kept = database.connection.execute(
            """SELECT i.label FROM identities i JOIN identity_accounts ia USING (identity_id)
               WHERE ia.account_id = ?""",
            (unrelated,),
        ).fetchone()
        assert kept["label"] == "keep-me"
        with pytest.raises(ValueError, match="stale review"):
            service.review(match_ref, "confirmed", expected_revision=revision)


def test_post_characteristics_are_manual_repeatable_and_do_not_touch_provider_relations(
    tmp_path: Path,
) -> None:
    with _catalog(tmp_path / "catalog.sqlite3") as database:
        service = DiscoveryService(database)
        service.discover()
        match_ref = service.candidates(kind="post")["results"][0]["match_ref"]
        before = database.connection.execute("SELECT COUNT(*) FROM post_relations").fetchone()[0]
        service.add_characteristic(match_ref, "text_removed", direction="subject_to_target")
        service.add_characteristic(match_ref, "progression", source_label="user-example")
        service.add_characteristic(match_ref, "progression", source_label="user-example")
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM post_candidate_characteristics"
            ).fetchone()[0]
            == 2
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM post_relations").fetchone()[0]
            == before
        )


def test_malformed_retained_record_is_counted_without_leaking_payload(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            raw_id = writer.store_raw(
                RawRecord(b"{private malformed", "application/json", "post", "bad", NOW)
            )
            writer.upsert_post(PostRecord("x", "bad", NOW), raw_observation_id=raw_id)
        result = DiscoveryService(database).discover()
        assert result.counts["failed"] == 1
        run = database.connection.execute(
            "SELECT diagnostic FROM discovery_runs WHERE discovery_run_id = ?", (result.run_id,)
        ).fetchone()
        assert run["diagnostic"] is None


def test_manual_post_candidates_canonicalize_symmetric_pairs_and_scores_do_not_decide(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            first = writer.upsert_post(PostRecord("x", "1", NOW)).id
            second = writer.upsert_post(PostRecord("x", "2", NOW)).id
        service = DiscoveryService(database)
        forward = service.create_post_candidate(
            first,
            second,
            "same_work",
            explanation="user compared public metadata",
            strength="exact",
        )
        reverse = service.create_post_candidate(
            second,
            first,
            "same_work",
            explanation="user compared public metadata",
            strength="exact",
        )
        assert forward == reverse
        shown = service.candidate(forward)
        assert shown["candidate"]["score"] == 100
        assert shown["candidate"]["current_state"] == "pending"
        assert shown["evidence"][0]["direction"] == "symmetric"
        with pytest.raises(ValueError, match="different"):
            service.create_post_candidate(first, first, "variant_of", explanation="invalid")


def test_identity_conflict_is_reported_without_partial_decision(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            first = writer.upsert_account(AccountRecord("x", "1", NOW)).id
            second = writer.upsert_account(AccountRecord("x", "2", NOW)).id
            first_identity = database.connection.execute(
                "INSERT INTO identities (created_at) VALUES (?)", (NOW,)
            ).lastrowid
            second_identity = database.connection.execute(
                "INSERT INTO identities (created_at) VALUES (?)", (NOW,)
            ).lastrowid
            database.connection.execute(
                """INSERT INTO identity_accounts (identity_id, account_id, added_at)
                   VALUES (?, ?, ?), (?, ?, ?)""",
                (first_identity, first, NOW, second_identity, second, NOW),
            )
            candidate_id = database.connection.execute(
                """INSERT INTO account_match_candidates
                   (candidate_key, subject_account_id, target_account_id, relation_kind,
                    score_version, created_at, updated_at)
                   VALUES (?, ?, ?, 'same_identity', 'link-evidence-v1', ?, ?)""",
                ("c" * 64, first, second, NOW, NOW),
            ).lastrowid
        service = DiscoveryService(database)
        with pytest.raises(ValueError, match="identity conflict"):
            service.review(f"account:{candidate_id}", "confirmed")
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM account_candidate_decisions"
            ).fetchone()[0]
            == 0
        )
        assert (
            database.connection.execute(
                "SELECT current_state FROM account_match_candidates"
            ).fetchone()[0]
            == "pending"
        )


def test_instance_scoped_reference_does_not_cross_resolve(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            writer.upsert_post(PostRecord("mastodon", "123", NOW))
            source = writer.upsert_post(
                PostRecord("x", "1", NOW, text="https://baraag.net/@artist/123")
            ).id
        service = DiscoveryService(database)
        service.discover()
        candidate = database.connection.execute(
            "SELECT * FROM post_match_candidates WHERE subject_post_id = ?", (source,)
        ).fetchone()
        assert candidate["target_post_id"] is None
        assert candidate["target_reference_id"] is not None


def test_snapshot_and_derivation_versions_do_not_collapse_or_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            writer.upsert_account(AccountRecord("x", "1", NOW, bio="https://www.pixiv.net/users/5"))
            writer.upsert_account(
                AccountRecord(
                    "x",
                    "1",
                    NOW,
                    display_name="changed",
                    bio="https://www.pixiv.net/users/5",
                )
            )
        service = DiscoveryService(database)
        service.discover()
        assert (
            database.connection.execute("SELECT COUNT(*) FROM link_observations").fetchone()[0] == 2
        )
        import media_catalog.discovery as discovery_module

        candidate = service.candidates(kind="account")["results"][0]
        service.review(candidate["match_ref"], "rejected")
        initial_score = candidate["score"]
        initial_generation = candidate["evidence_generation"]
        monkeypatch.setattr(discovery_module, "CANONICALIZER_VERSION", "url-canonicalizer-v2")
        service.discover()
        assert (
            database.connection.execute("SELECT COUNT(*) FROM link_observations").fetchone()[0] == 2
        )
        after_canonicalizer = service.candidates(kind="account")["results"]
        assert len(after_canonicalizer) == 1
        assert after_canonicalizer[0]["current_state"] == "rejected"
        assert after_canonicalizer[0]["score"] == initial_score
        assert after_canonicalizer[0]["evidence_generation"] == initial_generation
        import media_catalog.links as links_module

        monkeypatch.setattr(discovery_module, "RECOGNIZER_VERSION", "platform-recognizers-v2")
        monkeypatch.setattr(links_module, "RECOGNIZER_VERSION", "platform-recognizers-v2")
        service.discover()
        after_recognizer = service.candidates(kind="account")["results"]
        assert len(after_recognizer) == 1
        assert after_recognizer[0]["current_state"] == "rejected"
        assert after_recognizer[0]["score"] == initial_score
        assert after_recognizer[0]["evidence_generation"] == initial_generation
        assert (
            database.connection.execute(
                """SELECT COUNT(*) FROM external_links el
               WHERE NOT EXISTS (SELECT 1 FROM link_observations lo
                                 WHERE lo.external_link_id = el.external_link_id)"""
            ).fetchone()[0]
            == 0
        )


def test_link_output_redacts_sensitive_query_values(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            writer.upsert_post(
                PostRecord(
                    "x",
                    "1",
                    NOW,
                    text=(
                        "https://example.test/path?access_token=SECRET&"
                        "X-Amz-Signature=AWSSECRET&id=7#access_token=FRAGMENTSECRET"
                    ),
                )
            )
        service = DiscoveryService(database)
        service.discover()
        encoded = json.dumps(service.links())
        assert "SECRET" not in encoded
        assert "AWSSECRET" not in encoded
        assert "FRAGMENTSECRET" not in encoded
        assert "%3Credacted%3E" in encoded
        assert "id=7" in encoded
