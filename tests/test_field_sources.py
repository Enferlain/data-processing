"""Post-field-sources projection tests (OpenSpec per-field-source-export).

Every observed field carries its complete retained value history; the newest
observation wins the current value under the stated policy; nulls never erase;
posts without retained observations and limit overflow are excluded with
counted reasons; the projection is read-only and digest-reproducible.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.projections import plan_export, run_export
from media_catalog.projections.output import parse_jsonl
from media_catalog.records import PostMetadataObservationRecord
from media_catalog.writer import CatalogWriter

NOW = "2026-10-21T00:00:00Z"


def _seed(catalog: Path) -> dict[str, int]:
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
        ids: dict[str, int] = {}
        for native in ("6001", "6002", "6003"):
            c.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform, native),
            )
            ids[native] = int(
                c.execute(
                    "SELECT post_id FROM posts WHERE native_post_id = ?", (native,)
                ).fetchone()[0]
            )
        # One retained raw observation so a history entry can carry a pointer.
        c.execute(
            "INSERT INTO raw_payloads (payload, sha256, byte_size, media_type) "
            "VALUES (x'7b7d', ?, 2, 'application/json')",
            ("a" * 64,),
        )
        payload = int(c.execute("SELECT raw_payload_id FROM raw_payloads").fetchone()[0])
        c.execute(
            """INSERT INTO raw_observations (platform_id, object_kind, native_id,
                   media_type, observed_at, adapter_version, schema_version, status,
                   raw_payload_id)
               VALUES (?, 'post', '6001', 'application/json', '2026-02-01T00:00:00Z',
                       'test-v1', 'test-v1', 200, ?)""",
            (platform, payload),
        )
        raw = int(c.execute("SELECT raw_observation_id FROM raw_observations").fetchone()[0])
        # Post 6001: favorite_count observed three times (two distinct values),
        # score_total once, then an observation asserting only flags -- its null
        # favorite_count must not erase the retained history.
        writer = CatalogWriter(database)
        for observed_at, favorite, score, raw_id in (
            ("2026-01-01T00:00:00Z", 5, 11, None),
            ("2026-02-01T00:00:00Z", 7, None, raw),
            ("2026-03-01T00:00:00Z", None, None, None),
        ):
            writer.record_post_metadata(
                ids["6001"],
                PostMetadataObservationRecord(
                    observed_at=observed_at,
                    score_total=score,
                    favorite_count=favorite,
                    flag_deleted=True,
                ),
                raw_observation_id=raw_id,
            )
        # Post 6002: one observation, so limit tests have two observed posts.
        writer.record_post_metadata(
            ids["6002"],
            PostMetadataObservationRecord(observed_at="2026-01-01T00:00:00Z", comment_count=3),
        )
        # Post 6003: no retained observations at all.
        database.connection.commit()
        return ids


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_field_history_retains_dissent_and_marks_the_newest(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    result = run_export(
        catalog, kind="post-field-sources", out_dir=tmp_path / "out", clock=lambda: NOW
    )
    rows = parse_jsonl(tmp_path / "out" / "post-field-sources-projection.jsonl")
    assert result["counts"]["included"] == 2
    anchor = next(row for row in rows if row["native_post_id"] == "6001")
    by_field = {field["field"]: field for field in anchor["fields"]}
    favorite = by_field["favorite_count"]
    # Both dissenting values retained, oldest first; the newest wins current.
    assert [entry["value"] for entry in favorite["entries"]] == [5, 7]
    assert favorite["current"] == favorite["entries"][1]
    assert favorite["current"]["raw_observation_id"] is not None
    # The March observation asserted only a flag: no null entry for favorite_count,
    # no erasure -- the flag lands instead.
    assert len(favorite["entries"]) == 2
    assert by_field["flag_deleted"]["entries"][0]["value"] is True
    assert by_field["score_total"]["entries"] == [
        {
            "value": 11,
            "observed_at": "2026-01-01T00:00:00Z",
            "raw_observation_id": None,
        }
    ]
    # Fields never observed do not appear.
    assert "comment_count" not in by_field


def test_exclusions_digests_and_read_only(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)  # fixture only; this test reads through the projection
    plan = plan_export(catalog, kind="post-field-sources")
    assert plan["counts"] == {
        "included": 2,
        "excluded": [{"reason": "no_retained_observations", "count": 1}],
    }
    limited = plan_export(catalog, kind="post-field-sources", limit=1)
    assert limited["counts"]["excluded"] == [
        {"reason": "no_retained_observations", "count": 1},
        {"reason": "excluded_by_limit", "count": 1},
    ]
    before = _file_sha(catalog)
    first = run_export(
        catalog, kind="post-field-sources", out_dir=tmp_path / "one", clock=lambda: NOW
    )
    second = run_export(
        catalog, kind="post-field-sources", out_dir=tmp_path / "two", clock=lambda: NOW
    )
    assert _file_sha(catalog) == before
    assert first["spec_digest"] == second["spec_digest"]
    assert first["selection_digest"] == second["selection_digest"]
    assert first["policies"]["field_source"] == (
        "newest_observation_wins_per_field_all_values_retained"
    )


def test_as_of_reconstructs_under_a_cutoff(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)  # favorite_count observed Jan (5) and Feb (7); flags in March

    between = run_export(
        catalog,
        kind="post-field-sources",
        out_dir=tmp_path / "between",
        as_of="2026-01-15T00:00:00Z",
        clock=lambda: NOW,
    )
    rows = parse_jsonl(tmp_path / "between" / "post-field-sources-projection.jsonl")
    anchor = next(row for row in rows if row["native_post_id"] == "6001")
    favorite = next(f for f in anchor["fields"] if f["field"] == "favorite_count")
    # Only the January observation exists at the cutoff; its value is current.
    assert [entry["value"] for entry in favorite["entries"]] == [5]
    assert favorite["current"]["value"] == 5
    assert between["as_of"] == "2026-01-15T00:00:00Z"
    # flag_deleted is asserted by every observation in the fixture, so at the
    # cutoff it exists with exactly the January entry (one of three).
    flags = next(f for f in anchor["fields"] if f["field"] == "flag_deleted")
    assert len(flags["entries"]) == 1

    after_all = run_export(
        catalog,
        kind="post-field-sources",
        out_dir=tmp_path / "after",
        as_of="2027-01-01T00:00:00Z",
        clock=lambda: NOW,
    )
    uncutoff = run_export(
        catalog,
        kind="post-field-sources",
        out_dir=tmp_path / "uncut",
        clock=lambda: NOW,
    )
    # Same rows under both; different recipes (the cutoff participates in the
    # digest), identical data content.
    assert after_all["spec_digest"] != uncutoff["spec_digest"]
    assert uncutoff["as_of"] == "all_retained"
    after_files = {f["name"]: f["content_digest"] for f in after_all["files"]}
    uncut_files = {f["name"]: f["content_digest"] for f in uncutoff["files"]}
    assert after_files == uncut_files

    before_all = plan_export(catalog, kind="post-field-sources", as_of="2025-01-01T00:00:00Z")
    assert before_all["counts"] == {
        "included": 0,
        "excluded": [{"reason": "no_retained_observations", "count": 3}],
    }
    # Cutoffs are refused for kinds without as-of semantics, and malformed
    # cutoffs are refused outright.
    with pytest.raises(ValueError, match="does not support an as-of cutoff"):
        plan_export(catalog, kind="posts", as_of="2026-01-15T00:00:00Z")
    # A bare date parses as a datetime but lacks the timezone: refused.
    with pytest.raises(ValueError, match="timezone"):
        run_export(
            catalog,
            kind="post-field-sources",
            out_dir=tmp_path / "bad",
            as_of="2026-01-15",
            clock=lambda: NOW,
        )
    # An impossible calendar date is refused by parsing.
    with pytest.raises(ValueError, match="ISO-8601"):
        run_export(
            catalog,
            kind="post-field-sources",
            out_dir=tmp_path / "bad2",
            as_of="2026-02-30T00:00:00Z",
            clock=lambda: NOW,
        )


def test_as_of_boundary_handles_fractional_seconds(tmp_path: Path) -> None:
    """Review regression: fractional seconds inside the cutoff second.

    Lexicographic comparison would place ".4s after a whole-second cutoff"
    before the cutoff ("." < "Z"); the parsed comparison must exclude it, and
    an observation exactly at the cutoff must be included.
    """

    from media_catalog.records import PostMetadataObservationRecord
    from media_catalog.writer import CatalogWriter

    catalog = tmp_path / "catalog.sqlite3"
    ids = _seed(catalog)
    with CatalogDatabase(catalog) as database:
        CatalogWriter(database).record_post_metadata(
            ids["6001"],
            PostMetadataObservationRecord(
                observed_at="2026-01-01T00:00:00.400000Z", favorite_count=9
            ),
        )
        database.connection.commit()

    run_export(
        catalog,
        kind="post-field-sources",
        out_dir=tmp_path / "whole",
        as_of="2026-01-01T00:00:00Z",
        clock=lambda: NOW,
    )
    rows = parse_jsonl(tmp_path / "whole" / "post-field-sources-projection.jsonl")
    anchor = next(row for row in rows if row["native_post_id"] == "6001")
    favorite = next(f for f in anchor["fields"] if f["field"] == "favorite_count")
    # The .4s observation is after the whole-second cutoff: excluded, even
    # though it sorts before the cutoff string lexicographically. The exact
    # whole-second observation at the cutoff is included.
    assert [entry["value"] for entry in favorite["entries"]] == [5]
    assert favorite["current"]["value"] == 5

    fractional = run_export(
        catalog,
        kind="post-field-sources",
        out_dir=tmp_path / "frac",
        as_of="2026-01-01T00:00:00.400000Z",
        clock=lambda: NOW,
    )
    rows = parse_jsonl(tmp_path / "frac" / "post-field-sources-projection.jsonl")
    anchor = next(row for row in rows if row["native_post_id"] == "6001")
    favorite = next(f for f in anchor["fields"] if f["field"] == "favorite_count")
    # At the fractional cutoff both January observations exist, in observation
    # order, with the newest (the .4s one) current.
    assert [entry["value"] for entry in favorite["entries"]] == [5, 9]
    assert favorite["current"]["value"] == 9
    assert fractional["as_of"] == "2026-01-01T00:00:00.400000Z"
