"""Attribution-disagreement projection tests (OpenSpec attribution-disagreement-report).

One row per linked post pair whose artist attributions no confirmed identity
joins; participants and tag-implied attribution entities both count; a
confirmed identity join, missing end attribution, rejected relationships, and
the row limit are excluded with counted reasons; the projection is offline,
read-only, and digest-reproducible.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from media_catalog.database import CatalogDatabase
from media_catalog.projections import plan_export, run_export
from media_catalog.projections.output import parse_jsonl
from media_catalog.records import RelationshipRecord
from media_catalog.writer import CatalogWriter

NOW = "2026-10-21T00:00:00Z"


def _seed(catalog: Path) -> dict[str, int]:
    """Two danbooru posts, artist participants, one reposted_from link."""

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
        # A third platform so one attribution can come from elsewhere.
        c.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name) "
            "VALUES ('aibooru', 'AIBooru')"
        )
        other_platform = int(
            c.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = 'aibooru'"
            ).fetchone()[0]
        )
        ids: dict[str, int] = {"platform": platform, "other_platform": other_platform}
        for native in ("5001", "5002"):
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
        # Artist accounts: the original's artist on danbooru, the repost's
        # attributed account imported from the X archive (same platform row is
        # fine; native ids differ).
        for native, post in (("artist-original", "5001"), ("artist-repost", "5002")):
            c.execute(
                """INSERT INTO accounts (platform_id, native_account_id, first_seen_at,
                                         last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform, native),
            )
            ids[native] = int(
                c.execute(
                    "SELECT account_id FROM accounts WHERE native_account_id = ?",
                    (native,),
                ).fetchone()[0]
            )
            c.execute(
                "INSERT INTO account_snapshots (account_id, observed_at, handle, "
                "snapshot_digest) VALUES (?, '2026-01-01T00:00:00Z', ?, ?)",
                (ids[native], native, hashlib.sha256(native.encode()).hexdigest()),
            )
            c.execute(
                "INSERT INTO post_participants (post_id, account_id, role, review_state) "
                "VALUES (?, ?, 'artist', 'observed')",
                (ids[post], ids[native]),
            )
        # A tag-implied attribution entity on the repost end: an attribution
        # entity linked to a tag the repost carries. Primary name collides with
        # the original side's participant name -> exercises the name hint.
        c.execute(
            """INSERT INTO tags (platform_id, category, name, normalization_version)
               VALUES (?, 'artist', 'artist-original', 'tag-norm-v1')""",
            (platform,),
        )
        tag = int(c.execute("SELECT tag_id FROM tags").fetchone()[0])
        c.execute(
            "INSERT INTO post_tags (post_id, tag_id, first_seen_at, last_seen_at) "
            "VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (ids["5002"], tag),
        )
        c.execute(
            """INSERT INTO attribution_entities (platform_id, provider_attribution_id,
                                                  adapter_version, first_seen_at, last_seen_at)
               VALUES (?, 'artist-entity-1', 'test-v1', '2026-01-01T00:00:00Z',
                       '2026-01-01T00:00:00Z')""",
            (platform,),
        )
        entity = int(
            c.execute("SELECT attribution_entity_id FROM attribution_entities").fetchone()[0]
        )
        c.execute(
            "INSERT INTO attribution_names (attribution_entity_id, name, name_kind, "
            "observed_at) VALUES (?, 'artist-original', 'primary', "
            "'2026-01-01T00:00:00Z')",
            (entity,),
        )
        c.execute(
            "INSERT INTO attribution_tag_links (attribution_entity_id, tag_id, observed_at) "
            "VALUES (?, ?, '2026-01-01T00:00:00Z')",
            (entity, tag),
        )
        database.connection.commit()
        return ids


def _link(catalog: Path, *, rejected: bool = False) -> int:
    ids_recorded = _read_ids(catalog)
    with CatalogDatabase(catalog) as database:
        writer = CatalogWriter(database)
        result = writer.insert_relationship(
            RelationshipRecord(
                subject_kind="post",
                subject_id=ids_recorded["5002"],
                relation_kind="reposted_from",
                target_kind="post",
                target_id=ids_recorded["5001"],
                epistemic_status="observed",
                created_at=NOW,
            )
        )
        if rejected:
            writer.record_relationship_review(
                result.id, decision="rejected", decided_at=NOW, note="test"
            )
        database.connection.commit()
        return result.id


