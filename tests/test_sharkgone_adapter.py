"""Sharkgone Danbooru-family instance (bead data-processing-9ds, change
``add-sharkgone-instance``): the operator's personal booru as an independent
cross-search source — artist surfaces omitted, never danbooru failover."""

from __future__ import annotations

from pathlib import Path

import httpx

from media_catalog.adapter_factory import adapter_construction
from media_catalog.adapters.contracts import (
    LookupQueryMaterial,
    LookupRequest,
    LookupStrategy,
)
from media_catalog.adapters.danbooru import SHARKGONE, DanbooruAdapter, DanbooruCredentials
from media_catalog.adapters.fixtures import load_fixture_suite
from media_catalog.crosscheck import PROVIDERS as CROSSCHECK_PROVIDERS
from media_catalog.discovery.planning import LOOKUP_PROVIDERS
from media_catalog.link_resolution import RESOLVED_PLATFORMS, resolve_link
from media_catalog.links import BOORU_INSTANCES, recognize_url

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
SUITE = load_fixture_suite(FIXTURES / "sharkgone.json")
LOOKUP_SUITE = load_fixture_suite(FIXTURES / "sharkgone_lookup.json")
MD5_HIT = next(case for case in LOOKUP_SUITE.cases if case.name == "md5_hit")
NOW = "2026-11-22T00:00:00Z"


def test_instance_policy_and_credentials() -> None:
    assert SHARKGONE.platform_key == "sharkgone"
    assert SHARKGONE.base_url == "https://booru.sharkgone.com"
    assert SHARKGONE.schema_version == "sharkgone-json-v1"
    assert (SHARKGONE.login_env, SHARKGONE.api_key_env) == (
        "SHARKGONE_LOGIN",
        "SHARKGONE_API_KEY",
    )
    # Anonymous requests work: fully absent credentials resolve to None.
    assert DanbooruCredentials.from_environment(SHARKGONE, {}) is None


def test_declares_post_strategies_only() -> None:
    strategies = SHARKGONE.lookup_capabilities.strategies
    assert strategies == frozenset(
        {
            LookupStrategy.SOURCE_POST_URL,
            LookupStrategy.EXTERNAL_POST_ID,
            LookupStrategy.DECLARED_MD5,
            LookupStrategy.VERIFIED_MD5,
        }
    )
    assert not SHARKGONE.lookup_capabilities.supports(LookupStrategy.ARTIST_EXACT_NAME)
    assert not SHARKGONE.lookup_capabilities.supports(LookupStrategy.ARTIST_ALIAS)
    assert SHARKGONE.enumeration_capabilities.declarations == ()
    context = SHARKGONE.lookup_plan_context
    assert (context.provider, context.instance_key) == ("danbooru", "sharkgone")


def test_registration_across_seams() -> None:
    assert "sharkgone" in CROSSCHECK_PROVIDERS
    assert SHARKGONE in LOOKUP_PROVIDERS
    assert BOORU_INSTANCES["booru.sharkgone.com"] == "sharkgone"
    assert "sharkgone" in RESOLVED_PLATFORMS
    from media_catalog.cli_commands.maintenance import _REPROCESS_PROVIDERS

    assert "sharkgone" in _REPROCESS_PROVIDERS
    from media_catalog.records.common import SOURCE_OPERATIONS

    assert SOURCE_OPERATIONS["sharkgone"] is not None
    factory, interval = adapter_construction("sharkgone")
    assert interval == SHARKGONE.minimum_interval_seconds
    client = httpx.Client()
    try:
        adapter = factory(client)
        assert isinstance(adapter, DanbooruAdapter)
        assert adapter.instance_key == "sharkgone"
    finally:
        client.close()


def test_sharkgone_links_recognize_and_resolve() -> None:
    recognized = recognize_url("https://booru.sharkgone.com/posts/213")
    assert recognized is not None
    reference = recognized.reference
    assert reference is not None
    assert reference.platform == "sharkgone"
    assert reference.object_kind == "post"
    assert reference.identifier_kind == "stable_id"
    resolved = resolve_link("https://booru.sharkgone.com/posts/213")
    assert resolved.platform == "sharkgone"
    assert resolved.operation == "fetch_post"
    assert resolved.target == "213"


def test_captured_contract_normalizes_over_the_wire() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            content=MD5_HIT.response.payload,
            headers={"content-type": "application/json"},
        )

    adapter = DanbooruAdapter(
        SHARKGONE,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        credentials=None,
    )
    request = LookupRequest(
        LookupStrategy.DECLARED_MD5, LookupQueryMaterial(LookupStrategy.DECLARED_MD5, "b" * 32)
    )
    page = adapter.normalize_lookup(adapter.fetch_lookup(request), request)
    assert page.record_count == 1
    result = page.results[0]
    assert result.native_id == "213"
    assert result.data["platform"] == "sharkgone"
    assert str(requests[-1].url).startswith("https://booru.sharkgone.com/posts.json")
    assert requests[-1].url.params["tags"] == f"md5:{'b' * 32}"
    assert requests[-1].url.params.get("login") is None


def test_captured_metadata_contract_normalizes() -> None:
    case = next(case for case in SUITE.cases if case.name == "post_213")
    adapter = DanbooruAdapter(SHARKGONE, client=httpx.Client(), credentials=None)
    page = adapter.normalize(case.response)
    post_ids = {item.native_id for item in page.items if item.object_kind == "post"}
    assert post_ids == {"213"}


def test_fixture_provenance() -> None:
    manifest_text = (FIXTURES / "sharkgone.json").read_text()
    assert "2026-11-22" in manifest_text
    assert "anonymous" in manifest_text
    body = MD5_HIT.response.payload
    assert b"password" not in body and b"api_key" not in body
