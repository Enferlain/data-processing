from __future__ import annotations

import json
from pathlib import Path

from media_catalog.acquisition import (
    AcquisitionSelection,
    check_planned_item_current,
    plan_acquisition,
)
from media_catalog.acquisition.policies import PolicyIdentity
from media_catalog.database import CatalogDatabase

NOW = "2026-08-10T14:00:00Z"


def _platform(connection, key: str) -> int:  # type: ignore[no-untyped-def]
    return int(
        connection.execute(
            "SELECT platform_id FROM platforms WHERE platform_key = ?", (key,)
        ).fetchone()[0]
    )


def _seed_occurrences(database: CatalogDatabase) -> None:
    connection = database.connection
    for post_id, platform, native_id in (
        (1, "pixiv", "100"),
        (2, "danbooru", "200"),
        (3, "x", "300"),
    ):
        connection.execute(
            """INSERT INTO posts (
                   post_id, platform_id, native_post_id, first_seen_at, last_seen_at
               ) VALUES (?, ?, ?, ?, ?)""",
            (post_id, _platform(connection, platform), native_id, NOW, NOW),
        )
    pixiv_variants = json.dumps(
        {
            "version": "pixiv-variants-v1",
            "variants": [
                {"role": "original", "url": "https://i.pximg.net/100_p0.jpg"},
                {"role": "preview", "url": "https://i.pximg.net/100_p0_preview.jpg"},
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    connection.execute(
        """INSERT INTO media_occurrences (
               media_occurrence_id, post_id, source_key, media_index, media_type,
               remote_url, preview_url, mime_type, width, height, variants_json,
               availability, observed_at
           ) VALUES (1, 1, '100:p0', 0, 'image/jpeg', ?, ?, 'image/jpeg', 1200, 800,
                     ?, 'available', ?)""",
        (
            "https://i.pximg.net/100_p0.jpg",
            "https://i.pximg.net/100_p0_preview.jpg",
            pixiv_variants,
            NOW,
        ),
    )
    connection.execute(
        """INSERT INTO media_occurrences (
               media_occurrence_id, post_id, source_key, media_index, media_type,
               remote_url, mime_type, variants_json, availability, observed_at
           ) VALUES (2, 1, '100:p1', 1, 'image/png', ?, 'image/png', ?, 'available', ?)""",
        (
            "https://i.pximg.net/100_p1.png",
            json.dumps(
                {
                    "version": "pixiv-variants-v1",
                    "variants": [
                        {"role": "original", "url": "https://i.pximg.net/100_p1.png"}
                    ],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            NOW,
        ),
    )
    connection.execute(
        """INSERT INTO media_occurrences (
               media_occurrence_id, post_id, source_key, media_index, media_type,
               remote_url, preview_url, mime_type, width, height, variants_json,
               declared_md5, declared_file_size, availability, observed_at
           ) VALUES (3, 2, 'primary', 0, 'image/jpeg', ?, ?, 'image/jpeg', 2000, 1000,
                     ?, ?, 12345, 'available', ?)""",
        (
            "https://cdn.donmai.us/original.jpg",
            "https://cdn.donmai.us/preview.jpg",
            json.dumps(
                {
                    "version": "provider-variants-v1",
                    "variants": [
                        {"role": "original", "url": "https://cdn.donmai.us/original.jpg"},
                        {"role": "sample", "url": "https://cdn.donmai.us/sample.jpg"},
                        {"role": "preview", "url": "https://cdn.donmai.us/preview.jpg"},
                    ],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            "a" * 32,
            NOW,
        ),
    )
    connection.execute(
        """INSERT INTO media_occurrences (
               media_occurrence_id, post_id, source_key, media_index, media_type,
               remote_url, availability, observed_at
           ) VALUES (4, 3, '300:0', 0, 'image', 'https://pbs.twimg.com/media/example',
                     'available', ?)""",
        (NOW,),
    )
    connection.execute(
        """INSERT INTO assets (
               asset_id, verified_sha256, verified_md5, storage_kind, verification_method
           ) VALUES (10, ?, ?, 'managed', 'calculated')""",
        ("b" * 64, "a" * 32),
    )
    connection.execute(
        """INSERT INTO occurrence_assets (
               media_occurrence_id, asset_id, relationship, verification_source
           ) VALUES (3, 10, 'reference', 'calculated')"""
    )


def test_planning_selects_pixiv_pages_and_booru_variants_without_conflating_claims(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database, database.transaction():
        _seed_occurrences(database)

    plan = plan_acquisition(
        path,
        [
            AcquisitionSelection(1),
            AcquisitionSelection(1, "preview"),
            AcquisitionSelection(1, "preview"),
            AcquisitionSelection(2, "original"),
            AcquisitionSelection(3, "sample"),
            AcquisitionSelection(3, "preview"),
            AcquisitionSelection(3, "original"),
            AcquisitionSelection(4),
        ],
        max_items=10,
        clock=lambda: NOW,
    )

    assert plan.counts == {
        "requested": 7,
        "eligible": 5,
        "already_satisfied": 1,
        "excluded": 1,
        "duplicates": 1,
    }
    items = {(item.media_occurrence_id, item.variant_key): item for item in plan.items}
    assert items[(1, "primary")].request_policy == PolicyIdentity(
        "pixiv-media", "pixiv-media-v1"
    )
    assert items[(2, "original")].eligibility == "eligible"
    assert items[(3, "original")].eligibility == "already_satisfied"
    assert items[(3, "original")].satisfied_asset_id == 10
    assert items[(3, "original")].declared_md5 == "a" * 32
    assert items[(3, "sample")].declared_md5 is None
    assert items[(3, "sample")].declared_file_size is None
    assert items[(3, "preview")].eligibility == "eligible"
    assert items[(4, "primary")].exclusion_reason == "unsupported_provider"
    public = str(plan.as_dict())
    assert "selected_url" not in public
    assert "pximg.net" not in public
    assert "donmai.us" not in public


def test_planning_is_read_only_network_free_and_does_not_create_layout(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    managed = tmp_path / "managed-must-not-exist"
    with CatalogDatabase(path) as database, database.transaction():
        _seed_occurrences(database)
    before = path.read_bytes(), tuple(sorted(item.name for item in tmp_path.iterdir()))

    plan = plan_acquisition(path, [AcquisitionSelection(1)], max_items=1, clock=lambda: NOW)

    assert plan.counts["eligible"] == 1
    assert not managed.exists()
    assert (path.read_bytes(), tuple(sorted(item.name for item in tmp_path.iterdir()))) == before


def test_changed_variant_or_policy_is_stale_before_any_request(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        with database.transaction():
            _seed_occurrences(database)
        plan = plan_acquisition(
            database,
            [AcquisitionSelection(1)],
            max_items=1,
            clock=lambda: NOW,
        )
        assert check_planned_item_current(database, plan.items[0]) == (True, None)
        with database.transaction():
            database.connection.execute(
                "UPDATE media_occurrences SET remote_url = ? WHERE media_occurrence_id = 1",
                ("https://i.pximg.net/replaced.jpg",),
            )
        assert check_planned_item_current(database, plan.items[0]) == (False, "stale_target")

    with CatalogDatabase(path) as database:
        fresh = plan_acquisition(
            database,
            [AcquisitionSelection(2, "original")],
            max_items=1,
            clock=lambda: NOW,
        )
        def changed_policy(_platform: str) -> PolicyIdentity:
            return PolicyIdentity("pixiv-media", "pixiv-media-v2")

        assert check_planned_item_current(
            database,
            fresh.items[0],
            policy_resolver=changed_policy,
        ) == (False, "stale_target")
