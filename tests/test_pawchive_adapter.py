"""Pawchive (kemono API family) adapter: registry policy and captured contract.

Fixtures are live anonymous captures from pawchive.pw /api/v1 (2026-11-01),
the only maintained instance of the family (maintainer statement
2026-10-31).  The contract surprises the captures pinned: flat post detail
(no {post, attachments} envelope), bare-array listing pages, string ids,
``{name, path}`` media entries with expiring signed temp URLs the catalog
never retains, and brace-string tags.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import AdapterOperation, AdapterRequest, ResponseEnvelope
from media_catalog.adapters.contracts import Continuation
from media_catalog.adapters.fixtures import load_fixture_suite
from media_catalog.adapters.pawchive import (
    ADAPTER_VERSION,
    CONTINUATION_VERSION,
    MAX_RESPONSE_BYTES,
    MINIMUM_INTERVAL_SECONDS,
    PAWCHIVE,
    PAWCHIVE_INSTANCES,
    SCHEMA_VERSION,
    PawchiveAdapter,
    PawchiveInstance,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
SUITE = load_fixture_suite(FIXTURES / "pawchive.json")
NOW = "2026-11-01T00:00:00Z"


def _case(name: str):
    return next(case for case in SUITE.cases if case.name == name)


def _normalize(case, request_target: str):
    adapter = PawchiveAdapter(client=httpx.Client())
    return adapter.normalize(
        ResponseEnvelope(
            provider="pawchive",
            instance="pawchive",
            operation=case.operation,
            request_identity=case.request_identity,
            status_code=case.response.status_code,
            headers=dict(case.response.headers),
            payload=case.response.payload,
            observed_at=NOW,
            adapter_version=ADAPTER_VERSION,
            schema_version=SCHEMA_VERSION,
            request_target=request_target,
        )
    )


def test_family_registry_and_instance_policy() -> None:
    assert set(PAWCHIVE_INSTANCES) == {"pawchive"}
    assert PAWCHIVE_INSTANCES["pawchive"] is PAWCHIVE
    assert PAWCHIVE.base_url == "https://pawchive.pw"
    assert PAWCHIVE.schema_version == SCHEMA_VERSION == "pawchive-json-v1"
    # Anonymous metadata API; no lookup strategy is declared until each one
    # earns its own captured fixture.
    assert not tuple(PAWCHIVE.lookup_capabilities)
    # Fixed 50-entry pages and multi-megabyte listing pages need headroom.
    assert MINIMUM_INTERVAL_SECONDS == 1.0
    assert MAX_RESPONSE_BYTES == 4 * 1024 * 1024


def test_instance_policy_floors_are_enforced() -> None:
    with pytest.raises(ValueError, match="lowercase platform key"):
        PawchiveInstance(platform_key="Pawchive")
    with pytest.raises(ValueError, match="canonical HTTPS base URL"):
        PawchiveInstance(base_url="https://elsewhere.example", host="pawchive.pw")


def test_captured_profile_normalizes_under_the_pawchive_identity() -> None:
    case = _case("profile_patreon_75232195")
    page = _normalize(case, "account:patreon:75232195")
    expected = case.expected
    account = next(item for item in page.items if item.object_kind == "account")
    assert account.native_id == expected["account_ids"][0]
    assert account.data["name"] == expected["name"]
    assert account.data["service"] == expected["service"]
    assert account.data["public_id"] == expected["public_id"]
    assert account.data["platform"] == "pawchive"


def test_captured_listing_normalizes_and_short_pages_have_no_continuation() -> None:
    case = _case("posts_patreon_75232195_o0")
    page = _normalize(case, "listing:patreon:75232195:0")
    expected = case.expected
    posts = [item for item in page.items if item.object_kind == "post"]
    assert [post.native_id for post in posts] == expected["post_ids"]
    assert page.continuation is None
    # Every listed post still carries its creator participant and occurrences.
    assert any(item.object_kind == "post_participant" for item in page.items)
    assert any(item.object_kind == "media_occurrence" for item in page.items)


def test_full_listing_page_rolls_the_offset_forward() -> None:
    # A full 50-entry page (synthetic count on top of the captured shape) is
    # the continuation trigger; the next offset derives from the durable
    # request target, not client state.
    case = _case("posts_patreon_75232195_o0")
    body = json.loads(case.response.payload)
    padded = [body[0]] * 50
    adapter = PawchiveAdapter(client=httpx.Client())
    page = adapter.normalize(
        ResponseEnvelope(
            provider="pawchive",
            instance="pawchive",
            operation=AdapterOperation.LIST_ACCOUNT_POSTS,
            request_identity=case.request_identity,
            status_code=200,
            headers=dict(case.response.headers),
            payload=json.dumps(padded).encode(),
            observed_at=NOW,
            adapter_version=ADAPTER_VERSION,
            schema_version=SCHEMA_VERSION,
            request_target="listing:patreon:75232195:100",
        )
    )
    assert page.continuation is not None
    assert page.continuation.adapter == "pawchive"
    assert page.continuation.version == CONTINUATION_VERSION
    assert dict(page.continuation.value) == {"offset": 150}


def test_replayed_full_page_without_a_request_target_is_terminal() -> None:
    # Offline replay rebuilds envelopes without request targets; a full
    # replayed page must normalize to a terminal page (gelbooru listing
    # precedent) instead of failing a valid payload.
    case = _case("posts_patreon_75232195_o0")
    body = json.loads(case.response.payload)
    padded = [body[0]] * 50
    adapter = PawchiveAdapter(client=httpx.Client())
    page = adapter.normalize(
        ResponseEnvelope(
            provider="pawchive",
            instance="pawchive",
            operation=AdapterOperation.LIST_ACCOUNT_POSTS,
            request_identity=case.request_identity,
            status_code=200,
            headers=dict(case.response.headers),
            payload=json.dumps(padded).encode(),
            observed_at=NOW,
            adapter_version=ADAPTER_VERSION,
            schema_version=SCHEMA_VERSION,
            request_target="replay:posts:patreon:75232195",
        )
    )
    assert page.continuation is None
    assert len([item for item in page.items if item.object_kind == "post"]) == 50


def test_captured_post_detail_normalizes_with_occurrences_and_thumbnails() -> None:
    case = _case("post_patreon_75232195_70439020")
    page = _normalize(case, "post:patreon:75232195:70439020")
    expected = case.expected
    post = next(item for item in page.items if item.object_kind == "post")
    assert post.native_id == expected["post_ids"][0]
    assert post.data["platform"] == "pawchive"
    assert post.data["service"] == "patreon"
    assert post.data["user_id"] == expected["creator_account_id"]
    assert post.data["canonical_url"] == ("https://pawchive.pw/patreon/user/75232195/post/70439020")
    participant = next(item for item in page.items if item.object_kind == "post_participant")
    assert (participant.data["role"], participant.data["account_id"]) == (
        "creator",
        expected["creator_account_id"],
    )
    occurrences = [item for item in page.items if item.object_kind == "media_occurrence"]
    assert [occurrence.data["role"] for occurrence in occurrences] == expected["occurrence_roles"]
    primary = occurrences[0]
    assert primary.data["path"] == expected["primary_path"]
    assert primary.data["remote_url"] is None  # expiring signed URLs are never retained
    assert primary.data["variants"] == [
        {
            "role": "thumbnail",
            "url": expected["thumbnail_base"] + expected["primary_path"],
            "preview_only": False,
        }
    ]
    tags = [item for item in page.items if item.object_kind == "post_tag"]
    assert len(tags) == expected["tag_count"]


def test_wire_requests_target_the_captured_endpoints() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    adapter = PawchiveAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    adapter.fetch(
        AdapterRequest(operation=AdapterOperation.FETCH_POST, target="patreon:75232195:70439020")
    )
    assert str(requests[0].url) == (
        "https://pawchive.pw/api/v1/patreon/user/75232195/post/70439020"
    )
    adapter.fetch(
        AdapterRequest(operation=AdapterOperation.FETCH_ACCOUNT, target="patreon:75232195")
    )
    assert str(requests[1].url) == "https://pawchive.pw/api/v1/patreon/user/75232195/profile"
    adapter.fetch(
        AdapterRequest(
            operation=AdapterOperation.LIST_ACCOUNT_POSTS,
            target="patreon:75232195",
            continuation=None,
        )
    )
    assert str(requests[2].url) == "https://pawchive.pw/api/v1/patreon/user/75232195/posts?o=0"
    adapter.fetch(
        AdapterRequest(
            operation=AdapterOperation.LIST_ACCOUNT_POSTS,
            target="patreon:75232195",
            continuation=Continuation(
                adapter="pawchive",
                version=CONTINUATION_VERSION,
                value={"offset": 50},
            ),
        )
    )
    assert str(requests[3].url) == "https://pawchive.pw/api/v1/patreon/user/75232195/posts?o=50"
    for request in requests:
        assert request.headers["user-agent"].startswith("data-processing-tools/")
        # The captured anti-asset-pipeline header rides every API request.
        assert request.headers["accept"] == "text/css"


def test_oversized_response_fails_typed_before_parsing() -> None:
    from media_catalog.adapters import AdapterFailure, AdapterOutcome

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))

    adapter = PawchiveAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(AdapterFailure) as raised:
        adapter.fetch(
            AdapterRequest(
                operation=AdapterOperation.FETCH_POST, target="patreon:75232195:70439020"
            )
        )
    assert raised.value.outcome is AdapterOutcome.RESPONSE_TOO_LARGE


def test_malformed_targets_and_continuations_fail_before_network() -> None:
    from media_catalog.adapters import AdapterFailure, AdapterOutcome
    from media_catalog.adapters.pawchive.adapter import _account_target, _post_target

    with pytest.raises(ValueError, match="service:user-id"):
        _account_target("patreon")
    with pytest.raises(ValueError, match="service:user-id"):
        _account_target("patreon:")
    with pytest.raises(ValueError, match="service:user-id:post-id"):
        _post_target("patreon:75232195")
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    adapter = PawchiveAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ValueError, match="incompatible pawchive listing continuation"):
        adapter.fetch(
            AdapterRequest(
                operation=AdapterOperation.LIST_ACCOUNT_POSTS,
                target="patreon:75232195",
                continuation=Continuation(
                    adapter="gelbooru",
                    version=CONTINUATION_VERSION,
                    value={"offset": 50},
                ),
            )
        )
    with pytest.raises(AdapterFailure) as raised:
        adapter.fetch(AdapterRequest(operation=AdapterOperation.FETCH_TAG, target="anything"))
    assert raised.value.outcome is AdapterOutcome.MALFORMED_RESPONSE
    assert calls == []


def test_tags_contract_brace_string_and_null() -> None:
    from media_catalog.adapters.pawchive.adapter import _parse_tags

    assert _parse_tags("{Benefits,Douki-Chan,NSFW}") == ["Benefits", "Douki-Chan", "NSFW"]
    assert _parse_tags(None) == []
    assert _parse_tags("{}") == []
    with pytest.raises(Exception, match="tags must be text or null"):
        _parse_tags(["not", "text"])


def test_zoneless_provider_timestamps_qualify_as_utc() -> None:
    # Kemono serializes naive stamps; the catalog's temporal layer requires
    # offsets. The repo's established interpretation (gelbooru HTML adapter)
    # qualifies zoneless provider stamps as UTC.
    from media_catalog.adapters.pawchive.adapter import _timestamp

    assert _timestamp("2022-08-12T19:42:29") == "2022-08-12T19:42:29Z"
    assert _timestamp("2026-10-31T15:33:47.339-04:00") == "2026-10-31T19:33:47.339000Z"
    assert _timestamp(None) is None
    assert _timestamp("not-a-time") is None
