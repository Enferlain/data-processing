from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import (
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    AdapterRequest,
    Continuation,
    NormalizedPage,
    ResponseEnvelope,
    load_fixture_suite,
)
from media_catalog.adapters.e621 import (
    ADAPTER_VERSION,
    CONTINUATION_VERSION,
    E621,
    SCHEMA_VERSION,
    E621Adapter,
    E621Credentials,
    E621Instance,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
NOW = "2026-08-13T00:00:00Z"
SUITE = load_fixture_suite(FIXTURES / "e621.json")


def _case(name: str):
    return next(case for case in SUITE.cases if case.name == name)


def _adapter(handler=None, credentials=None) -> E621Adapter:
    if handler is None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "unused"})

    return E621Adapter(
        E621,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        credentials=credentials,
        clock=lambda: NOW,
    )


def _by_kind(page: NormalizedPage) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for item in page.items:
        grouped.setdefault(item.object_kind, []).append(item)
    return grouped


# ---------------------------------------------------------------------------
# Request policy: exact shapes, identification, pacing, and privacy (tasks 2.3/2.4)
# ---------------------------------------------------------------------------


def test_post_and_attribution_requests_render_exact_paths_with_user_agent() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": 1, "tags": {}, "file": {}, "flags": {}})

    adapter = _adapter(handler=handler)
    adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "5001"))
    adapter.fetch(AdapterRequest(AdapterOperation.FETCH_ATTRIBUTION, "6001"))

    assert requests[0].url == "https://e621.net/posts/5001.json"
    assert requests[1].url == "https://e621.net/artists/6001.json"
    assert all(request.headers["user-agent"] == E621.user_agent for request in requests)
    assert all("authorization" not in {k.lower() for k in request.headers} for request in requests)


def test_tag_and_alias_requests_render_bounded_search_parameters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    adapter = _adapter(handler=handler)
    adapter.fetch(AdapterRequest(AdapterOperation.FETCH_TAG, "fox"))
    adapter.fetch(AdapterRequest(AdapterOperation.FETCH_TAG_ALIAS, "fox_tail"))

    # Bracketed search keys may be percent-encoded in the rendered query string;
    # assert the path, the bounded limit, and the non-secret value admission.
    assert requests[0].url.path == "/tags.json"
    assert requests[0].url.params["limit"] == "1"
    assert "search" in str(requests[0].url) and "fox" in str(requests[0].url)
    assert requests[1].url.path == "/tag_aliases.json"
    assert requests[1].url.params["limit"] == "1"
    assert "antecedent_name" in str(requests[1].url) and "fox_tail" in str(requests[1].url)


def test_listing_first_page_has_no_cursor_and_ceiling_is_320() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    adapter = _adapter(handler=handler)
    adapter.fetch(AdapterRequest(AdapterOperation.LIST_ACCOUNT_POSTS, "artist_a"))

    assert requests[0].url.path == "/posts.json"
    assert requests[0].url.params["tags"] == "artist_a"
    assert requests[0].url.params["limit"] == "320"
    assert "page" not in requests[0].url.params


def test_credentials_use_ephemeral_basic_auth_and_never_enter_durable_output() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"x-rate-limit": "9;w=1", "set-cookie": "private"},
            json={"id": 5001, "tags": {}, "file": {}, "flags": {}},
        )

    credentials = E621Credentials("example-user", "sentinel-secret")
    adapter = _adapter(handler=handler, credentials=credentials)
    envelope = adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "5001"))

    assert requests[0].headers["authorization"].startswith("Basic ")
    assert envelope.request_identity == "e621:fetch_post:5001"
    assert envelope.headers == {"content-type": "application/json", "x-rate-limit": "9;w=1"}
    public = repr(credentials) + repr(adapter) + repr(envelope)
    assert "sentinel-secret" not in public
    assert "private" not in public


def test_environment_credentials_require_both_references() -> None:
    assert E621Credentials.from_environment(E621, {}) is None
    with pytest.raises(ValueError, match="configure both"):
        E621Credentials.from_environment(E621, {E621.username_env: "user"})
    loaded = E621Credentials.from_environment(
        E621, {E621.username_env: "user", E621.api_key_env: "secret"}
    )
    assert loaded is not None
    assert "secret" not in repr(loaded)


