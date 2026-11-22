"""Calibrated candidate-scoring policy (bead data-processing-vo8, change
``add-calibrated-scoring-policy``): per-family weights from operator label
rates, negative same-artist weight, correlated-field compounding."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from media_catalog import scoring
from media_catalog.database import CatalogDatabase
from media_catalog.scoring import score_candidate_evidence, score_evidence


def test_same_artist_overlap_alone_scores_negative() -> None:
    score, components = score_evidence(
        [{"evidence_kind": "same_artist_overlap", "strength": "weak"}]
    )
    assert score < 0
    family = components["families"]["same_artist_overlap"]
    assert family["labels"] == 54
    assert family["rate"] == pytest.approx(3 / 56, abs=1e-4)
    assert family["ci95"][0] < family["rate"] < family["ci95"][1]
    assert components["policy_version"] == scoring.SCORING_POLICY_VERSION


def test_unmapped_kinds_keep_v1_behavior() -> None:
    assert score_evidence([{"evidence_kind": "official_link", "strength": "strong"}])[0] == 70
    assert score_evidence([{"evidence_kind": "manual_assessment", "strength": "exact"}])[0] == 100


def test_calibrated_family_outranks_raw_strength() -> None:
    # Same tier, different families: calibration, not raw strength, orders them.
    source = score_evidence([{"evidence_kind": "provider_source_reference", "strength": "weak"}])[0]
    exact = score_evidence([{"evidence_kind": "verified_exact_hash", "strength": "weak"}])[0]
    artist = score_evidence([{"evidence_kind": "same_artist_overlap", "strength": "weak"}])[0]
    assert exact > source > artist


def test_correlated_positives_compound_never_sum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scoring,
        "CORRELATED_GROUPS",
        (frozenset({"provider_source_reference", "verified_exact_hash"}),),
    )
    rows = [
        {"evidence_kind": "provider_source_reference", "strength": "strong"},
        {"evidence_kind": "verified_exact_hash", "strength": "exact"},
    ]
    score, components = score_evidence(rows)
    plain = sum(
        scoring.STRENGTH_SCORES[
            "exact" if r["evidence_kind"] == "verified_exact_hash" else "strong"
        ]
        * (
            scoring.family_calibration(scoring.KIND_FAMILY[r["evidence_kind"]]).factor
            if r["evidence_kind"] in scoring.KIND_FAMILY
            else 1.0
        )
        for r in rows
    )
    assert score < round(plain)
    assert components["compounds"] == [
        {
            "group": ["provider_source_reference", "verified_exact_hash"],
            "compound": components["compounds"][0]["compound"],
        }
    ]


def test_negative_artist_discount_never_inflates_source_evidence() -> None:
    source_alone = score_evidence(
        [{"evidence_kind": "provider_source_reference", "strength": "strong"}]
    )[0]
    artist_alone = score_evidence([{"evidence_kind": "same_artist_overlap", "strength": "weak"}])[0]
    mixed = score_evidence(
        [
            {"evidence_kind": "provider_source_reference", "strength": "strong"},
            {"evidence_kind": "same_artist_overlap", "strength": "weak"},
        ]
    )[0]
    assert artist_alone < 0
    assert mixed == source_alone + artist_alone
    assert mixed < source_alone


def test_score_is_deterministic() -> None:
    rows = [
        {"evidence_kind": "verified_exact_hash", "strength": "exact"},
        {"evidence_kind": "same_artist_overlap", "strength": "weak"},
    ]
    assert score_evidence(rows) == score_evidence(rows)


def _seed_two_posts_with_shared_artist(catalog: Path) -> tuple[int, int]:
    with CatalogDatabase(catalog) as database, database.transaction():
        connection = database.connection
        connection.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name)"
            " VALUES ('danbooru', 'danbooru')"
        )
        platform_id = int(
            connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
            ).fetchone()[0]
        )
        ids: list[int] = []
        for native in ("probe-a", "probe-b"):
            connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, availability,
                                          first_seen_at, last_seen_at)
                   VALUES (?, ?, 'available', '2026-01-01T00:00:00Z',
                           '2026-01-01T00:00:00Z')""",
                (platform_id, native),
            )
            ids.append(int(connection.execute("SELECT last_insert_rowid()").fetchone()[0]))
        connection.execute(
            """INSERT OR IGNORE INTO tags (platform_id, name, category,
                                            normalization_version, created_at)
               VALUES (?, 'shared_artist', 'artist', 'seed-v1',
                       '2026-01-01T00:00:00Z')""",
            (platform_id,),
        )
        tag_id = int(
            connection.execute("SELECT tag_id FROM tags WHERE name = 'shared_artist'").fetchone()[0]
        )
        for post_id in ids:
            connection.execute(
                "INSERT INTO post_tags (post_id, tag_id, first_seen_at, last_seen_at)"
                " VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
                (post_id, tag_id),
            )
    return ids[0], ids[1]


