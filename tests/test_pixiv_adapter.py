from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import (
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    Continuation,
    load_fixture_suite,
)
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.database import CatalogDatabase
from media_catalog.remote_queries import list_account_external_links, list_post_tags
from media_catalog.remote_sync import MetadataSyncService, SyncLimits

FIXTURE = Path(__file__).parent / "fixtures" / "metadata_adapters" / "pixiv.json"


def _suite_case(name: str):
    return next(case for case in load_fixture_suite(FIXTURE).cases if case.name == name)


def _adapter_for_cases(*names: str):
    cases = {name: _suite_case(name) for name in names}
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/user/detail"):
            case = cases["profile"]
        elif request.url.path.endswith("/illust/detail"):
            case = cases["single_page_artwork"]
        elif request.url.path.endswith("/user/illusts"):
            case = cases["artwork_listing_page"]
        elif request.url.path.endswith("/ugoira/metadata"):
            case = cases["ugoira"]
        else:
            raise AssertionError(f"unexpected URL: {request.url}")
        body = json.loads(case.response.payload)
        return httpx.Response(
            case.response.status_code,
            headers={"content-type": "application/json"},
            json=body,
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PixivAdapter(
        client=client, base_url="https://app-api.pixiv.net", refresh_token_env=None
    ), requests


def test_profile_and_artwork_requests_are_explicit_and_never_follow_media_urls() -> None:
    adapter, requests = _adapter_for_cases("profile", "single_page_artwork")
    profile = adapter.fetch_account("1001")
    assert profile.items[0].object_kind == "account"
    assert profile.items[0].data["native_id"] == "1001"
    assert {link["url"] for link in profile.items[0].data["external_links"]} == {
        "https://artist.example",
        "https://x.com/artist_a",
    }
    assert [request.url.path for request in requests] == ["/v1/user/detail"]

    post_page = adapter.fetch_post(2001)
    post = post_page.items[0]
    assert post.object_kind == "post"
    assert post.native_id == "2001"
    assert [item.object_kind for item in post_page.items] == [
        "post",
        "account",
        "post_participant",
        "post_tag",
        "media_occurrence",
    ]
    occurrence = post.data["media_occurrences"][0]
    assert occurrence["source_key"] == "2001:p0"
    assert occurrence["remote_url"].startswith("https://i.pximg.net/")
    assert [request.url.path for request in requests] == ["/v1/user/detail", "/v1/illust/detail"]
    assert all("i.pximg.net" not in str(request.url) for request in requests)


def test_multi_page_order_tags_and_ugoira_metadata_are_lossless() -> None:
    adapter = PixivAdapter(refresh_token_env=None)
    multi = adapter.normalize(_suite_case("multi_page_artwork").response)
    post = multi.items[0].data
    assert [item["source_key"] for item in post["media_occurrences"]] == ["2002:p0", "2002:p1"]
    assert [item["index"] for item in post["media_occurrences"]] == [0, 1]

    single = adapter.normalize(_suite_case("single_page_artwork").response)
    assert single.items[0].data["tags"][0]["translated_name"] == "Original"

    ugoira = adapter.normalize(_suite_case("ugoira").response)
    occurrence = ugoira.items[0].data["media_occurrences"][0]
    assert occurrence["source_key"] == "2003:ugoira"
    assert occurrence["frame_delays_ms"] == [80, 120]
    assert occurrence["archive_url"].endswith(".zip")
    assert ugoira.items[-1].object_kind == "media_occurrence"


def test_listing_is_bounded_by_opaque_continuation_and_does_not_run_implicitly() -> None:
    adapter, requests = _adapter_for_cases("profile", "artwork_listing_page")
    profile = adapter.fetch_account("1001")
    assert profile.items[0].native_id == "1001"
    assert [request.url.path for request in requests] == ["/v1/user/detail"]

    listing = adapter.list_account_posts("1001")
    assert [item.native_id for item in listing.items] == ["2002", "2001"]
    assert listing.continuation == Continuation("pixiv", "pixiv-list-v1", {"offset": 2})
    assert requests[-1].url.params["user_id"] == "1001"
    assert "offset" not in requests[-1].url.params

    with pytest.raises(AdapterFailure) as error:
        adapter.list_account_posts("1001", Continuation("other", "v1", {"offset": 2}))
    assert error.value.outcome is AdapterOutcome.MALFORMED_RESPONSE
    assert len(requests) == 2


def test_http_failures_are_typed_and_secrets_are_not_in_identity_or_repr() -> None:
    case = _suite_case("authentication_required")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            case.response.status_code,
            headers={"content-type": "application/json"},
            content=case.response.payload,
            request=request,
        )

    sentinel = "refresh-sentinel"
    adapter = PixivAdapter(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://app-api.pixiv.net",
        access_token=sentinel,
        refresh_token_env=None,
    )
    with pytest.raises(AdapterFailure) as error:
        adapter.fetch_account("1001")
    assert error.value.outcome is AdapterOutcome.AUTHENTICATION_REQUIRED
    assert sentinel not in repr(adapter)
    assert sentinel not in repr(error.value)