def test_pacing_floor_and_page_size_cannot_be_weakened() -> None:
    with pytest.raises(ValueError, match="minimum interval"):
        E621Instance(minimum_interval_seconds=0.5)
    with pytest.raises(ValueError, match="page size"):
        E621Instance(page_size=321)
    with pytest.raises(ValueError, match="page size"):
        E621Instance(page_size=0)

    strict = E621Instance(minimum_interval_seconds=2.0)
    assert strict.minimum_interval_seconds == 2.0
    adapter = _adapter()
    assert adapter.minimum_interval_seconds == 1.0
    assert E621.page_size == 320


def test_default_tests_never_contact_media_hosts() -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        return httpx.Response(200, json=json.loads(_case("normal_post").response.payload))

    adapter = _adapter(handler=handler)
    envelope = adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "5001"))
    adapter.normalize(envelope)
    assert requested_hosts == ["e621.net"]


# ---------------------------------------------------------------------------
# Post, media, tag, and attribution normalization (tasks 3.1/3.2/3.3)
# ---------------------------------------------------------------------------


def test_post_normalization_keeps_nested_facts_separate() -> None:
    page = _adapter().normalize(_case("normal_post").response)
    by_kind = _by_kind(page)

    post = by_kind["post"][0]
    assert post.native_id == "5001"
    assert post.data["rating"] == "s"
    assert post.data["availability"] == "available"
    assert post.data["score"] == {"up": 20, "down": 2, "total": 18}
    assert post.data["fav_count"] == 12
    assert post.data["pools"] == [77001]
    assert post.data["description_present"] is False

    assert [item.native_id for item in by_kind["account"]] == ["42"]
    assert by_kind["post_participant"][0].data["role"] == "uploader"

    media = by_kind["media_occurrence"][0].data
    assert media["declared_md5"] == "abcdef0123456789abcdef0123456789"
    assert "verified_md5" not in media

    refs = by_kind["external_reference"]
    assert {ref.data["value"] for ref in refs} == {
        "https://www.pixiv.net/artworks/9001",
        "https://example.com/source",
    }
    assert all(ref.data["evidence_only"] is True for ref in refs)

    assert by_kind["post_relation"][0].data == {
        "platform": "e621",
        "source_post_id": "4999",
        "target_post_id": "5001",
        "relation_type": "parent_of",
    }
    # Artist-category tags are retained as post-tag attribution, not account
    # attribution items; the uploader is retained only in the uploader role.
    assert "attribution" not in by_kind


def test_three_representations_exist_and_original_owns_declared_facts() -> None:
    media = _by_kind(_adapter().normalize(_case("normal_post").response))["media_occurrence"][0]
    variants = {variant["role"]: variant for variant in media.data["variants"]}
    assert [variant["role"] for variant in media.data["variants"]] == [
        "original",
        "sample",
        "preview",
    ]
    assert media.data["declared_md5"] == "abcdef0123456789abcdef0123456789"
    assert media.data["declared_file_size"] == 234567
    assert media.data["width"] == 1600 and media.data["height"] == 1200
    # Sample and preview carry only their own representation facts.
    for role in ("sample", "preview"):
        assert "declared_md5" not in variants[role]
        assert "declared_file_size" not in variants[role]
    assert variants["sample"]["url"] != media.data["remote_url"]


def test_dynamic_categories_preserve_native_identity_and_never_collapse_to_general() -> None:
    tags = _by_kind(_adapter().normalize(_case("normal_post").response))["post_tag"]
    by_native = {
        tag.data["native_category"]: tag
        for tag in tags
        if tag.data["spelling"] in {"solo", "canine", "fox", "background_story"}
    }
    # Known category maps losslessly.
    assert by_native["general"].data["category"] == "general"
    # Unfamiliar categories map to neutral unknown and keep their native label.
    for native in ("species", "lore"):
        assert by_native[native].data["category"] == "unknown"
        assert by_native[native].data["native_category"] == native
    assert {tag.data["category"] for tag in tags} >= {"general", "unknown"}
    assert all(
        tag.data["category"] != "general"
        for tag in tags
        if tag.data["native_category"] in {"species", "lore"}
    )