def test_interpreter_attaches_negative_artist_evidence(tmp_path: Path) -> None:
    """The same_artist_overlap producer + calibrated policy land a negative
    contribution on a real candidate (vo8 acceptance)."""

    from media_catalog.adapters import LookupStrategy, NormalizedLookupResult
    from media_catalog.candidate_lookup.interpretation import LookupInterpreter

    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass
    seed_id, _target_id = _seed_two_posts_with_shared_artist(catalog)
    result = NormalizedLookupResult(
        "post",
        "probe-b",
        {
            "platform": "danbooru",
            "post_id": "probe-b",
            "canonical_url": "https://danbooru.donmai.us/posts/probe-b",
            "query_kind": "declared_md5",
            "query": "0" * 32,
            "source": None,
            "declared_md5": "0" * 32,
        },
        0,
        (),
    )
    with CatalogDatabase(catalog) as database:
        interpreter = LookupInterpreter(database.connection)
        interpreted = interpreter.interpret(
            result,
            seed_post_id=seed_id,
            seed_account_id=None,
            strategy=LookupStrategy.DECLARED_MD5,
            raw_observation_id=1,
            observed_at="2026-01-01T00:00:00Z",
            seed_material_digest="0" * 64,
            query_values=("0" * 32,),
        )
        candidate_id = interpreted.post_candidate_id
        assert candidate_id is not None
        row = database.connection.execute(
            """SELECT score, score_components_json FROM post_match_candidates
                WHERE post_candidate_id = ?""",
            (candidate_id,),
        ).fetchone()
        import json as _json

        components = _json.loads(row[1])
        kinds = {kind for kind, entry in components["families"].items() if entry["count"] > 0}
        # declared_hash (unmapped, +35) plus same_artist_overlap (negative)
        assert "same_artist_overlap" in kinds
        assert components["families"]["same_artist_overlap"]["contribution"] < 0
        assert row[0] < 35  # artist agreement never raises the candidate


def test_score_candidate_evidence_reads_supports_rows(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        connection = database.connection
        connection.execute(
            """INSERT INTO match_evidence (evidence_digest, stance, evidence_kind,
                    direction, strength, detector, detector_version, observed_at,
                    explanation, components_json)
               VALUES (?, 'supports', 'same_artist_overlap', 'symmetric', 'weak',
                       'test', 't-v1', '2026-01-01T00:00:00Z', '', '{}'),
                      (?, 'contradicts', 'declared_hash', 'symmetric', 'moderate',
                       'test', 't-v1', '2026-01-01T00:00:00Z', '', '{}')""",
            ("e" * 64, "f" * 64),
        )
        connection.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name)"
            " VALUES ('danbooru', 'danbooru')"
        )
        platform_id = int(
            connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'danbooru'"
            ).fetchone()[0]
        )
        for native in ("fk-a", "fk-b"):
            connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, availability,
                                          first_seen_at, last_seen_at)
                   VALUES (?, ?, 'available', '2026-01-01T00:00:00Z',
                           '2026-01-01T00:00:00Z')""",
                (platform_id, native),
            )
        connection.execute(
            """INSERT INTO post_match_candidates (candidate_key, relation_kind,
                    subject_post_id, target_post_id, score, score_version,
                    created_at, updated_at)
               VALUES (?, 'same_work', 1, 2, 0, 'test-v1',
                       '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            ("k" * 64,),
        )
        connection.execute(
            "INSERT INTO post_candidate_evidence (post_candidate_id, evidence_id)"
            " VALUES (1, 1), (1, 2)"
        )
        score, components, generation = score_candidate_evidence(
            connection, "post_candidate_evidence", "post_candidate_id", 1
        )
    assert score < 0  # only the supports row counts, and it is negative
    assert generation == 1
    assert "same_artist_overlap" in components
    assert isinstance(sqlite3.connect(":memory:"), sqlite3.Connection)  # sanity
