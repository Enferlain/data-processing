"""Evidence-dependence derivation tests (OpenSpec model-evidence-dependence).

Observation count is not independent-corroboration count: the pixiv ->
danbooru -> gelbooru -> archive mirror chain keeps four observations but
resolves to one lineage; byte-identical occurrences merge lineages through
equivalence edges; independent sources stay separate.  Dependence carries
its own uncertainty -- inferred proposals and rejected edges do not merge
under the default policy.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from media_catalog.database import CatalogDatabase
from media_catalog.records import PostMetadataObservationRecord, RelationshipRecord
from media_catalog.relationships import lineage_components, materialize_works, review_relationship
from media_catalog.relationships.seed import seed_relationships
from media_catalog.writer import CatalogWriter

CHAIN = (
    # (platform, native post id) reposted_from the previous entry.
    ("pixiv", "1001"),
    ("danbooru", "2001"),
    ("gelbooru", "3001"),
    ("archive", "4001"),
)
INDEPENDENT = (("pixiv", "1002"), ("danbooru", "2002"))


def _platform(c: object, key: str) -> int:
    c.execute(
        "INSERT OR IGNORE INTO platforms (platform_key, display_name) VALUES (?, ?)",
        (key, key.capitalize()),
    )
    return int(
        c.execute("SELECT platform_id FROM platforms WHERE platform_key = ?", (key,)).fetchone()[0]
    )


def _mirror_chain_fixture(catalog: Path) -> dict[str, int]:
    """The gh#9 mirror chain plus two independent sources asserting the same claim."""

    with CatalogDatabase(catalog) as database:
        c = database.connection
        ids: dict[str, int] = {}
        for platform, native in CHAIN + INDEPENDENT:
            platform_id = _platform(c, platform)
            c.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform_id, native),
            )
            ids[f"{platform}:{native}"] = int(
                c.execute(
                    "SELECT post_id FROM posts WHERE native_post_id = ?", (native,)
                ).fetchone()[0]
            )
            c.execute(
                """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                                  media_type, role, observed_at)
                   VALUES (?, ?, 0, 'image', 'original', '2026-01-01T00:00:00Z')""",
                (ids[f"{platform}:{native}"], f"{platform}:{native}:0"),
            )
        writer = CatalogWriter(database)
        # Every source in the chain and both independent posts observe the same
        # claim (favorite_count 42): six observations, how many lineages?
        for platform, native in CHAIN + INDEPENDENT:
            writer.record_post_metadata(
                ids[f"{platform}:{native}"],
                PostMetadataObservationRecord(
                    observed_at="2026-01-01T00:00:00Z", favorite_count=42
                ),
            )
        # danbooru reposts pixiv, gelbooru reposts danbooru, archive reposts
        # gelbooru -- each edge exactly as the seeder would record it.
        for (platform, native), (origin_platform, origin_native) in zip(
            CHAIN[1:], CHAIN[:-1], strict=True
        ):
            writer.insert_relationship(
                RelationshipRecord(
                    subject_kind="post",
                    subject_id=ids[f"{platform}:{native}"],
                    relation_kind="reposted_from",
                    target_kind="post",
                    target_id=ids[f"{origin_platform}:{origin_native}"],
                    epistemic_status="observed",
                    created_at="2026-01-02T00:00:00Z",
                )
            )
        database.connection.commit()
        return ids


def _chain_post(components: list[dict], key: str) -> dict:
    return next(
        component for component in components if any(key in label for label in component["members"])
    )


def test_mirror_chain_is_one_lineage_of_four_observations(tmp_path: Path) -> None:
    _mirror_chain_fixture(tmp_path / "catalog.sqlite3")
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        components = lineage_components(database)
        observations = int(
            database.connection.execute(
                "SELECT COUNT(*) FROM post_metadata_observations WHERE favorite_count = 42"
            ).fetchone()[0]
        )
    # Six observations retained; the chain is one lineage, the two independent
    # sources are two more: three lineages back the same claimed value.
    assert observations == 6
    chain = _chain_post(components, "post:danbooru:2001")
    assert chain["members"] == [
        "occurrence:1",
        "occurrence:2",
        "occurrence:3",
        "occurrence:4",
        "post:archive:4001",
        "post:danbooru:2001",
        "post:gelbooru:3001",
        "post:pixiv:1001",
    ]
    assert [
        (edge["kind"], edge["subject"], edge["target"]) for edge in chain["dependence_edges"]
    ] == [
        ("reposted_from", "post:archive:4001", "post:gelbooru:3001"),
        ("reposted_from", "post:danbooru:2001", "post:pixiv:1001"),
        ("reposted_from", "post:gelbooru:3001", "post:danbooru:2001"),
    ]
    # The independent sources carry no dependence edges: three components
    # total (the chain plus two unmerged pairs of post and occurrence).
    assert len(components) == 3
    unmerged = {tuple(c["members"]) for c in components if not c["dependence_edges"]}
    assert unmerged == {
        ("occurrence:5", "post:pixiv:1002"),
        ("occurrence:6", "post:danbooru:2002"),
    }