def test_deleted_post_retained_with_deleted_availability() -> None:
    page = _adapter().normalize(_case("deleted_post").response)
    by_kind = _by_kind(page)
    post = by_kind["post"][0]
    assert post.data["availability"] == "deleted"
    assert post.data["status"] == "deleted"
    # Remaining provider facts stay queryable; media is retained as deleted.
    assert by_kind["media_occurrence"][0].data["availability"] == "deleted"


def test_nondeleted_null_url_marked_unavailable_not_deleted() -> None:
    page = _adapter().normalize(_case("null_media_post").response)
    by_kind = _by_kind(page)
    assert by_kind["post"][0].data["availability"] == "available"
    media = by_kind["media_occurrence"][0].data
    assert media["availability"] == "unavailable"
    assert media["remote_url"] is None
    original = next(v for v in media["variants"] if v["role"] == "original")
    assert original["url"] is None
    assert original["availability"] == "unavailable"


def test_video_post_media_type_is_detected() -> None:
    media = _by_kind(_adapter().normalize(_case("video_post").response))["media_occurrence"][0]
    assert media.data["mime_type"] == "video/webm"
    assert media.data["availability"] == "available"


def test_artist_record_is_attribution_and_never_an_account() -> None:
    page = _adapter().normalize(_case("artist_record").response)
    assert [item.object_kind for item in page.items] == ["attribution"]
    artist = page.items[0]
    assert artist.native_id == "6001"
    assert artist.data["account"] is False
    assert artist.data["other_names"] == ["artist-a", "alt_name"]
    assert artist.data["group_name"] == "group_x"
    assert artist.data["urls"] == [
        "https://www.pixiv.net/users/1001",
        "https://example.com/artist_a",
    ]


def test_tag_record_preserves_native_category_and_count() -> None:
    page = _adapter().normalize(_case("tag_record").response)
    assert [item.object_kind for item in page.items] == ["tag"]
    tag = page.items[0].data
    assert tag["native_category"] == "species"
    assert tag["native_category_code"] == 5
    assert tag["category"] == "unknown"
    assert tag["post_count"] == 4321


def test_active_alias_is_typed_evidence() -> None:
    page = _adapter().normalize(_case("active_alias").response)
    assert [item.object_kind for item in page.items] == ["tag_alias"]
    alias = page.items[0].data
    assert alias["antecedent"] == "fox_tail"
    assert alias["consequent"] == "fox"
    assert alias["status"] == "active"
    assert alias["active"] is True


# ---------------------------------------------------------------------------
# Bounded older-ID listing with opaque b<ID> continuations (task 3.4)
# ---------------------------------------------------------------------------


def test_listing_continues_toward_older_ids_with_opaque_boundary() -> None:
    first = _adapter().normalize(_case("listing_first").response)
    assert [item.native_id for item in first.items if item.object_kind == "post"] == [
        "5102",
        "5101",
    ]
    assert first.continuation is not None
    assert first.continuation.value["page"] == "b5101"
    assert first.continuation.value["direction"] == "older"

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=json.loads(_case("listing_continuation").response.payload))

    adapter = _adapter(handler=handler)
    second = adapter.normalize(
        adapter.fetch(
            AdapterRequest(
                AdapterOperation.LIST_ACCOUNT_POSTS,
                "artist_a",
                continuation=first.continuation,
            )
        )
    )
    assert requests[0].url.params["page"] == "b5101"
    assert requests[0].url.params["limit"] == "320"
    assert second.continuation is not None
    assert second.continuation.value["page"] == "b5100"


def test_invalid_continuation_is_rejected_before_any_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    adapter = _adapter(handler=handler)

    def fetch_with(continuation: Continuation) -> None:
        adapter.fetch(
            AdapterRequest(
                AdapterOperation.LIST_ACCOUNT_POSTS, "artist_a", continuation=continuation
            )
        )

    with pytest.raises(ValueError, match="adapter or version"):
        fetch_with(
            Continuation("danbooru", E621.schema_version, {"page": "b5101", "direction": "older"})
        )
    with pytest.raises(ValueError, match="adapter or version"):
        fetch_with(Continuation("e621", "e621-json-v2", {"page": "b5101", "direction": "older"}))
    with pytest.raises(ValueError, match="older IDs"):
        fetch_with(
            Continuation(
                "e621",
                CONTINUATION_VERSION,
                {"page": "b5101", "direction": "newer"},
            )
        )
    with pytest.raises(ValueError, match="b<ID>"):
        fetch_with(
            Continuation(
                "e621",
                CONTINUATION_VERSION,
                {"page": "5101", "direction": "older"},
            )
        )
    assert requests == []


