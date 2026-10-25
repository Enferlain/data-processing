"""Work and relationship model tests (OpenSpec add-work-relationship-model).

Works are minimal deterministic anchors; relationships are typed, epistemic,
canonically oriented conclusions; evidence rides the shared ledger; review is
append-only and reversible; storage immutability is trigger-enforced from
migration 0015; seeding is offline, deterministic, and idempotent.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.projections import run_export
from media_catalog.projections.output import parse_jsonl
from media_catalog.records import RelationshipRecord
from media_catalog.records.relationships import RELATIONSHIP_KINDS, relationship_key
from media_catalog.relationships import (
    materialize_works,
    review_relationship,
    seed_relationships,
)

NOW = "2026-10-16T00:00:00Z"
SHA = "a" * 64
SHA2 = "b" * 64


def _seed(catalog: Path) -> dict[str, int]:
    """One shared-asset pair, one sample/original pair, one repost citation."""

    with CatalogDatabase(catalog) as database:
        c = database.connection
        c.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name) "
            "VALUES ('danbooru', 'Danbooru')"
        )
        platform = int(
            c.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
            ).fetchone()[0]
        )
        # Post A: original + sample occurrences; Post B: a repost of post A;
        # Post C: an unrelated mirror sharing post A's original bytes.
        for native, url in (
            ("3001", "https://danbooru.donmai.us/posts/3001"),
            ("3002", "https://danbooru.donmai.us/posts/3002"),
            ("3003", "https://danbooru.donmai.us/posts/3003"),
        ):
            c.execute(
                """INSERT INTO posts (platform_id, native_post_id, canonical_url,
                                      first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, '2026-01-01T00:00:00Z', '2026-02-01T00:00:00Z')""",
                (platform, native, url),
            )
        ids = {
            native: int(row[0])
            for native, row in (
                (
                    native,
                    c.execute(
                        "SELECT post_id FROM posts WHERE native_post_id = ?", (native,)
                    ).fetchone(),
                )
                for native in ("3001", "3002", "3003")
            )
        }
        for post, source_key, role in (
            ("3001", "danbooru:3001:0", "original"),
            ("3001", "danbooru:3001:1", "sample"),
            ("3002", "danbooru:3002:0", "original"),
            ("3003", "danbooru:3003:0", "original"),
        ):
            c.execute(
                """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                                  media_type, role, observed_at)
                   VALUES (?, ?, 0, 'image', ?, '2026-01-01T00:00:00Z')""",
                (ids[post], source_key, role),
            )
        occurrences = {
            source_key: int(row[0])
            for source_key, row in (
                (
                    key,
                    c.execute(
                        "SELECT media_occurrence_id FROM media_occurrences WHERE source_key = ?",
                        (key,),
                    ).fetchone(),
                )
                for key in (
                    "danbooru:3001:0",
                    "danbooru:3001:1",
                    "danbooru:3002:0",
                    "danbooru:3003:0",
                )
            )
        }
        for sha in (SHA, SHA2):
            c.execute(
                """INSERT INTO assets (verified_sha256, storage_kind, verification_method,
                                       byte_size, verified_at, detected_mime_type,
                                       detected_width, detected_height)
                   VALUES (?, 'managed', 'sha256_adoption', 100,
                           '2026-01-02T00:00:00Z', 'image/jpeg', 800, 600)""",
                (sha,),
            )
        asset_ids = {
            sha: int(row[0])
            for sha, row in (
                (
                    sha,
                    c.execute(
                        "SELECT asset_id FROM assets WHERE verified_sha256 = ?", (sha,)
                    ).fetchone(),
                )
                for sha in (SHA, SHA2)
            )
        }
        for key, sha in (
            ("danbooru:3001:0", SHA),
            ("danbooru:3001:1", SHA),
            ("danbooru:3003:0", SHA),
            ("danbooru:3002:0", SHA2),
        ):
            c.execute(
                """INSERT INTO occurrence_assets (media_occurrence_id, asset_id,
                                                  relationship, verification_source)
                   VALUES (?, ?, 'exact_bytes', 'byte_verification')""",
                (occurrences[key], asset_ids[sha]),
            )
        # Post B cites post A's URL as its provider-declared source.
        c.execute(
            """INSERT INTO platform_references (
                   platform_id, object_kind, identifier_kind, native_identifier,
                   canonical_target_url, recognizer_name, recognizer_version,
                   resolved_post_id
               ) VALUES (?, 'post', 'stable_id', '3001',
                         'https://danbooru.donmai.us/posts/3001',
                         'test-recognizer', 'v1', ?)""",
            (platform, ids["3001"]),
        )
        reference = int(
            c.execute("SELECT platform_reference_id FROM platform_references").fetchone()[0]
        )
        c.execute(
            """INSERT INTO raw_payloads (payload, sha256, byte_size, media_type)
               VALUES (x'7b7d', ?, 2, 'application/json')""",
            ("c" * 64,),
        )
        payload_id = int(c.execute("SELECT raw_payload_id FROM raw_payloads").fetchone()[0])
        c.execute(
            """INSERT INTO raw_observations (remote_run_id, platform_id, object_kind,
                                             native_id, media_type, observed_at,
                                             adapter_version, schema_version, status,
                                             raw_payload_id)
               VALUES (NULL, ?, 'post', '3002', 'application/json',
                       '2026-01-01T00:00:00Z', 'test-v1', 'test-v1', 200, ?)""",
            (platform, payload_id),
        )
        raw = int(c.execute("SELECT raw_observation_id FROM raw_observations").fetchone()[0])
        c.execute(
            """INSERT INTO post_external_references (post_id, platform_reference_id,
                                                     reference_kind, raw_observation_id,
                                                     observed_at)
               VALUES (?, ?, 'source_url', ?, '2026-01-01T00:00:00Z')""",
            (ids["3002"], reference, raw),
        )
        # An unresolved source URL (external link only, no typed platform
        # reference) must be counted as a skip, not dropped by the JOIN.
        c.execute(
            """INSERT INTO external_links (canonical_url, canonicalization_version,
                                           resolution_state, resolution_reason)
               VALUES ('https://example.com/unresolved-source', 'url-v1',
                       'unresolved', 'no recognizer')"""
        )
        link = int(c.execute("SELECT external_link_id FROM external_links").fetchone()[0])
        c.execute(
            """INSERT INTO post_external_references (post_id, external_link_id,
                                                     reference_kind, raw_observation_id,
                                                     observed_at)
               VALUES (?, ?, 'source_url', ?, '2026-01-01T00:00:00Z')""",
            (ids["3003"], link, raw),
        )
        c.execute(
            """INSERT INTO post_relations (source_post_id, target_post_id, relation_type,
                                           raw_observation_id)
               VALUES (?, ?, 'parent_of', ?)""",
            (ids["3003"], ids["3001"], raw),
        )
        # A declaration without a retained raw observation still materializes;
        # a self-link is skipped.
        c.execute(
            """INSERT INTO post_relations (source_post_id, target_post_id, relation_type,
                                           raw_observation_id)
               VALUES (?, ?, 'parent_of', NULL), (?, ?, 'parent_of', NULL)""",
            (ids["3002"], ids["3001"], ids["3003"], ids["3003"]),
        )
        database.connection.commit()
        return {**ids, **occurrences}


# --- Records: vocabulary, orientation, keys -----------------------------------


def test_symmetric_kinds_canonicalize_and_directional_ones_do_not() -> None:
    forward = RelationshipRecord(
        subject_kind="media_occurrence",
        subject_id=7,
        relation_kind="same_bytes",
        target_kind="media_occurrence",
        target_id=3,
        epistemic_status="verified",
    )
    assert (forward.subject_id, forward.target_id) == (3, 7)
    assert forward.relationship_key == relationship_key(
        "same_bytes", "media_occurrence", 3, "media_occurrence", 7
    )
    directional = RelationshipRecord(
        subject_kind="media_occurrence",
        subject_id=9,
        relation_kind="thumbnail_of",
        target_kind="media_occurrence",
        target_id=2,
        epistemic_status="observed",
    )
    assert (directional.subject_id, directional.target_id) == (9, 2)
    with pytest.raises(ValueError, match="does not link"):
        RelationshipRecord(
            subject_kind="post",
            subject_id=1,
            relation_kind="same_bytes",
            target_kind="post",
            target_id=2,
            epistemic_status="verified",
        )
    with pytest.raises(ValueError, match="cannot link an object to itself"):
        RelationshipRecord(
            subject_kind="post",
            subject_id=1,
            relation_kind="reposted_from",
            target_kind="post",
            target_id=1,
            epistemic_status="observed",
        )
    assert set(RELATIONSHIP_KINDS) == {
        "same_bytes",
        "thumbnail_of",
        "reposted_from",
        "parent_of",
        "page_of",
        "same_work",
        "variant_of",
        "derived_from",
        "reencoded_from",
        "resized_from",
        "cropped_from",
        "censored_variant_of",
        "edited_from",
        "transcoded_from",
        "extracted_from",
    }


# --- Storage tiers ------------------------------------------------------------


def test_storage_immutability_tiers(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    ids = _seed(catalog)
    with CatalogDatabase(catalog) as database:
        c = database.connection
        c.execute(
            "INSERT INTO works (origin_post_id, work_kind, created_at) "
            "VALUES (?, 'single', '2026-01-01T00:00:00Z')",
            (ids["3001"],),
        )
        c.execute(
            "INSERT INTO work_representations VALUES (1, ?, '2026-01-01T00:00:00Z')",
            (ids["danbooru:3001:0"],),
        )
        c.execute(
            f"""INSERT INTO relationships (relationship_key, subject_kind, subject_id,
                   relation_kind, target_kind, target_id, epistemic_status, created_at,
                   updated_at) VALUES ('{SHA}', 'media_occurrence',
                   {ids["danbooru:3001:0"]}, 'same_bytes', 'media_occurrence',
                   {ids["danbooru:3001:1"]}, 'verified', '2026-01-01T00:00:00Z',
                   '2026-01-01T00:00:00Z')"""
        )
        c.execute(
            "INSERT INTO match_evidence (evidence_digest, stance, evidence_kind, "
            "direction, strength, detector, detector_version, observed_at, explanation, "
            "components_json) VALUES (?, 'supports', 'hash_equality', 'symmetric', "
            "'exact', 'asset-sha256', 'v1', '2026-01-01T00:00:00Z', 'x', '{}')",
            (SHA2,),
        )
        c.execute("INSERT INTO relationship_evidence VALUES (1, 1, '2026-01-01T00:00:00Z')")
        c.execute(
            "INSERT INTO relationship_review_decisions (relationship_id, prior_state, "
            "decision, decided_at) VALUES (1, 'pending', 'confirmed', "
            "'2026-01-01T00:00:00Z')"
        )
        c.execute(
            "INSERT INTO relationship_status_history (relationship_id, prior_status, "
            "new_status, cause, at) VALUES (1, 'observed', 'reviewed', "
            "'review decision', '2026-01-01T00:00:00Z')"
        )
        c.commit()
        c.execute(
            "UPDATE relationships SET review_state = 'confirmed', "
            "epistemic_status = 'reviewed', updated_at = '2026-01-02T00:00:00Z'"
        )
        c.commit()  # permitted: current state fields only
        for statement in (
            "UPDATE works SET work_kind = 'unknown'",
            "DELETE FROM works",
            "DELETE FROM work_representations",
            "UPDATE relationships SET subject_id = 2",
            "UPDATE relationships SET relation_kind = 'same_work'",
            "DELETE FROM relationships",
            "UPDATE relationship_evidence SET added_at = '2026-01-01T00:00:00Z'",
            "DELETE FROM relationship_evidence",
            "UPDATE relationship_review_decisions SET decision = 'rejected'",
            "DELETE FROM relationship_review_decisions",
            "UPDATE relationship_status_history SET cause = 'x'",
            "DELETE FROM relationship_status_history",
        ):
            with pytest.raises(Exception, match=r"immutable|append-only|never deleted|retained"):
                c.execute(statement)
                c.commit()


# --- Materialization and seeding ----------------------------------------------


def test_materialize_works_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    with CatalogDatabase(catalog) as database:
        first = materialize_works(database, clock=lambda: NOW)
    assert first["works_created"] == 3
    assert first["representations_linked"] == 4
    with CatalogDatabase(catalog) as database:
        counts = database.connection.execute(
            """SELECT (SELECT COUNT(*) FROM works),
                      (SELECT COUNT(*) FROM work_representations),
                      (SELECT work_kind FROM works w JOIN posts p ON p.post_id = w.origin_post_id
                        WHERE p.native_post_id = '3001')"""
        ).fetchone()
    assert tuple(counts) == (3, 4, "multi_page")
    second = materialize_works(CatalogDatabase(catalog), clock=lambda: NOW)
    assert second["works_created"] == 0
    assert second["representations_linked"] == 0


def test_seeder_materializes_deterministic_kinds_with_evidence(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    ids = _seed(catalog)
    with CatalogDatabase(catalog) as database:
        socket_default = socket.socket.connect

        def fail_connect(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("network access attempted")

        socket.socket.connect = fail_connect
        try:
            result = seed_relationships(database, clock=lambda: NOW)
        finally:
            socket.socket.connect = socket_default
    # same_bytes pairs: (3001:0, 3001:1), (3001:0, 3003:0), (3001:1, 3003:0).
    assert result["same_bytes"] == {"materialized": 3, "existing": 0}
    # thumbnail_of: 3001:1 (sample) -> 3001:0 (original).
    assert result["thumbnail_of"] == {"materialized": 1, "existing": 0, "skipped": 0}
    # reposted_from: post 3002 cites post 3001; the unresolved source URL
    # declared by post 3003 is counted as a skip, not dropped.
    assert result["reposted_from"] == {
        "materialized": 1,
        "existing": 0,
        "skipped": 1,
        "skipped_reasons": {
            "source_url_unresolved": 1,
            "target_post_unresolved": 0,
            "self_reference": 0,
        },
    }
    # parent_of: 3003 -> 3001 with a raw observation, 3002 -> 3001 without one
    # (still materializes), and the 3003 self-link is skipped.
    assert result["parent_of"] == {"materialized": 2, "existing": 0, "skipped": 1}

    with CatalogDatabase(catalog) as database:
        c = database.connection
        rows = c.execute(
            """SELECT relation_kind, epistemic_status, review_state, subject_id, target_id
                 FROM relationships ORDER BY relationship_id"""
        ).fetchall()
        by_kind: dict[str, list[tuple]] = {}
        for row in rows:
            by_kind.setdefault(row["relation_kind"], []).append(
                (row["epistemic_status"], row["review_state"], row["subject_id"], row["target_id"])
            )
        assert len(by_kind["same_bytes"]) == 3
        assert all(status == "verified" for status, *_ in by_kind["same_bytes"])
        assert all(subject < target for _, _, subject, target in by_kind["same_bytes"])
        assert by_kind["thumbnail_of"][0][0] == "observed"
        assert by_kind["reposted_from"][0][0] == "observed"
        assert by_kind["parent_of"][0] == ("observed", "pending", ids["3002"], ids["3001"])
        assert by_kind["parent_of"][1] == ("observed", "pending", ids["3003"], ids["3001"])
        evidence = c.execute(
            """SELECT detector, detector_version, stance FROM relationship_evidence re
                 JOIN match_evidence me ON me.evidence_id = re.evidence_id"""
        ).fetchall()
        assert len(evidence) == 7
        assert {row["detector"] for row in evidence} == {
            "asset-sha256",
            "occurrence-role",
            "source-url-reference",
            "provider-parent-relation",
        }
        assert all(row["stance"] == "supports" for row in evidence)

        again = seed_relationships(database, clock=lambda: NOW)
    assert again["same_bytes"] == {"materialized": 0, "existing": 3}
    assert again["thumbnail_of"] == {"materialized": 0, "existing": 1, "skipped": 0}
    assert again["reposted_from"] == {
        "materialized": 0,
        "existing": 1,
        "skipped": 1,
        "skipped_reasons": {
            "source_url_unresolved": 1,
            "target_post_unresolved": 0,
            "self_reference": 0,
        },
    }
    assert again["parent_of"] == {"materialized": 0, "existing": 2, "skipped": 1}


# --- Review lifecycle ----------------------------------------------------------


def test_review_is_append_only_and_reversible(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    with CatalogDatabase(catalog) as database:
        seed_relationships(database, clock=lambda: NOW)
        relationship_id = int(
            database.connection.execute(
                "SELECT relationship_id FROM relationships WHERE relation_kind = 'reposted_from'"
            ).fetchone()[0]
        )
        review_relationship(database, relationship_id, "confirm", clock=lambda: NOW)
        review_relationship(database, relationship_id, "reject", note="miscited", clock=lambda: NOW)
        c = database.connection
        row = c.execute(
            "SELECT epistemic_status, review_state FROM relationships WHERE relationship_id = ?",
            (relationship_id,),
        ).fetchone()
        decisions = c.execute(
            "SELECT prior_state, decision FROM relationship_review_decisions "
            "WHERE relationship_id = ? ORDER BY relationship_decision_id",
            (relationship_id,),
        ).fetchall()
        history = c.execute(
            "SELECT prior_status, new_status FROM relationship_status_history "
            "WHERE relationship_id = ? ORDER BY relationship_status_history_id",
            (relationship_id,),
        ).fetchall()
        evidence_count = c.execute(
            "SELECT COUNT(*) FROM relationship_evidence WHERE relationship_id = ?",
            (relationship_id,),
        ).fetchone()[0]
    assert (row["epistemic_status"], row["review_state"]) == ("reviewed", "rejected")
    assert [(d["prior_state"], d["decision"]) for d in decisions] == [
        ("pending", "confirmed"),
        ("confirmed", "rejected"),
    ]
    assert [(h["prior_status"], h["new_status"]) for h in history] == [("observed", "reviewed")]
    assert evidence_count == 1


# --- Works projection -----------------------------------------------------------


def test_works_projection_prefers_original_and_excludes_thumbnails(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    with CatalogDatabase(catalog) as database:
        materialize_works(database, clock=lambda: NOW)
    first = run_export(catalog, kind="works", out_dir=tmp_path / "one", clock=lambda: NOW)
    rows = parse_jsonl(tmp_path / "one" / "works-projection.jsonl")
    assert len(rows) == 3
    by_origin = {row["origin_native_post_id"]: row for row in rows}
    anchor = by_origin["3001"]
    assert {rep["role"] for rep in anchor["representations"]} == {"original", "sample"}
    assert anchor["preferred_representation"]["role"] == "original"
    assert anchor["work_kind"] == "multi_page"
    assert anchor["same_work_count"] == 0
    assert all(
        row["preferred_representation"] is None
        or row["preferred_representation"]["role"] != "sample"
        for row in rows
    )
    second = run_export(catalog, kind="works", out_dir=tmp_path / "two", clock=lambda: NOW)
    assert first["spec_digest"] == second["spec_digest"]
    assert first["selection_digest"] == second["selection_digest"]
