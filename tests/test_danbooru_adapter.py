from __future__ import annotations

import json
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
    assert [variant["role"] for variant in media["variants"]] == [
        "original",
        "sample",
        "preview",
    ]
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
