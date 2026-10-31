from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import AdapterOperation, AdapterRequest, ResponseEnvelope
from media_catalog.adapters.e621 import (
    ADAPTER_VERSION,
    E621,
    E621_INSTANCES,
    E926,
    E621Adapter,
    E621Instance,
)
from media_catalog.adapters.fixtures import load_fixture_suite

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
SUITE = load_fixture_suite(FIXTURES / "e926.json")
NOW = "2026-10-31T00:00:00Z"


def test_family_registry_and_instance_policy() -> None:
    assert set(E621_INSTANCES) == {"e621", "e926"}
    assert E621_INSTANCES["e926"] is E926
    assert E926.platform_key == "e926"
    assert E926.base_url == "https://e926.net"
    assert E926.schema_version == "e926-json-v1"
    # The family shares the e621 credential references and pacing floors;
    # both instances accept anonymous requests.
    assert E926.username_env == E621.username_env
    assert E926.api_key_env == E621.api_key_env
    assert E926.minimum_interval_seconds == E621.minimum_interval_seconds


def test_instance_platform_keys_must_be_lowercase_slugs() -> None:
    with pytest.raises(ValueError, match="lowercase"):
        E621Instance(platform_key="E926")


def test_instance_requires_declared_https_host() -> None:
    with pytest.raises(ValueError, match="HTTPS base URL on its declared host"):
        E621Instance(platform_key="e926", base_url="https://elsewhere.example", host="e926.net")


def test_captured_contract_normalizes_under_the_e926_identity() -> None:
    case = SUITE.cases[0]
    adapter = E621Adapter(E926, client=httpx.Client())
    page = adapter.normalize(
        ResponseEnvelope(
            provider="e621",
            instance="e926",
            operation=AdapterOperation.FETCH_POST,
            request_identity=case.request_identity,
            status_code=case.response.status_code,
            headers=dict(case.response.headers),
            payload=case.response.payload,
            observed_at=NOW,
            adapter_version=ADAPTER_VERSION,
            schema_version="e926-json-v1",
        )
    )
    expected = case.expected
    post = next(item for item in page.items if item.object_kind == "post")
    assert post.native_id == expected["post_ids"][0]
    assert post.data["platform"] == "e926"
    assert post.data["canonical_url"] == expected["canonical_url"]
    assert post.data["rating"] == expected["rating"]
    occurrence = next(item for item in page.items if item.object_kind == "media_occurrence")
    assert occurrence.data["declared_md5"] == expected["declared_md5"]
    assert [variant["role"] for variant in occurrence.data["variants"]] == expected["variant_roles"]
    # e926 serves categorized tags; species has no neutral category and lands
    # as unknown while the native category is retained as evidence.
    tags = [item for item in page.items if item.object_kind == "post_tag"]
    assert len(tags) == expected["tag_count"]
    assert {tag.data["category"] for tag in tags} == set(expected["categories"])
    species = [tag for tag in tags if tag.data["native_category"] == "species"]
    assert species and all(tag.data["category"] == "unknown" for tag in species)
    participants = [item for item in page.items if item.object_kind == "post_participant"]
    assert [(p.data["role"], p.data["account_id"]) for p in participants] == [
        ("uploader", expected["uploader_ids"][0])
    ]


def test_wrapped_and_bare_post_bodies_both_normalize() -> None:
    # The capture stores the wire as served ({"post": {...}}); the historical
    # e621 fixture shape stores the bare post. The adapter accepts both so
    # neither captured contract is silently invalidated by a wire change.
    case = SUITE.cases[0]
    wrapped = case.response.payload
    bare = json.dumps(json.loads(wrapped)["post"]).encode()
    adapter = E621Adapter(E926, client=httpx.Client())
    for payload in (wrapped, bare):
        page = adapter.normalize(
            ResponseEnvelope(
                provider="e621",
                instance="e926",
                operation=AdapterOperation.FETCH_POST,
                request_identity=case.request_identity,
                status_code=200,
                headers=dict(case.response.headers),
                payload=payload,
                observed_at=NOW,
                adapter_version=ADAPTER_VERSION,
                schema_version="e926-json-v1",
            )
        )
        assert [i.native_id for i in page.items if i.object_kind == "post"] == ["6823045"]


def test_wire_request_targets_the_e926_host() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"post": {}})

    adapter = E621Adapter(E926, client=httpx.Client(transport=httpx.MockTransport(handler)))
    adapter.fetch(AdapterRequest(operation=AdapterOperation.FETCH_POST, target="6823045"))
    assert requests[0].url.host == "e926.net"
    assert str(requests[0].url) == "https://e926.net/posts/6823045.json"


def test_e926_declares_no_lookup_capabilities_yet() -> None:
    # The family ships e926 with the metadata contract only; each bounded
    # lookup strategy must earn its own e926 captured fixture first (the
    # safebooru/rule34 precedent), so nothing is plannable against e926 yet.
    assert not tuple(E926.lookup_capabilities)
    assert tuple(E621.lookup_capabilities)


def test_wrapped_form_also_normalizes_under_the_e621_identity() -> None:
    # The live e621.net wire serves the same single-key wrapper (verified
    # 2026-10-31), so the canonical instance must accept it too — not only
    # the historical bare-post shape its archived fixture pins.
    case = SUITE.cases[0]
    adapter = E621Adapter(E621, client=httpx.Client())
    page = adapter.normalize(
        ResponseEnvelope(
            provider="e621",
            instance="e621",
            operation=AdapterOperation.FETCH_POST,
            request_identity=f"e621:fetch_post:{case.target}",
            status_code=200,
            headers=dict(case.response.headers),
            payload=case.response.payload,
            observed_at=NOW,
            adapter_version=ADAPTER_VERSION,
            schema_version="e621-json-v1",
        )
    )
    assert [i.native_id for i in page.items if i.object_kind == "post"] == ["6823045"]