# ---------------------------------------------------------------------------
# Adapter contract behavior (task 3.5)
# ---------------------------------------------------------------------------


def test_reobservation_is_idempotent() -> None:
    adapter = _adapter()
    first = adapter.normalize(_case("normal_post").response)
    second = adapter.normalize(_case("normal_post").response)
    assert first.items == second.items
    assert first.continuation == second.continuation


def test_unknown_field_is_retained_in_raw_and_absent_from_normalized_items() -> None:
    body = json.loads(_case("normal_post").response.payload)
    body["future_unknown_field"] = {"surprise": True}
    envelope = ResponseEnvelope(
        provider="e621",
        instance="e621",
        operation=AdapterOperation.FETCH_POST,
        request_identity="e621:fetch_post:5001",
        status_code=200,
        headers={"content-type": "application/json"},
        payload=json.dumps(body).encode(),
        observed_at=NOW,
        adapter_version=ADAPTER_VERSION,
        schema_version=SCHEMA_VERSION,
    )
    page = _adapter().normalize(envelope)
    assert b"future_unknown_field" in envelope.payload
    for item in page.items:
        assert "future_unknown_field" not in item.data


def test_malformed_required_field_raises_typed_failure() -> None:
    with pytest.raises(AdapterFailure) as error:
        _adapter().normalize(_case("malformed_post").response)
    assert error.value.outcome is AdapterOutcome.MALFORMED_RESPONSE


@pytest.mark.parametrize(
    ("field", "value"),
    (("score", {"up": "bad"}), ("flags", {"deleted": "false"}), ("pools", [True])),
)
def test_malformed_nested_post_facts_raise_typed_failure(field: str, value: object) -> None:
    body = json.loads(_case("normal_post").response.payload)
    body[field] = value
    envelope = ResponseEnvelope(
        provider="e621",
        instance="e621",
        operation=AdapterOperation.FETCH_POST,
        request_identity="e621:fetch_post:5001",
        status_code=200,
        headers={"content-type": "application/json"},
        payload=json.dumps(body).encode(),
        observed_at=NOW,
        adapter_version=ADAPTER_VERSION,
        schema_version=SCHEMA_VERSION,
        request_target="5001",
    )
    with pytest.raises(AdapterFailure) as error:
        _adapter().normalize(envelope)
    assert error.value.outcome is AdapterOutcome.MALFORMED_RESPONSE


def test_typed_outcomes_for_status_codes() -> None:
    adapter = _adapter()

    def expect(name: str, outcome: AdapterOutcome, *, status: int | None = None) -> None:
        with pytest.raises(AdapterFailure) as error:
            adapter.normalize(_case(name).response)
        assert error.value.outcome is outcome
        if status is not None:
            assert error.value.status_code == status

    expect("unknown_post", AdapterOutcome.UNAVAILABLE, status=404)
    expect("authentication_required", AdapterOutcome.AUTHENTICATION_REQUIRED, status=401)
    expect("access_denied", AdapterOutcome.AUTHORIZATION_DENIED, status=403)
    expect("rate_limited", AdapterOutcome.RATE_LIMITED, status=429)
    expect("transient_provider", AdapterOutcome.TRANSIENT_PROVIDER, status=503)


def test_no_implicit_pool_note_or_media_fan_out() -> None:
    page = _adapter().normalize(_case("normal_post").response)
    by_kind = _by_kind(page)
    # Pools are retained as post-level ids only; no pool/note/media fan-out items.
    assert "pool" not in by_kind
    assert "note" not in by_kind
    assert len(by_kind.get("media_occurrence", [])) == 1
    assert by_kind["post"][0].data["pools"] == [77001]


def test_unknown_id_does_not_invent_post_or_occurrence() -> None:
    with pytest.raises(AdapterFailure) as error:
        _adapter().normalize(_case("unknown_post").response)
    assert error.value.outcome is AdapterOutcome.UNAVAILABLE