def test_same_bytes_equivalence_merges_without_declared_sources(tmp_path: Path) -> None:
    catalog = tmp_path / "bytes.sqlite3"
    with CatalogDatabase(catalog) as database:
        c = database.connection
        sha = "d" * 64
        c.execute(
            """INSERT INTO assets (verified_sha256, storage_kind, verification_method,
                                   byte_size, verified_at, detected_mime_type)
               VALUES (?, 'managed', 'sha256_adoption', 100,
                       '2026-01-02T00:00:00Z', 'image/jpeg')""",
            (sha,),
        )
        asset_id = int(c.execute("SELECT asset_id FROM assets").fetchone()[0])
        for platform, native in (
            ("pixiv", "5001"),
            ("danbooru", "5002"),
            ("gelbooru", "5003"),
            ("archive", "5004"),
            ("sankaku", "5005"),
        ):
            platform_id = _platform(c, platform)
            c.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform_id, native),
            )
            post_id = int(
                c.execute(
                    "SELECT post_id FROM posts WHERE native_post_id = ?", (native,)
                ).fetchone()[0]
            )
            c.execute(
                """INSERT INTO media_occurrences (post_id, source_key, media_index,
                                                  media_type, role, observed_at)
                   VALUES (?, ?, 0, 'image', 'original', '2026-01-01T00:00:00Z')""",
                (post_id, f"{platform}:{native}:0"),
            )
            c.execute(
                """INSERT INTO occurrence_assets (media_occurrence_id, asset_id,
                                                  relationship, verification_source)
                   VALUES ((SELECT media_occurrence_id FROM media_occurrences
                             WHERE source_key = ?), ?, 'exact_bytes',
                           'byte_verification')""",
                (f"{platform}:{native}:0", asset_id),
            )
        c.commit()
        # The real seeder derives the verified equivalence edges.
        seed_relationships(database, clock=lambda: "2026-01-03T00:00:00Z")
        components = lineage_components(database)
    merged = [component for component in components if len(component["members"]) > 1]
    assert len(merged) == 1
    # Five providers: every pair of occurrences seeds one equivalence edge.
    assert [edge["kind"] for edge in merged[0]["dependence_edges"]] == ["same_bytes"] * 10
    # Five providers, five occurrences, one origin assertion lineage.
    assert sorted(
        m.removeprefix("post:") for m in merged[0]["members"] if m.startswith("post:")
    ) == [
        "archive:5004",
        "danbooru:5002",
        "gelbooru:5003",
        "pixiv:5001",
        "sankaku:5005",
    ]


def test_work_anchors_join_lineages_and_same_work_merges(tmp_path: Path) -> None:
    catalog = tmp_path / "works.sqlite3"
    _mirror_chain_fixture(catalog)
    with CatalogDatabase(catalog) as database:
        materialize_works(database, clock=lambda: "2026-01-05T00:00:00Z")
        c = database.connection
        work_of = {
            native: int(
                c.execute(
                    "SELECT work_id FROM works w JOIN posts p ON p.post_id = w.origin_post_id "
                    "WHERE p.native_post_id = ?",
                    (native,),
                ).fetchone()[0]
            )
            for native in ("1002", "2002")
        }
        # A reviewed same_work conclusion joins the two independent anchors.
        CatalogWriter(database).insert_relationship(
            RelationshipRecord(
                subject_kind="work",
                subject_id=work_of["1002"],
                relation_kind="same_work",
                target_kind="work",
                target_id=work_of["2002"],
                epistemic_status="reviewed",
                created_at="2026-01-06T00:00:00Z",
            )
        )
        c.commit()
        components = lineage_components(database)
    # Every chain post's anchor joins its lineage: the component carries the
    # four works alongside the four posts and occurrences.
    chain = _chain_post(components, "post:danbooru:2001")
    assert [m for m in chain["members"] if m.startswith("work:")] == [
        "work:archive:4001",
        "work:danbooru:2001",
        "work:gelbooru:3001",
        "work:pixiv:1001",
    ]
    # The equivalence edge merges the two previously independent lineages.
    joined = _chain_post(components, "post:pixiv:1002")
    assert sorted(m for m in joined["members"] if m.startswith("post:")) == [
        "post:danbooru:2002",
        "post:pixiv:1002",
    ]
    assert [
        (edge["kind"], edge["subject"], edge["target"]) for edge in joined["dependence_edges"]
    ] == [("same_work", "work:pixiv:1002", "work:danbooru:2002")]


