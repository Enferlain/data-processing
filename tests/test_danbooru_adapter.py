from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import AdapterFailure, AdapterOperation, AdapterOutcome, AdapterRequest
from media_catalog.adapters.danbooru import (
    AIBOORU,
    DANBOORU,
    DanbooruAdapter,
    DanbooruCredentials,
)
from media_catalog.adapters.fixtures import FixtureCase, load_fixture_suite
from media_catalog.database import CatalogDatabase
from media_catalog.remote_queries import list_post_external_references, list_post_tags
from media_catalog.remote_sync import MetadataSyncService, SyncLimits

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
NOW = "2026-08-10T00:00:00Z"


def _case(suite_name: str, case_name: str) -> FixtureCase:
    suite = load_fixture_suite(FIXTURES / suite_name)
    return next(case for case in suite.cases if case.name == case_name)


def _adapter(instance=DANBOORU, handler=None, credentials=None) -> DanbooruAdapter:
    if handler is None:

        def handler(request):
            return httpx.Response(500, json={"message": "unused"})

    return DanbooruAdapter(
        instance,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        credentials=credentials,
        clock=lambda: NOW,
    )


def test_post_normalization_keeps_uploader_tags_hash_references_and_relations_separate() -> None:
    case = _case("danbooru.json", "post_with_attribution")
    page = _adapter().normalize(case.response)
    by_kind: dict[str, list] = {}
    for item in page.items:
        by_kind.setdefault(item.object_kind, []).append(item)

    assert [item.native_id for item in by_kind["account"]] == ["17"]
    assert by_kind["post_participant"][0].data["role"] == "uploader"
    assert {item.data["category"] for item in by_kind["post_tag"]} == {
        "artist",
        "character",
        "copyright",
        "general",
        "meta",
    }
    media = by_kind["media_occurrence"][0].data
    assert media["declared_md5"] == "0123456789abcdef0123456789abcdef"
    assert "verified_md5" not in media
    # Original/sample/preview keep their post-field URLs; the media asset adds
    # per-variant dimensions and the provider-native intermediate sizes.
    assert [variant["role"] for variant in media["variants"]] == [
        "original",
        "sample",
        "preview",
        "180x180",
        "360x360",
        "720x720",
    ]
    original_variant = media["variants"][0]
    assert original_variant["url"] == "https://cdn.donmai.us/original.jpg"
    assert (original_variant["width"], original_variant["height"]) == (1400, 1000)
    assert original_variant["ext"] == "jpg"
    assert original_variant["mime_type"] == "image/jpeg"
    assert media["variants"][3] == {
        "role": "180x180",
        "url": "https://cdn.donmai.us/180x180.jpg",
        "width": 252,
        "height": 180,
        "ext": "jpg",
        "mime_type": "image/jpeg",
    }
    post = by_kind["post"][0].data
    assert post["score"] == {"up": 14, "down": 2, "total": 12}
    assert post["fav_count"] == 11
    assert post["flags"] == {
        "deleted": False,
        "pending": False,
        "flagged": False,
        "banned": False,
    }
    refs = by_kind["external_reference"]
    assert any(item.data.get("target_platform") == "pixiv" for item in refs)
    assert all(item.data["evidence_only"] is True for item in refs)
    assert by_kind["post_relation"][0].data == {
        "platform": "danbooru",
        "source_post_id": "2999",
        "target_post_id": "3001",
        "relation_type": "parent_of",
    }
    assert "attribution" not in by_kind


def test_artist_is_attribution_and_never_materialized_as_account() -> None:
    case = _case("danbooru.json", "artist_record")
    page = _adapter().normalize(case.response)
    assert [item.object_kind for item in page.items] == ["attribution"]
    artist = page.items[0]
    assert artist.native_id == "4001"
    assert artist.data["account"] is False
    assert artist.data["other_names"] == ["artist-a", "別名"]
    assert artist.data["urls"] == [
        "https://www.pixiv.net/users/1001",
        "https://x.com/artist_a",
    ]
    assert artist.data["group_name"] == "circle_a"
    assert artist.data["is_banned"] is False
    assert artist.data["created_at"] == "2025-06-01T00:00:00.000Z"
    assert artist.data["updated_at"] == "2026-01-02T00:00:00.000Z"


def test_listing_uses_opaque_keyset_continuation_and_validates_its_version() -> None:
    case = _case("danbooru.json", "post_listing_keyset")
    page = _adapter().normalize(case.response)
    assert [item.native_id for item in page.items] == ["3002", "3001"]
    assert page.continuation is not None
    assert page.continuation.value == {"page": "b3001"}

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    adapter = _adapter(handler=handler)
    adapter.fetch(
        AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "artist_a",
            continuation=page.continuation,
        )
    )
    assert requests[0].url.params["page"] == "b3001"
    assert requests[0].url.params["limit"] == "200"


