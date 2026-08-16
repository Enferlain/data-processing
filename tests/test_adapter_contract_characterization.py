"""Characterization of the shared provider-neutral adapter boundary.

OpenSpec changes that add provider adapters require characterization of the
existing Danbooru/AIBooru/e621 behavior at the shared adapter boundary before a
new parallel provider is added.  These tests lock the neutral contract surface
(``fetch`` -> ``ResponseEnvelope`` -> ``normalize`` -> ``NormalizedPage``,
secret-free identities, typed outcomes, keyset continuations, and no media
requests) that the e621 adapter must mirror without changing Danbooru/AIBooru
behavior.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import (
    Adapter,
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    AdapterRequest,
    NormalizedPage,
    load_fixture_suite,
)
from media_catalog.adapters.danbooru import AIBOORU, DANBOORU, DanbooruAdapter
from media_catalog.adapters.e621 import E621, E621Adapter

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
NOW = "2026-08-12T00:00:00Z"


def _case(suite_name: str, case_name: str):
    suite = load_fixture_suite(FIXTURES / suite_name)
    return next(case for case in suite.cases if case.name == case_name)


def _adapter(instance=DANBOORU, handler=None) -> DanbooruAdapter:
    if handler is None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "unused"})

    return DanbooruAdapter(
        instance,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )


def _e621_adapter(handler=None) -> E621Adapter:
    if handler is None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "unused"})

    return E621Adapter(
        E621,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )


def test_danbooru_satisfies_the_neutral_adapter_protocol() -> None:
    adapter = _adapter()
    # The runtime-checkable Adapter protocol is the shared boundary e621 mirrors.
    assert isinstance(adapter, Adapter)
    assert adapter.provider_key == "danbooru"
    assert adapter.instance_key == DANBOORU.platform_key
    assert adapter.adapter_version and adapter.schema_version


def test_danbooru_fetch_envelope_is_secret_free_and_versioned() -> None:
    case = _case("danbooru.json", "post_with_attribution")
    body = json.loads(case.response.payload)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body, request=request)

    envelope = _adapter(handler=handler).fetch(AdapterRequest(AdapterOperation.FETCH_POST, "3001"))
    assert envelope.provider == "danbooru"
    assert envelope.instance == "danbooru"
    assert envelope.operation is AdapterOperation.FETCH_POST
    assert envelope.request_identity == "danbooru:fetch_post:3001"
    assert "authorization" not in envelope.headers
    assert envelope.adapter_version and envelope.schema_version


def test_danbooru_normalize_returns_page_with_top_level_post() -> None:
    page = _adapter().normalize(_case("danbooru.json", "post_with_attribution").response)
    assert isinstance(page, NormalizedPage)
    assert any(item.object_kind == "post" for item in page.items)
    assert page.record_count >= 1


def test_danbooru_keyset_continuation_renders_on_resume() -> None:
    page = _adapter().normalize(_case("danbooru.json", "post_listing_keyset").response)
    assert page.continuation is not None
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    _adapter(handler=handler).fetch(
        AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "artist_a", continuation=page.continuation
        )
    )
    assert requests[0].url.params["page"] == "b3001"


def test_aibooru_is_independent_of_danbooru() -> None:
    danbooru = _adapter().normalize(_case("danbooru.json", "post_with_attribution").response)
    aibooru = _adapter(AIBOORU).normalize(_case("aibooru.json", "compatible_post").response)
    danbooru_post = next(item for item in danbooru.items if item.object_kind == "post")
    aibooru_post = next(item for item in aibooru.items if item.object_kind == "post")
    assert danbooru_post.data["platform"] == "danbooru"
    assert aibooru_post.data["platform"] == "aibooru"


def test_danbooru_outcomes_are_typed_consistently() -> None:
    adapter = _adapter()
    # Deleted posts are marked in-band (normalized availability), not as a failure.
    deleted_page = adapter.normalize(_case("danbooru.json", "deleted_post").response)
    deleted_post = next(item for item in deleted_page.items if item.object_kind == "post")
    assert deleted_post.data["availability"] == "deleted"
    # Rate limiting surfaces as a typed failure outcome on the shared contract.
    with pytest.raises(AdapterFailure) as rate_limited:
        adapter.normalize(_case("danbooru.json", "rate_limited").response)
    assert rate_limited.value.outcome is AdapterOutcome.RATE_LIMITED


def test_danbooru_metadata_fetch_does_not_contact_media_hosts() -> None:
    case = _case("danbooru.json", "post_with_attribution")
    body = json.loads(case.response.payload)
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        return httpx.Response(200, json=body)

    adapter = _adapter(handler=handler)
    adapter.normalize(adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "3001")))
    assert requested_hosts == ["danbooru.donmai.us"]


def test_e621_satisfies_the_same_versioned_adapter_boundary() -> None:
    adapter = _e621_adapter()
    assert isinstance(adapter, Adapter)
    assert adapter.provider_key == "e621"
    assert adapter.instance_key == E621.platform_key
    assert adapter.adapter_version and adapter.schema_version


def test_e621_listing_continuation_remains_target_scoped_and_opaque() -> None:
    page = _e621_adapter().normalize(_case("e621.json", "listing_first").response)
    assert page.continuation is not None
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    _e621_adapter(handler).fetch(
        AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "artist_a",
            continuation=page.continuation,
        )
    )
    assert requests[0].url.host == "e621.net"
    assert requests[0].url.params["tags"] == "artist_a"
    assert requests[0].url.params["page"] == "b5101"


def test_e621_metadata_normalization_never_contacts_returned_media_hosts() -> None:
    case = _case("e621.json", "normal_post")
    body = json.loads(case.response.payload)
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        return httpx.Response(200, json=body)

    adapter = _e621_adapter(handler)
    page = adapter.normalize(adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "5001")))
    occurrence = next(item for item in page.items if item.object_kind == "media_occurrence")
    assert occurrence.data["remote_url"].startswith("https://static1.e621.net/")
    assert requested_hosts == ["e621.net"]
