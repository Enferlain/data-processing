"""rule34.xxx instance of the gelbooru 0.2 engine: policy and captured contract.

The fixtures are live captures from https://api.rule34.xxx (2026-10-31,
maintainer-supplied credentials; credential values never appear in the
fixtures). The www host serves a CAPTCHA wall and the api host rejects
anonymous dapi requests, so this instance is credentials-required. Its notes
endpoint serves XML, matching the gelbooru r4y finding.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from media_catalog.adapters import AdapterOperation, AdapterRequest, ResponseEnvelope
from media_catalog.adapters.fixtures import load_fixture_suite
from media_catalog.adapters.gelbooru import (
    ADAPTER_VERSION,
    GELBOORU_INSTANCES,
    RULE34,
    RULE34_DAPI_SCHEMA_VERSION,
    GelbooruAdapter,
    GelbooruCredentials,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
SUITE = load_fixture_suite(FIXTURES / "rule34.json")
NOTES_XML = (FIXTURES / "rule34_notes_11899541.xml").read_text(encoding="utf-8")
NOW = "2026-10-31T00:00:00Z"


def test_family_registry_membership() -> None:
    assert set(GELBOORU_INSTANCES) == {"gelbooru", "safebooru", "rule34"}
    assert GELBOORU_INSTANCES["rule34"] is RULE34


def test_instance_policy_is_credentialed_on_the_api_host() -> None:
    assert RULE34.platform_key == "rule34"
    assert RULE34.base_url == "https://api.rule34.xxx"
    assert RULE34.host == "api.rule34.xxx"
    assert RULE34.dapi_credentials_required is True
    assert RULE34.user_id_env == "RULE34_USER_ID"
    assert RULE34.api_key_env == "RULE34_API_KEY"
    assert RULE34.dapi_schema_version == RULE34_DAPI_SCHEMA_VERSION == "rule34-json-v1"
    # Lookup stays undeclared until each strategy earns its own captured fixture.
    assert not tuple(RULE34.lookup_capabilities)


def test_captured_contract_normalizes_under_the_rule34_identity() -> None:
    case = SUITE.cases[0]
    adapter = GelbooruAdapter(RULE34, client=httpx.Client())
    page = adapter.normalize(
        ResponseEnvelope(
            provider="gelbooru",
            instance="rule34",
            operation=AdapterOperation.FETCH_POST,
            request_identity=case.request_identity,
            status_code=case.response.status_code,
            headers=dict(case.response.headers),
            payload=case.response.payload,
            observed_at=NOW,
            adapter_version=ADAPTER_VERSION,
            schema_version=RULE34_DAPI_SCHEMA_VERSION,
        )
    )
    expected = case.expected
    post = next(item for item in page.items if item.object_kind == "post")
    assert post.native_id == expected["post_ids"][0]
    assert post.data["platform"] == "rule34"
    # This engine generation declares no creation time and exposes `hash`, not
    # md5: both facts stay absent rather than being invented.
    assert post.data["created_at"] is None
    assert post.data["rating"] == expected["rating"]
    assert post.data["score"]["total"] == expected["score"]
    assert post.data["status"] == expected["status"]
    assert post.data["source"] == expected["source"]
    occurrence = next(item for item in page.items if item.object_kind == "media_occurrence")
    assert occurrence.data["declared_md5"] is None
    assert (occurrence.data["width"], occurrence.data["height"]) == (
        expected["width"],
        expected["height"],
    )
    assert [variant["role"] for variant in occurrence.data["variants"]] == expected["variants"]
    tags = [item for item in page.items if item.object_kind == "post_tag"]
    assert len(tags) == expected["tag_count"]


def test_wire_request_carries_credentials_only_in_the_query() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    adapter = GelbooruAdapter(
        RULE34,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        credentials=GelbooruCredentials(user_id="u", api_key="k"),
    )

    adapter.fetch(AdapterRequest(operation=AdapterOperation.FETCH_POST, target="19210742"))
    request = requests[0]
    assert request.url.host == "api.rule34.xxx"
    # Credential material rides the query per the dapi contract; the durable
    # identity the adapter derives must stay secret-free.
    assert "user_id=u" in str(request.url) and "api_key=k" in str(request.url)


def test_captured_notes_contract_parses_through_the_enrichment_parser() -> None:
    # Same server behavior the gelbooru r4y capture proved: the notes dapi
    # serves an XML document regardless of json=1, and the enrichment XML
    # parser is the contract consumer. The captured document (noted post
    # 11899541) must round-trip it with typed fields — including its
    # Ruby-style timestamps, which the strict parser ignores rather than
    # rejects.
    from media_catalog.remote_sync.enrichment import _parse_document, parse_notes

    assert NOTES_XML.startswith("<notes ")
    document = _parse_document(NOTES_XML.encode("utf-8"))
    notes = parse_notes(document, "11899541")
    assert notes is not None and len(notes) == 3
    first = next(note for note in notes if note["note_native_id"] == "201855")
    assert first["body"] == "This is the year!"
    assert (first["position_x"], first["position_y"], first["width"], first["height"]) == (
        86,
        1762,
        72,
        245,
    )
    assert first["version"] == 1