def test_instances_are_independent_and_malformed_aibooru_does_not_fall_back() -> None:
    danbooru = _adapter().normalize(_case("danbooru.json", "post_with_attribution").response)
    aibooru_adapter = _adapter(AIBOORU)
    aibooru = aibooru_adapter.normalize(_case("aibooru.json", "compatible_post").response)
    danbooru_post = next(item for item in danbooru.items if item.object_kind == "post")
    aibooru_post = next(item for item in aibooru.items if item.object_kind == "post")
    assert danbooru_post.native_id == aibooru_post.native_id == "3001"
    assert danbooru_post.data["platform"] == "danbooru"
    assert aibooru_post.data["platform"] == "aibooru"

    with pytest.raises(AdapterFailure) as error:
        aibooru_adapter.normalize(_case("aibooru.json", "incompatible_shape").response)
    assert error.value.outcome is AdapterOutcome.MALFORMED_RESPONSE


def test_deleted_and_rate_limited_outcomes_are_typed() -> None:
    deleted = _adapter().normalize(_case("danbooru.json", "deleted_post").response)
    post = next(item for item in deleted.items if item.object_kind == "post")
    assert post.data["availability"] == "deleted"
    assert all(item.object_kind != "media_occurrence" for item in deleted.items)

    with pytest.raises(AdapterFailure) as error:
        _adapter().normalize(_case("danbooru.json", "rate_limited").response)
    assert error.value.outcome is AdapterOutcome.RATE_LIMITED
    assert error.value.status_code == 429


def test_transport_identifies_itself_but_envelope_and_repr_do_not_leak_credentials() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"x-rate-limit": "9;w=1", "set-cookie": "private"},
            json={"id": 3001},
        )

    credentials = DanbooruCredentials("example-user", "sentinel-secret")
    adapter = _adapter(handler=handler, credentials=credentials)
    envelope = adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "3001"))
    assert requests[0].url == "https://danbooru.donmai.us/posts/3001.json"
    assert requests[0].headers["user-agent"] == DANBOORU.user_agent
    assert requests[0].headers["authorization"].startswith("Basic ")
    assert envelope.request_identity == "danbooru:fetch_post:3001"
    assert envelope.headers == {
        "content-type": "application/json",
        "x-rate-limit": "9;w=1",
    }
    public = repr(credentials) + repr(adapter) + repr(envelope)
    assert "sentinel-secret" not in public
    assert "private" not in public


def test_environment_credentials_require_both_references() -> None:
    assert DanbooruCredentials.from_environment(DANBOORU, {}) is None
    with pytest.raises(ValueError, match="configure both"):
        DanbooruCredentials.from_environment(DANBOORU, {DANBOORU.login_env: "user"})
    loaded = DanbooruCredentials.from_environment(
        DANBOORU,
        {DANBOORU.login_env: "user", DANBOORU.api_key_env: "secret"},
    )
    assert loaded is not None
    assert "secret" not in repr(loaded)


def test_fetch_never_follows_metadata_urls_to_media_hosts() -> None:
    case = _case("danbooru.json", "post_with_attribution")
    body = json.loads(case.response.payload)
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        return httpx.Response(200, json=body)

    adapter = _adapter(handler=handler)
    envelope = adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "3001"))
    adapter.normalize(envelope)
    assert requested_hosts == ["danbooru.donmai.us"]


def test_danbooru_catalog_integration_keeps_metadata_evidence_separate(
    tmp_path: Path,
) -> None:
    case = _case("danbooru.json", "post_with_attribution")
    body = json.loads(case.response.payload)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=case.response.headers, json=body, request=request)

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = MetadataSyncService(
            database,
            _adapter(handler=handler),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ).synchronize(
            AdapterOperation.FETCH_POST,
            "3001",
            limits=SyncLimits(1, 1, 50, 10),
        )
        post_id = database.connection.execute(
            "SELECT post_id FROM posts WHERE native_post_id = '3001'"
        ).fetchone()[0]
        occurrence = database.connection.execute(
            """SELECT declared_md5, declared_file_size, mime_type
               FROM media_occurrences WHERE post_id = ?""",
            (post_id,),
        ).fetchone()
        assert tuple(occurrence) == (
            "0123456789abcdef0123456789abcdef",
            123456,
            "image/jpeg",
        )
        assert len(list_post_tags(database, post_id)) == 5
        assert len(list_post_external_references(database, post_id)) == 2
        assert database.connection.execute("SELECT COUNT(*) FROM post_relations").fetchone()[0] == 1
        assert database.connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
        assert result.status == "complete"