def test_dependence_uncertainty_filters_edges(tmp_path: Path) -> None:
    catalog = tmp_path / "policy.sqlite3"
    with CatalogDatabase(catalog) as database:
        c = database.connection
        ids: dict[str, int] = {}
        for native in ("6001", "6002", "6003"):
            platform_id = _platform(c, "danbooru")
            c.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform_id, native),
            )
            ids[native] = int(
                c.execute(
                    "SELECT post_id FROM posts WHERE native_post_id = ?", (native,)
                ).fetchone()[0]
            )
        writer = CatalogWriter(database)
        proposed = writer.insert_relationship(
            RelationshipRecord(
                subject_kind="post",
                subject_id=ids["6002"],
                relation_kind="reposted_from",
                target_kind="post",
                target_id=ids["6001"],
                epistemic_status="inferred",
                created_at="2026-01-02T00:00:00Z",
            )
        )
        declared = writer.insert_relationship(
            RelationshipRecord(
                subject_kind="post",
                subject_id=ids["6003"],
                relation_kind="reposted_from",
                target_kind="post",
                target_id=ids["6001"],
                epistemic_status="observed",
                created_at="2026-01-02T00:00:00Z",
            )
        )
        c.commit()
        # Default policy: the inferred proposal does not merge; the observed
        # declaration does.
        before = lineage_components(database)
        assert {tuple(component["members"]) for component in before} == {
            ("post:danbooru:6001", "post:danbooru:6003"),
            ("post:danbooru:6002",),
        }
        # Review confirms the proposal: the two sides merge.
        review_relationship(database, proposed.id, "confirm", clock=lambda: "2026-01-04T00:00:00Z")
        confirmed = lineage_components(database)
        assert {tuple(component["members"]) for component in confirmed} == {
            ("post:danbooru:6001", "post:danbooru:6002", "post:danbooru:6003")
        }
        # Review rejects the declared edge: the sides separate again, while the
        # edge and its history remain retained.
        review_relationship(database, declared.id, "reject", clock=lambda: "2026-01-05T00:00:00Z")
        after = lineage_components(database)
        assert {tuple(component["members"]) for component in after} == {
            ("post:danbooru:6001", "post:danbooru:6002"),
            ("post:danbooru:6003",),
        }
        # A surface may still state a policy that counts rejected edges.
        counting_rejected = lineage_components(database, include_rejected=True)
        assert {tuple(component["members"]) for component in counting_rejected} == {
            ("post:danbooru:6001", "post:danbooru:6002", "post:danbooru:6003")
        }


def test_structural_kinds_anchor_but_never_merge(tmp_path: Path) -> None:
    catalog = tmp_path / "structural.sqlite3"
    with CatalogDatabase(catalog) as database:
        c = database.connection
        ids: dict[str, int] = {}
        for native in ("7001", "7002"):
            platform_id = _platform(c, "danbooru")
            c.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform_id, native),
            )
            ids[native] = int(
                c.execute(
                    "SELECT post_id FROM posts WHERE native_post_id = ?", (native,)
                ).fetchone()[0]
            )
        CatalogWriter(database).insert_relationship(
            RelationshipRecord(
                subject_kind="post",
                subject_id=ids["7001"],
                relation_kind="parent_of",
                target_kind="post",
                target_id=ids["7002"],
                epistemic_status="observed",
                created_at="2026-01-02T00:00:00Z",
            )
        )
        c.commit()
        components = lineage_components(database)
    # A quote/reply parent link is new authorship, not claim descent.
    assert all(len(component["members"]) == 1 for component in components)
    assert all(component["dependence_edges"] == [] for component in components)


def test_derivation_is_read_only_and_deterministic(tmp_path: Path) -> None:
    catalog = tmp_path / "readonly.sqlite3"
    _mirror_chain_fixture(catalog)
    before = hashlib.sha256(catalog.read_bytes()).hexdigest()
    with CatalogDatabase(catalog) as database:
        first = lineage_components(database)
        second = lineage_components(database)
    assert hashlib.sha256(catalog.read_bytes()).hexdigest() == before
    assert first == second
    # An unknown kind or status in a stated policy is an error, not a silent
    # empty edge set.
    with CatalogDatabase(catalog) as database:
        for kwargs in ({"relation_kinds": {"mirrors"}}, {"epistemic_statuses": {"rumored"}}):
            try:
                lineage_components(database, **kwargs)  # type: ignore[arg-type]
            except ValueError:
                continue
            raise AssertionError(f"expected ValueError for {kwargs}")