def test_refresh_token_exchange_is_isolated_from_metadata_envelopes() -> None:
    profile = _suite_case("profile")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "oauth.secure.pixiv.net":
            return httpx.Response(200, json={"access_token": "access-sentinel"}, request=request)
        return httpx.Response(
            profile.response.status_code,
            headers={"content-type": "application/json"},
            content=profile.response.payload,
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = PixivAdapter(
        client=client,
        base_url="https://app-api.pixiv.net",
        refresh_token="refresh-sentinel",
        refresh_token_env=None,
        client_id="client-id",
        client_secret="client-secret",
    )
    page = adapter.fetch_account("1001")
    assert page.items[0].native_id == "1001"
    assert [request.url.host for request in requests] == [
        "oauth.secure.pixiv.net",
        "app-api.pixiv.net",
    ]
    assert "refresh-sentinel" not in repr(adapter)
    assert "access-sentinel" not in repr(adapter)


def test_incomplete_pixiv_credential_references_fail_before_http() -> None:
    requested = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(500, request=request)

    adapter = PixivAdapter(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        refresh_token="refresh-sentinel",
        refresh_token_env=None,
        client_id_env=None,
        client_secret_env=None,
        require_auth=True,
    )
    with pytest.raises(AdapterFailure) as error:
        adapter.fetch_account("1001")
    assert error.value.outcome is AdapterOutcome.AUTHENTICATION_REQUIRED
    assert requested is False


def test_pixiv_catalog_integration_preserves_profile_artwork_and_page_metadata(
    tmp_path: Path,
) -> None:
    adapter, requests = _adapter_for_cases("profile", "single_page_artwork")
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        service = MetadataSyncService(
            database,
            adapter,
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            clock=lambda: "2026-08-10T00:00:00Z",
        )
        profile = service.synchronize(
            AdapterOperation.FETCH_ACCOUNT,
            "1001",
            limits=SyncLimits(1, 1, 20, 10),
        )
        artwork = service.synchronize(
            AdapterOperation.FETCH_POST,
            "2001",
            limits=SyncLimits(1, 1, 20, 10),
        )
        account_id = database.connection.execute(
            "SELECT account_id FROM accounts WHERE native_account_id = '1001'"
        ).fetchone()[0]
        post_id = database.connection.execute(
            "SELECT post_id FROM posts WHERE native_post_id = '2001'"
        ).fetchone()[0]
        occurrence = database.connection.execute(
            """SELECT source_key, media_index, role, mime_type, remote_url
               FROM media_occurrences WHERE post_id = ?""",
            (post_id,),
        ).fetchone()
        assert tuple(occurrence[:4]) == ("2001:p0", 0, "page", "image/jpeg")
        assert occurrence[4].startswith("https://i.pximg.net/")
        assert len(list_account_external_links(database, account_id)) == 2
        assert list_post_tags(database, post_id)[0]["observation_count"] == 1
        assert database.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
        assert profile.status == artwork.status == "complete"
        assert [request.url.host for request in requests] == [
            "app-api.pixiv.net",
            "app-api.pixiv.net",
        ]