@pytest.mark.parametrize(
    "field, value",
    (
        ("score", "twelve"),
        ("fav_count", True),
        ("is_flagged", "yes"),
        ("media_asset", "asset-ref"),
        ("media_asset", {"variants": [{"type": "180x180", "url": "https://x", "width": "big"}]}),
    ),
)
def test_malformed_engagement_and_asset_fields_fail_closed(field: str, value: object) -> None:
    # The engagement/flag/media-asset fields fail closed as malformed responses
    # (the sync service retains raw) instead of silently dropping provider values.
    case = _case("danbooru.json", "post_with_attribution")
    envelope = case.response
    body = json.loads(envelope.payload)
    body[field] = value
    mutated = replace(envelope, payload=json.dumps(body).encode())
    with pytest.raises(AdapterFailure) as failure:
        _adapter().normalize(mutated)
    assert failure.value.outcome is AdapterOutcome.MALFORMED_RESPONSE


def test_danbooru_post_and_artist_facts_persist_idempotently(tmp_path: Path) -> None:
    # OpenSpec extend-danbooru-post-artist-facts: engagement facts land as post
    # metadata observations, status flags as flag observations, media-asset
    # dimensions enrich the occurrence variants, and artist group/ban state
    # persists on the attribution snapshot -- and unchanged re-observation does
    # not duplicate rows.
    post_case = _case("danbooru.json", "post_with_attribution")
    post_body = json.loads(post_case.response.payload)
    artist_case = _case("danbooru.json", "artist_record")
    artist_body = json.loads(artist_case.response.payload)

    def handler(request: httpx.Request) -> httpx.Response:
        body = artist_body if "artists" in str(request.url) else post_body
        return httpx.Response(200, headers=post_case.response.headers, json=body, request=request)

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        service = MetadataSyncService(
            database,
            _adapter(handler=handler),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        )
        for _ in range(2):
            assert (
                service.synchronize(
                    AdapterOperation.FETCH_POST, "3001", limits=SyncLimits(1, 1, 50, 10)
                ).status
                == "complete"
            )
            assert (
                service.synchronize(
                    AdapterOperation.FETCH_ATTRIBUTION, "4001", limits=SyncLimits(1, 1, 50, 10)
                ).status
                == "complete"
            )
        connection = database.connection
        assert [
            tuple(row)
            for row in connection.execute(
                """SELECT score_up, score_down, score_total, favorite_count,
                          flag_deleted, flag_pending, flag_flagged
                     FROM post_metadata_observations"""
            )
        ] == [(14, 2, 12, 11, False, False, False)]
        assert {
            tuple(row)
            for row in connection.execute(
                "SELECT flag_name, flag_value FROM post_flag_observations"
            )
        } == {("deleted", 0), ("pending", 0), ("flagged", 0), ("banned", 0)}
        variants = json.loads(
            connection.execute("SELECT variants_json FROM media_occurrences").fetchone()[0]
        )
        assert variants["version"] == "provider-variants-v1"
        by_role = {variant["role"]: variant for variant in variants["variants"]}
        assert (by_role["original"]["width"], by_role["original"]["height"]) == (1400, 1000)
        assert (by_role["180x180"]["width"], by_role["180x180"]["height"]) == (252, 180)
        assert by_role["180x180"]["url"] == "https://cdn.donmai.us/180x180.jpg"
        artist = connection.execute(
            "SELECT group_name, is_banned FROM attribution_snapshots"
        ).fetchone()
        assert tuple(artist) == ("circle_a", 0)
        # Unchanged re-observation kept one row per distinct fact digest.
        assert (
            connection.execute("SELECT COUNT(*) FROM post_metadata_observations").fetchone()[0] == 1
        )
        assert connection.execute("SELECT COUNT(*) FROM post_flag_observations").fetchone()[0] == 4


def test_full_danbooru_page_fits_default_top_level_record_budget(tmp_path: Path) -> None:
    body = [
        {
            "id": 10_000 - index,
            "uploader_id": 17,
            "tag_string_artist": "artist_a",
            "tag_string_character": "character_a",
            "tag_string_copyright": "series_a",
            "tag_string_general": "solo",
            "tag_string_meta": "translated",
        }
        for index in range(DANBOORU.page_size)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body, request=request)

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        result = MetadataSyncService(
            database,
            _adapter(handler=handler),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: NOW,
        ).synchronize(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "artist_a",
            limits=SyncLimits(1, 2, 500, 10),
        )
        assert result.status == "paused"
        assert result.budget_boundary == "request"
        assert result.page_count == 1
        assert result.record_count == 400
        assert database.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 200
