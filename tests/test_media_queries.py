from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import media_catalog.media_queries as media_queries_module
from media_catalog.acquisition import AcquisitionSelection, plan_acquisition
from media_catalog.database import CatalogDatabase
from media_catalog.media_queries import MediaQueryService, get_media_occurrence

NOW = "2026-08-11T03:00:00Z"


def _seed(database: CatalogDatabase) -> None:
    connection = database.connection
    platforms = {
        str(row["platform_key"]): int(row["platform_id"])
        for row in connection.execute("SELECT platform_id, platform_key FROM platforms")
    }
    secret_payload = b'{"signed":"https://secret.invalid/file?token=PRIVATE"}'
    raw_payload_id = int(
        connection.execute(
            """INSERT INTO raw_payloads (sha256, media_type, payload, byte_size)
               VALUES (?, 'application/json', ?, ?)""",
            (hashlib.sha256(secret_payload).hexdigest(), secret_payload, len(secret_payload)),
        ).lastrowid
    )
    raw_observation_id = int(
        connection.execute(
            """INSERT INTO raw_observations (
                   raw_payload_id, platform_id, object_kind, native_id, media_type,
                   source_schema, status, observed_at
               ) VALUES (?, ?, 'post', '100', 'application/json', 'fixture-private-v1',
                         'available', ?)""",
            (raw_payload_id, platforms["pixiv"], NOW),
        ).lastrowid
    )
    connection.executemany(
        """INSERT INTO accounts (
               account_id, platform_id, native_account_id, availability,
               first_seen_at, last_seen_at
           ) VALUES (?, ?, ?, 'available', ?, ?)""",
        (
            (1, platforms["pixiv"], "10", NOW, NOW),
            (2, platforms["pixiv"], "11", NOW, NOW),
        ),
    )
    connection.executemany(
        """INSERT INTO account_snapshots (
               account_id, observed_at, handle, display_name, bio, snapshot_digest
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            (1, NOW, "artist", "Artist", "PRIVATE_BIO", "a" * 64),
            (2, NOW, "helper", "Helper", None, "b" * 64),
        ),
    )
    connection.executemany(
        """INSERT INTO posts (
               post_id, platform_id, native_post_id, availability, first_seen_at, last_seen_at
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            (1, platforms["pixiv"], "100", "available", NOW, NOW),
            (2, platforms["danbooru"], "200", "available", NOW, NOW),
        ),
    )
    connection.executemany(
        """INSERT INTO post_participants (
               post_id, account_id, role, review_state
           ) VALUES (?, ?, 'author', 'observed')""",
        ((1, 1), (1, 2)),
    )
    connection.executemany(
        """INSERT INTO media_occurrences (
               media_occurrence_id, post_id, source_key, media_index, media_type, role,
               remote_url, preview_url, mime_type, width, height, variants_json,
               availability, declared_md5, declared_file_size, raw_observation_id, observed_at
           ) VALUES (?, ?, ?, ?, 'image/png', 'primary', ?, ?, 'image/png', 10, 20,
                     ?, ?, ?, 123, ?, ?)""",
        (
            (
                10,
                1,
                "100:p0",
                0,
                "https://i.pximg.net/original.png?token=PRIVATE_QUERY",
                "https://i.pximg.net/preview.png?token=PRIVATE_PREVIEW",
                json.dumps(
                    {
                        "variants": [
                            {
                                "role": "original",
                                "url": "https://i.pximg.net/original.png?token=PRIVATE_QUERY",
                            }
                        ]
                    }
                ),
                "available",
                "1" * 32,
                raw_observation_id,
                NOW,
            ),
            (
                11,
                1,
                "100:p1",
                1,
                "https://i.pximg.net/broken.png?token=PRIVATE_BROKEN",
                None,
                "{",
                "unavailable",
                None,
                None,
                NOW,
            ),
            (
                12,
                2,
                "primary",
                0,
                "https://cdn.donmai.us/file.png?token=PRIVATE_DANBOORU",
                None,
                None,
                "available",
                None,
                None,
                NOW,
            ),
        ),
    )
    connection.execute(
        """INSERT INTO assets (
               asset_id, verified_sha256, verified_md5, byte_size, storage_kind,
               verification_method, verified_at, detected_mime_type,
               detected_width, detected_height, detected_frame_count
           ) VALUES (20, ?, ?, 321, 'managed', 'calculated', ?, 'image/png', 10, 20, 1)""",
        ("2" * 64, "3" * 32, NOW),
    )
    connection.execute(
        """INSERT INTO occurrence_assets (
               media_occurrence_id, asset_id, relationship, verification_source
           ) VALUES (10, 20, 'exact', 'verified')"""
    )
    connection.execute(
        """INSERT INTO assets (
               asset_id, verified_sha256, verified_md5, byte_size, storage_kind,
               verification_method, verified_at
           ) VALUES (21, ?, ?, 111, 'legacy_reference', 'legacy_x_likes', ?)""",
        ("4" * 64, "5" * 32, NOW),
    )
    connection.execute(
        """INSERT INTO occurrence_assets (
               media_occurrence_id, asset_id, relationship, verification_source
           ) VALUES (10, 21, 'reference', 'legacy')"""
    )
    connection.execute(
        """INSERT INTO asset_fingerprints (
               asset_id, fingerprint_kind, fingerprint_value, algorithm,
               algorithm_version, source, verification_status, observed_at
           ) VALUES (20, 'md5', ?, 'md5', 'md5-v1', 'calculated', 'verified', ?)""",
        ("3" * 32, NOW),
    )
    connection.execute(
        """INSERT INTO asset_fingerprints (
               asset_id, fingerprint_kind, fingerprint_value, algorithm,
               algorithm_version, source, verification_status, observed_at
           ) VALUES (20, 'phash', 'abcd', 'imagehash.phash', 'imagehash.phash-v1',
                     'calculated', 'verified', ?)""",
        (NOW,),
    )
    managed_root_id = int(
        connection.execute(
            """INSERT INTO managed_roots (
                   root_kind, root_identity, display_label, private_path, created_at
               ) VALUES ('source', 'fixture-root', 'private-source',
                         '/PRIVATE/ROOT/PATH', ?)""",
            (NOW,),
        ).lastrowid
    )
    connection.execute(
        """INSERT INTO occurrence_sources (
               media_occurrence_id, managed_root_id, source_kind, relative_path,
               source_identity, recorded_at
           ) VALUES (10, ?, 'legacy_local', 'PRIVATE/relative/file.png',
                     'PRIVATE_SOURCE_IDENTITY', ?)""",
        (managed_root_id, NOW),
    )
    connection.execute(
        """INSERT INTO occurrence_sources (
               media_occurrence_id, managed_root_id, source_kind, relative_path,
               source_identity, recorded_at
           ) VALUES (10, ?, 'external', 'PRIVATE/other/file.png',
                     'PRIVATE_OTHER_IDENTITY', ?)""",
        (managed_root_id, NOW),
    )


