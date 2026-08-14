from __future__ import annotations

import httpx

from media_catalog.adapters import (
    LookupPlanContext,
    LookupPlanItem,
    LookupQueryMaterial,
    LookupRequest,
    LookupStrategy,
)
from media_catalog.adapters.danbooru import AIBOORU, DANBOORU, DanbooruAdapter

NOW = "2026-08-10T00:00:00Z"


def _adapter(instance=DANBOORU, handler=None) -> DanbooruAdapter:
    if handler is None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[], request=request)

    return DanbooruAdapter(
        instance,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )


def test_lookup_contracts_are_closed_and_redacted() -> None:
    assert [strategy.value for strategy in LookupStrategy] == [
        "source_post_url",
        "external_post_id",
        "declared_md5",
        "verified_md5",
        "artist_exact_name",
        "artist_alias",
        "artist_text",
    ]
    material = LookupQueryMaterial(
        kind=LookupStrategy.SOURCE_POST_URL,
        values=("https://x.com/acme/status/1", "https://twitter.com/acme/status/1"),
        provenance_kind="post",
        provenance_id="seed-1",
    )
    assert material.material_digest == material.digest
    assert "x.com/acme" not in repr(material)
    assert "x.com/acme" not in str(material.as_dict())
    assert LookupQueryMaterial.from_json(material.to_json()) == material


def test_capabilities_are_instance_specific() -> None:
    assert set(DANBOORU.lookup_capabilities) == set(LookupStrategy)
    assert AIBOORU.lookup_capabilities.supports(LookupStrategy.SOURCE_POST_URL)
    assert AIBOORU.lookup_capabilities.supports(LookupStrategy.ARTIST_ALIAS)
    assert not AIBOORU.lookup_capabilities.supports(LookupStrategy.ARTIST_TEXT)
    alias = next(
        item
        for item in AIBOORU.lookup_capabilities.declarations
        if item.strategy is LookupStrategy.ARTIST_ALIAS
    )
    assert alias.result_kind == "attribution"


def test_lookup_plan_context_is_provider_neutral_and_preserves_identity() -> None:
    # OpenSpec task 5.1: the neutral planning context removes the hardcoded
    # Danbooru identity from the planner while reproducing the exact identity the
    # planner previously hardcoded, so existing DANBOORU/AIBOORU plan digests,
    # exclusions, and rendered requests are unchanged.
    cases = (
        (DANBOORU, "danbooru", "danbooru-json-v1"),
        (AIBOORU, "aibooru", "aibooru-json-v1"),
    )
    for instance, platform_key, schema_version in cases:
        context = instance.lookup_plan_context
        assert isinstance(context, LookupPlanContext)
        # provider and adapter_version are constant across the Danbooru family;
        # instance_key and schema_version are instance-specific.
        assert context.provider == "danbooru"
        assert context.instance_key == platform_key
        assert context.adapter_version == "danbooru-native-v1"
        assert context.schema_version == schema_version
        assert context.lookup_capabilities is instance.lookup_capabilities

    # The adapter declares the same provider identity as the neutral context.
    adapter = _adapter()
    assert adapter.provider_key == DANBOORU.lookup_plan_context.provider
    assert adapter.adapter_version == DANBOORU.lookup_plan_context.adapter_version

    # A plan item built from the neutral context must be byte-for-byte identical
    # to one built with the original hardcoded literals.  Any drift in
    # provider/instance/version identity fails here -- expected digests are not
    # relaxed to accept drift.
    material = LookupQueryMaterial(LookupStrategy.SOURCE_POST_URL, "https://x.com/acme/status/1")
    limits = {"requests": 3, "pages": 3, "results": 200, "seconds": 60}
    for instance, platform_key, schema_version in cases:
        context = instance.lookup_plan_context
        via_context = LookupPlanItem(
            provider=context.provider,
            instance=context.instance_key,
            strategy=material.strategy,
            query_digest=material.digest,
            limits=limits,
            seed_kind="post",
            seed_id="1",
            adapter_version=context.adapter_version,
            schema_version=context.schema_version,
        )
        via_literals = LookupPlanItem(
            provider="danbooru",
            instance=platform_key,
            strategy=material.strategy,
            query_digest=material.digest,
            limits=limits,
            seed_kind="post",
            seed_id="1",
            adapter_version="danbooru-native-v1",
            schema_version=schema_version,
        )
        assert via_context.digest == via_literals.digest
        assert via_context.to_json() == via_literals.to_json()


def test_lookup_request_uses_fixed_opaque_source_and_md5_queries() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    adapter = _adapter(handler=handler)
    source = LookupRequest(
        LookupStrategy.SOURCE_POST_URL,
        LookupQueryMaterial(
            LookupStrategy.SOURCE_POST_URL,
            "https://x.com/acme/status/1",
        ),
    )
    response = adapter.fetch_lookup(source)
    assert seen[0].url.path == "/posts.json"
    assert seen[0].url.params["tags"] == "source:https://x.com/acme/status/1"
    assert response.request_identity.startswith("lookup:")
    assert "x.com" not in response.request_identity

    md5 = LookupRequest(LookupStrategy.DECLARED_MD5, "0123456789abcdef0123456789abcdef")
    adapter.fetch_lookup(md5)
    assert seen[1].url.params["tags"] == "md5:0123456789abcdef0123456789abcdef"


def test_lookup_normalization_retains_post_facts_and_ordered_artist_leads() -> None:
    post = {
        "id": 8186581,
        "source": "https://twitter.com/acme/status/1",
        "md5": "072b69605a05873a2443626b7600ed69",
        "uploader_id": 17,
        "tag_string_artist": "artist_a",
        "tag_string_character": "",
        "tag_string_copyright": "",
        "tag_string_general": "",
        "tag_string_meta": "",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[post], request=request)

    adapter = _adapter(handler=handler)
    request = LookupRequest(LookupStrategy.SOURCE_POST_URL, "https://twitter.com/acme/status/1")
    page = adapter.normalize_lookup(adapter.fetch_lookup(request), request)
    assert page.record_count == 1
    assert page.results[0].result_kind == "post"
    assert page.results[0].native_id == "8186581"
    assert page.results[0].data["source"] == post["source"]
    assert page.results[0].data["declared_md5"] == post["md5"]
    assert any(item.object_kind == "post_participant" for item in page.results[0].items)

    artists = [
        {"id": 4, "name": "artist_a", "other_names": ["a"], "urls": []},
        {"id": 5, "name": "artist_ab", "other_names": [], "urls": []},
    ]
    artist_adapter = _adapter(handler=lambda req: httpx.Response(200, json=artists, request=req))
    artist_request = LookupRequest(LookupStrategy.ARTIST_TEXT, "artist")
    # Danbooru supports bounded wildcard text; AIBooru intentionally does not.
    artist_page = artist_adapter.normalize_lookup(
        artist_adapter.fetch_lookup(artist_request), artist_request
    )
    assert [result.native_id for result in artist_page.results] == ["4", "5"]
    assert [result.rank for result in artist_page.results] == [0, 1]
    assert all(result.result_kind == "attribution" for result in artist_page.results)