def _read_ids(catalog: Path) -> dict[str, int]:
    with CatalogDatabase.open_read_only(catalog) as database:
        return {
            "5001": int(
                database.connection.execute(
                    "SELECT post_id FROM posts WHERE native_post_id = '5001'"
                ).fetchone()[0]
            ),
            "5002": int(
                database.connection.execute(
                    "SELECT post_id FROM posts WHERE native_post_id = '5002'"
                ).fetchone()[0]
            ),
            "artist-original": int(
                database.connection.execute(
                    "SELECT account_id FROM accounts WHERE native_account_id = 'artist-original'"
                ).fetchone()[0]
            ),
            "artist-repost": int(
                database.connection.execute(
                    "SELECT account_id FROM accounts WHERE native_account_id = 'artist-repost'"
                ).fetchone()[0]
            ),
        }


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_unjoined_attributions_surface_as_one_row(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    ids = _seed(catalog)
    relationship_id = _link(catalog)
    result = run_export(
        catalog,
        kind="attribution-disagreements",
        out_dir=tmp_path / "out",
        clock=lambda: NOW,
    )
    rows = parse_jsonl(tmp_path / "out" / "attribution-disagreements-projection.jsonl")
    assert result["counts"]["included"] == 1
    assert len(rows) == 1
    row = rows[0]
    assert row["relationship_id"] == relationship_id
    assert row["relation_kind"] == "reposted_from"
    assert row["epistemic_status"] == "observed"
    assert row["subject"]["post_id"] == ids["5002"]
    subject_identities = {
        (i["identity_kind"], i["native_id"]) for i in row["subject"]["attribution"]
    }
    assert subject_identities == {
        ("participant", "artist-repost"),
        ("attribution_entity", "artist-entity-1"),
    }
    assert row["target"]["attribution"] == [
        {
            "identity_kind": "participant",
            "platform": "danbooru",
            "native_id": "artist-original",
            "primary_name": "artist-original",
            "review_state": "observed",
        }
    ]
    # The tag-implied entity's primary name equals the original participant's
    # handle: the hint fires, weakly.
    assert row["name_match"] is True


def test_confirmed_identity_join_excludes_the_pair(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    _link(catalog)
    ids = _read_ids(catalog)
    with CatalogDatabase(catalog) as database:
        c = database.connection
        c.execute("INSERT INTO identities (created_at) VALUES ('2026-01-01T00:00:00Z')")
        identity = int(c.execute("SELECT identity_id FROM identities").fetchone()[0])
        for account_id in (ids["artist-original"], ids["artist-repost"]):
            c.execute(
                "INSERT INTO identity_accounts (identity_id, account_id, added_at) "
                "VALUES (?, ?, '2026-01-01T00:00:00Z')",
                (identity, account_id),
            )
        database.connection.commit()
    plan = plan_export(catalog, kind="attribution-disagreements")
    assert plan["counts"] == {
        "included": 0,
        "excluded": [{"reason": "confirmed_identity_join", "count": 1}],
    }


def test_missing_attribution_rejected_relationship_and_limit(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    _link(catalog)
    ids = _read_ids(catalog)
    with CatalogDatabase(catalog) as database:
        # Remove the original end's attribution -> missing on one end.
        database.connection.execute(
            "DELETE FROM post_participants WHERE post_id = ?", (ids["5001"],)
        )
        database.connection.commit()
    plan = plan_export(catalog, kind="attribution-disagreements")
    assert plan["counts"]["excluded"] == [{"reason": "attribution_missing_on_end", "count": 1}]

    catalog2 = tmp_path / "rejected.sqlite3"
    ids2 = _seed(catalog2)
    _link(catalog2, rejected=True)
    assert ids2  # fixture ran
    plan2 = plan_export(catalog2, kind="attribution-disagreements")
    assert plan2["counts"]["excluded"] == [{"reason": "rejected_relationship", "count": 1}]

    catalog3 = tmp_path / "limit.sqlite3"
    _seed(catalog3)
    _link(catalog3)
    plan3 = plan_export(catalog3, kind="attribution-disagreements", limit=1)
    assert plan3["counts"] == {"included": 1, "excluded": []}


def test_projection_is_read_only_and_reproducible(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog)
    _link(catalog)
    before = _file_sha(catalog)
    first = run_export(
        catalog, kind="attribution-disagreements", out_dir=tmp_path / "one", clock=lambda: NOW
    )
    second = run_export(
        catalog, kind="attribution-disagreements", out_dir=tmp_path / "two", clock=lambda: NOW
    )
    assert _file_sha(catalog) == before
    assert first["spec_digest"] == second["spec_digest"]
    assert first["selection_digest"] == second["selection_digest"]
    assert {f["content_digest"] for f in first["files"]} == {
        f["content_digest"] for f in second["files"]
    }
    # Manifest states the report-only policy surface.
    assert first["policies"]["field_source"].startswith("participants_and_tag_implied")
