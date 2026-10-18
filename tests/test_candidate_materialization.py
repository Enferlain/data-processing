"""Candidate materialization tests (OpenSpec add-reviewed-candidate-materialization).

Confirmed post candidates become reviewed relationship rows under the fixed
kind mapping, with evidence carry-over and decision-ledger provenance;
anything unconfirmed or unresolvable is refused with a typed reason; the
candidate side is never written; execution is offline.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.relationships import materialize_candidates, materialize_works

NOW = "2026-10-18T00:00:00Z"


def _seed(catalog: Path) -> dict[str, int]:
    """Posts A/B/C (B cites A's URL, C shares B's platform), works, candidates."""

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
        for native in ("4001", "4002", "4003"):
            c.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform, native),
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
                for native in ("4001", "4002", "4003")
            )
        }
        for native in ("4001", "4002"):
            c.execute(
                """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                                  media_type, role, observed_at)
                   VALUES (?, ?, 0, 'image', 'original', '2026-01-01T00:00:00Z')""",
                (ids[native], f"danbooru:{native}:0"),
            )
        # A platform reference so one candidate can carry a target-reference-only
        # endpoint (no catalog post behind it).
        c.execute(
            """INSERT INTO platform_references (
                   platform_id, object_kind, identifier_kind, native_identifier,
                   canonical_target_url, recognizer_name, recognizer_version
               ) VALUES (?, 'post', 'stable_id', '9999',
                         'https://danbooru.donmai.us/posts/9999',
                         'test-recognizer', 'v1')""",
            (platform,),
        )
        reference = int(
            c.execute("SELECT platform_reference_id FROM platform_references").fetchone()[0]
        )
        candidates = {
            # name: (kind, state, target) -- subject is always post 4002
            "repost_confirmed": ("repost_of", "confirmed", ids["4001"]),
            "same_work_confirmed": ("same_work", "confirmed", ids["4001"]),
            "sourced_pending": ("sourced_from", "pending", ids["4001"]),
            "repost_rejected": ("repost_of", "rejected", ids["4001"]),
            "unresolved": ("unresolved", "confirmed", ids["4001"]),
            "target_reference": ("sourced_from", "confirmed", None),
            # same_work toward post 4003, which has no occurrences and thus no
            # work anchor after materialize_works.
            "anchor_missing": ("same_work", "confirmed", ids["4003"]),
        }
        candidate_ids: dict[str, int] = {}
        for index, (name, (kind, state, target)) in enumerate(candidates.items()):
            c.execute(
                """INSERT INTO post_match_candidates (
                       candidate_key, subject_post_id, target_post_id, target_reference_id,
                       relation_kind, current_state, score, score_version, created_at,
                       updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 5, 'test-v1', ?, ?)""",
                (
                    f"{index:064x}",
                    ids["4002"],
                    target,
                    reference if target is None else None,
                    kind,
                    state,
                    NOW,
                    NOW,
                ),
            )
            candidate_ids[name] = int(
                c.execute(
                    "SELECT post_candidate_id FROM post_match_candidates WHERE candidate_key = ?",
                    (f"{index:064x}",),
                ).fetchone()[0]
            )
        c.execute(
            """INSERT INTO match_evidence (evidence_digest, stance, evidence_kind,
                   direction, strength, detector, detector_version, observed_at,
                   explanation, components_json)
               VALUES (?, 'supports', 'official_link', 'subject_to_target', 'strong',
                       'test-detector', 'v1', ?, 'cites the target', '{}')""",
            ("e" * 64, NOW),
        )
        evidence = int(c.execute("SELECT evidence_id FROM match_evidence").fetchone()[0])
        for candidate_id in candidate_ids.values():
            c.execute(
                "INSERT INTO post_candidate_evidence VALUES (?, ?)",
                (candidate_id, evidence),
            )
        # An account candidate: out of scope, must never be touched.
        c.execute(
            """INSERT INTO accounts (platform_id, native_account_id, first_seen_at,
                                     last_seen_at)
               VALUES (?, 'subject-account', '2026-01-01T00:00:00Z',
                       '2026-01-01T00:00:00Z')""",
            (platform,),
        )
        c.execute(
            """INSERT INTO platform_references (
                   platform_id, object_kind, identifier_kind, native_identifier,
                   canonical_target_url, recognizer_name, recognizer_version
               ) VALUES (?, 'account', 'stable_id', 'artist-elsewhere',
                         'https://danbooru.donmai.us/users/9999',
                         'test-recognizer', 'v1')""",
            (platform,),
        )
        account_reference = int(
            c.execute(
                "SELECT platform_reference_id FROM platform_references "
                "WHERE object_kind = 'account'"
            ).fetchone()[0]
        )
        c.execute(
            """INSERT INTO account_match_candidates (
                   candidate_key, subject_account_id, target_account_id, target_reference_id,
                   relation_kind, current_state, score, score_version, created_at,
                   updated_at
               ) VALUES (?, 1, NULL, ?, 'same_identity', 'pending', 0, 'test-v1', ?, ?)""",
            ("f" * 64, account_reference, NOW, NOW),
        )
        database.connection.commit()
        return {**ids, **candidate_ids, "evidence": evidence}


def _snapshot(c) -> str:
    return repr(
        sorted(
            tuple(str(value) for value in row)
            for row in c.execute("SELECT * FROM post_match_candidates")
        )
        + sorted(
            tuple(str(value) for value in row)
            for row in c.execute("SELECT * FROM post_candidate_evidence")
        )
        + sorted(
            tuple(str(value) for value in row)
            for row in c.execute("SELECT * FROM post_candidate_decisions")
        )
    )


def test_confirmed_candidates_materialize_with_provenance(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    ids = _seed(catalog)
    with CatalogDatabase(catalog) as database:
        materialize_works(database, clock=lambda: NOW)
        before = _snapshot(database.connection)
        result = materialize_candidates(database, clock=lambda: NOW)

    by_candidate = {item["candidate_id"]: item for item in result["results"]}
    repost = by_candidate[ids["repost_confirmed"]]
    assert repost["outcome"] == "materialized"
    same_work = by_candidate[ids["same_work_confirmed"]]
    assert same_work["outcome"] == "materialized"
    assert by_candidate[ids["sourced_pending"]] == {
        "candidate_id": ids["sourced_pending"],
        "outcome": "refused",
        "reason": "candidate_not_confirmed",
    }
    assert by_candidate[ids["repost_rejected"]]["reason"] == "candidate_not_confirmed"
    assert by_candidate[ids["unresolved"]]["reason"] == "unresolved_relation_kind"
    assert by_candidate[ids["target_reference"]]["reason"] == "target_reference_unresolved"
    assert by_candidate[ids["anchor_missing"]]["reason"] == "work_anchor_missing"
    assert result["counts"] == {"materialized": 2, "refused": 5}

    with CatalogDatabase(catalog) as database:
        c = database.connection
        repost_row = c.execute(
            """SELECT relation_kind, epistemic_status, review_state, subject_id, target_id
                 FROM relationships WHERE relationship_id = ?""",
            (repost["relationship_id"],),
        ).fetchone()
        assert tuple(repost_row)[:3] == ("reposted_from", "reviewed", "confirmed")
        assert (repost_row["subject_id"], repost_row["target_id"]) == (
            ids["4002"],
            ids["4001"],
        )
        work_row = c.execute(
            """SELECT relation_kind, subject_kind, target_kind, epistemic_status
                 FROM relationships WHERE relationship_id = ?""",
            (same_work["relationship_id"],),
        ).fetchone()
        assert tuple(work_row) == ("same_work", "work", "work", "reviewed")
        decision = c.execute(
            "SELECT decision, note FROM relationship_review_decisions WHERE relationship_id = ?",
            (repost["relationship_id"],),
        ).fetchone()
        assert decision["decision"] == "confirmed"
        assert f"post:{ids['repost_confirmed']}" in decision["note"]
        evidence_links = c.execute(
            "SELECT COUNT(*) FROM relationship_evidence WHERE relationship_id = ?",
            (repost["relationship_id"],),
        ).fetchone()[0]
        assert evidence_links == 1
        # The candidate side is untouched.
        assert _snapshot(c) == before


def test_rematerialization_is_idempotent_with_evidence_top_up(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    ids = _seed(catalog)
    with CatalogDatabase(catalog) as database:
        materialize_works(database, clock=lambda: NOW)
        first = materialize_candidates(database, clock=lambda: NOW)
        repost = next(
            item for item in first["results"] if item["candidate_id"] == ids["repost_confirmed"]
        )
        rows_before = database.connection.execute(
            """SELECT (SELECT COUNT(*) FROM relationships),
                      (SELECT COUNT(*) FROM relationship_review_decisions),
                      (SELECT COUNT(*) FROM relationship_evidence)"""
        ).fetchone()

        # New evidence lands on the candidate after the first materialization.
        database.connection.execute(
            """INSERT INTO match_evidence (evidence_digest, stance, evidence_kind,
                   direction, strength, detector, detector_version, observed_at,
                   explanation, components_json)
               VALUES (?, 'neutral', 'official_link', 'symmetric', 'weak',
                       'test-detector', 'v2', ?, 'later observation', '{}')""",
            ("d" * 64, NOW),
        )
        later_evidence = int(
            database.connection.execute(
                "SELECT evidence_id FROM match_evidence WHERE evidence_digest = ?",
                ("d" * 64,),
            ).fetchone()[0]
        )
        database.connection.execute(
            "INSERT INTO post_candidate_evidence VALUES (?, ?)",
            (ids["repost_confirmed"], later_evidence),
        )
        database.connection.commit()

        again = materialize_candidates(database, clock=lambda: NOW)
        c = database.connection
        rows_after = c.execute(
            """SELECT (SELECT COUNT(*) FROM relationships),
                      (SELECT COUNT(*) FROM relationship_review_decisions),
                      (SELECT COUNT(*) FROM relationship_evidence)"""
        ).fetchone()
    second = next(
        item for item in again["results"] if item["candidate_id"] == ids["repost_confirmed"]
    )
    assert second["outcome"] == "existing"
    assert second["relationship_id"] == repost["relationship_id"]
    assert again["counts"] == {"existing": 2, "refused": 5}
    assert tuple(rows_after)[:2] == tuple(rows_before)[:2]
    assert rows_after[2] == rows_before[2] + 1  # only the evidence top-up
    assert again["counts"]["existing"] == 2


def test_cli_materializes_one_candidate_offline(tmp_path: Path, capsys, monkeypatch) -> None:
    from media_catalog.cli import main

    catalog = tmp_path / "catalog.sqlite3"
    ids = _seed(catalog)
    with CatalogDatabase(catalog) as database:
        materialize_works(database, clock=lambda: NOW)

    monkeypatch.chdir(tmp_path)

    def fail_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    socket_default = socket.socket.connect
    socket.socket.connect = fail_connect
    try:
        main(
            [
                "relationships",
                "materialize",
                str(catalog),
                "--candidate",
                f"post:{ids['repost_confirmed']}",
                "--json",
            ]
        )
        executed = json.loads(capsys.readouterr().out)
    finally:
        socket.socket.connect = socket_default
    assert executed["counts"] == {"materialized": 1}
    with CatalogDatabase(catalog) as database:
        assert database.connection.execute("SELECT COUNT(*) FROM relationships").fetchone()[0] == 1


def test_materialization_reviews_a_seeded_relationship(tmp_path: Path) -> None:
    """A confirmed candidate upgrades an existing observed relationship.

    Review regression from the subagent audit: materializing onto a seeded
    (observed, pending) relationship must record the decision and move the
    status to reviewed -- not silently report "existing" unreviewed.
    """

    from media_catalog.records import RelationshipRecord
    from media_catalog.writer import CatalogWriter

    catalog = tmp_path / "catalog.sqlite3"
    ids = _seed(catalog)
    with CatalogDatabase(catalog) as database:
        writer = CatalogWriter(database)
        seeded = writer.insert_relationship(
            RelationshipRecord(
                subject_kind="post",
                subject_id=ids["4002"],
                relation_kind="reposted_from",
                target_kind="post",
                target_id=ids["4001"],
                epistemic_status="observed",
                created_at=NOW,
            )
        )
        assert seeded.outcome == "inserted"
        database.connection.commit()
        result = materialize_candidates(
            database, candidate_id=ids["repost_confirmed"], clock=lambda: NOW
        )
        assert result["counts"] == {"existing": 1}
        row = database.connection.execute(
            "SELECT epistemic_status, review_state FROM relationships WHERE relationship_id = ?",
            (seeded.id,),
        ).fetchone()
        decisions = database.connection.execute(
            "SELECT decision, note FROM relationship_review_decisions WHERE relationship_id = ?",
            (seeded.id,),
        ).fetchall()
        history = database.connection.execute(
            "SELECT prior_status, new_status FROM relationship_status_history "
            "WHERE relationship_id = ?",
            (seeded.id,),
        ).fetchall()
    assert (row["epistemic_status"], row["review_state"]) == ("reviewed", "confirmed")
    assert [d["decision"] for d in decisions] == ["confirmed"]
    assert [(h["prior_status"], h["new_status"]) for h in history] == [("observed", "reviewed")]


def test_cli_unknown_candidate_is_an_error(tmp_path: Path, capsys) -> None:
    from media_catalog.cli import main

    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    with pytest.raises(SystemExit) as exit_info:
        main(["relationships", "materialize", str(catalog), "--candidate", "post:999", "--json"])
    # The error payload is the SystemExit code (rendered to stderr by the CLI).
    assert "not found" in str(exit_info.value.code)
    assert exit_info.value.code not in (0, None)