def test_listing_is_keyset_paginated_and_filters_without_duplicate_rows(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed(database)
        service = MediaQueryService(database)
        first = service.list(limit=1)
        assert [row["media_occurrence_id"] for row in first["results"]] == [10]
        assert first["has_more"] is True
        assert first["continuation"] == 10
        second = service.list(limit=1, after=first["continuation"])
        assert [row["media_occurrence_id"] for row in second["results"]] == [11]

        assert [
            row["media_occurrence_id"]
            for row in service.list(author="pixiv:10")["results"]
        ] == [10, 11]
        assert [
            row["media_occurrence_id"]
            for row in service.list(post="pixiv:100")["results"]
        ] == [10, 11]
        assert [
            row["media_occurrence_id"]
            for row in service.list(platform="danbooru")["results"]
        ] == [12]
        assert [
            row["media_occurrence_id"]
            for row in service.list(availability="unavailable")["results"]
        ] == [11]
        assert [row["media_occurrence_id"] for row in service.list(linked=True)["results"]] == [10]
        assert [
            row["media_occurrence_id"] for row in service.list(linked=False)["results"]
        ] == [11, 12]
        assert [
            row["media_occurrence_id"]
            for row in service.list(
                platform="pixiv",
                author="pixiv:10",
                post="pixiv:100",
                availability="available",
                linked=True,
            )["results"]
        ] == [10]

        with pytest.raises(ValueError, match="PLATFORM:NATIVE_ID"):
            service.list(author="mutable-handle")
        with pytest.raises(ValueError, match="between 1 and 200"):
            service.list(limit=201)


def test_detail_matches_planner_and_redacts_urls_payloads_and_paths(tmp_path: Path) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed(database)
        detail = get_media_occurrence(database, 10)
        assert detail is not None
        occurrence = detail["occurrence"]
        assert occurrence["declared"]["md5"] == "1" * 32
        assert detail["assets"]["results"][0]["verified"]["md5"] == "3" * 32
        assert [author["native_account_id"] for author in detail["authors"]["results"]] == [
            "10",
            "11",
        ]
        assert [item["source_kind"] for item in detail["sources"]["results"]] == [
            "legacy_local",
            "external",
        ]
        assert [item["asset_id"] for item in detail["assets"]["results"]] == [20, 21]

        selections = [
            AcquisitionSelection(10, variant["key"]) for variant in occurrence["variants"]
        ]
        planned = plan_acquisition(
            database, selections, max_items=len(selections), clock=lambda: NOW
        )
        expected = {item.variant_key: item.as_dict() for item in planned.items}
        for variant in occurrence["variants"]:
            plan_item = expected[variant["key"]]
            assert variant["selection"] == f"10:{variant['key']}"
            for key in (
                "eligibility",
                "exclusion_reason",
                "request_policy_key",
                "request_policy_version",
                "satisfied_asset_id",
            ):
                assert variant[key] == plan_item[key]

        rendered = json.dumps(detail)
        for secret in (
            "secret.invalid",
            "i.pximg.net",
            "PRIVATE_QUERY",
            "PRIVATE_PREVIEW",
            "PRIVATE_BIO",
            "/PRIVATE/ROOT/PATH",
            "PRIVATE/relative/file.png",
            "PRIVATE_SOURCE_IDENTITY",
            "PRIVATE/other/file.png",
            "PRIVATE_OTHER_IDENTITY",
        ):
            assert secret not in rendered

        malformed = get_media_occurrence(database, 11)
        assert malformed is not None
        assert malformed["occurrence"]["variants"][0]["eligibility"] == "excluded"
        assert malformed["occurrence"]["variants"][0][
            "exclusion_reason"
        ] == "unavailable_occurrence"
        malformed_plan = plan_acquisition(
            database,
            [AcquisitionSelection(11, "primary")],
            max_items=1,
            clock=lambda: NOW,
        )
        assert malformed["occurrence"]["variants"][0]["exclusion_reason"] == (
            malformed_plan.items[0].exclusion_reason
        )
        assert get_media_occurrence(database, 999) is None


def test_related_collections_are_bounded_and_report_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed(database)
        monkeypatch.setattr(media_queries_module, "MAX_RELATED_ITEMS", 1)
        detail = get_media_occurrence(database, 10)
    assert detail is not None
    for key in ("authors", "assets", "sources"):
        assert detail[key]["truncated"] is True
        assert len(detail[key]["results"]) == 1
    assert detail["assets"]["results"][0]["fingerprints_truncated"] is True


def test_variant_parity_covers_archive_ambiguous_booru_and_unsupported(
    tmp_path: Path,
) -> None:
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        with database.transaction():
            _seed(database)
            x_platform_id = int(
                database.connection.execute(
                    "SELECT platform_id FROM platforms WHERE platform_key = 'x'"
                ).fetchone()[0]
            )
            database.connection.execute(
                """INSERT INTO posts (
                       post_id, platform_id, native_post_id, first_seen_at, last_seen_at
                   ) VALUES (3, ?, '300', ?, ?)""",
                (x_platform_id, NOW, NOW),
            )
            database.connection.executemany(
                """INSERT INTO media_occurrences (
                       media_occurrence_id, post_id, source_key, media_index, media_type,
                       remote_url, variants_json, availability, observed_at
                   ) VALUES (?, ?, ?, 0, ?, ?, ?, 'available', ?)""",
                (
                    (
                        13,
                        1,
                        "100:ugoira",
                        "animation",
                        None,
                        json.dumps(
                            {
                                "archive": {
                                    "url": "https://i.pximg.net/archive.zip?token=PRIVATE_ARCHIVE"
                                }
                            }
                        ),
                        NOW,
                    ),
                    (
                        14,
                        1,
                        "100:ambiguous",
                        "image/png",
                        "https://i.pximg.net/ambiguous.png",
                        json.dumps(
                            {
                                "variants": [
                                    {"role": "original", "url": "https://i.pximg.net/a.png"},
                                    {"role": "original", "url": "https://i.pximg.net/b.png"},
                                ]
                            }
                        ),
                        NOW,
                    ),
                    (
                        15,
                        3,
                        "300:0",
                        "image/jpeg",
                        "https://pbs.twimg.com/media/private",
                        None,
                        NOW,
                    ),
                    (
                        16,
                        1,
                        "100:invalid",
                        "image/png",
                        "https://i.pximg.net/invalid.png",
                        "{",
                        NOW,
                    ),
                ),
            )

        for occurrence_id in (12, 13, 14, 15, 16):
            detail = get_media_occurrence(database, occurrence_id)
            assert detail is not None
            variants = detail["occurrence"]["variants"]
            planned = plan_acquisition(
                database,
                [AcquisitionSelection(occurrence_id, item["key"]) for item in variants],
                max_items=len(variants),
                clock=lambda: NOW,
            )
            by_key = {item.variant_key: item.as_dict() for item in planned.items}
            for variant in variants:
                assert variant["eligibility"] == by_key[variant["key"]]["eligibility"]
                assert variant["exclusion_reason"] == by_key[variant["key"]][
                    "exclusion_reason"
                ]
        assert {
            item["key"] for item in get_media_occurrence(database, 13)["occurrence"]["variants"]
        } == {"archive", "primary"}
        assert get_media_occurrence(database, 14)["occurrence"]["variants"][0][
            "exclusion_reason"
        ] == "ambiguous_variant"
        assert get_media_occurrence(database, 15)["occurrence"]["variants"][0][
            "exclusion_reason"
        ] == "unsupported_provider"
        assert get_media_occurrence(database, 16)["occurrence"]["variants"][0][
            "exclusion_reason"
        ] == "invalid_variants"


def test_path_queries_are_read_only_and_do_not_create_sidecars(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog) as database, database.transaction():
        _seed(database)
    before_bytes = catalog.read_bytes()
    before_names = sorted(path.name for path in tmp_path.iterdir())
    result = MediaQueryService(catalog).list(limit=10)
    assert result["count"] == 3
    assert catalog.read_bytes() == before_bytes
    assert sorted(path.name for path in tmp_path.iterdir()) == before_names
