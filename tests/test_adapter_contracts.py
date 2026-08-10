from __future__ import annotations

import json
from pathlib import Path

import pytest

from media_catalog.adapters import (
    AdapterOperation,
    AdapterOutcome,
    Continuation,
    NormalizedItem,
    NormalizedPage,
    ResponseEnvelope,
    load_fixture_suite,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"


def test_adapter_contract_values_are_stable_and_continuations_round_trip() -> None:
    assert [operation.value for operation in AdapterOperation] == [
        "fetch_account",
        "fetch_post",
        "list_account_posts",
        "fetch_attribution",
    ]
    assert {outcome.value for outcome in AdapterOutcome} >= {
        "success",
        "authentication_required",
        "rate_limited",
        "malformed_response",
        "budget_exhausted",
    }
    continuation = Continuation("pixiv", "v1", {"offset": 2})
    assert Continuation.from_json(continuation.to_json()) == continuation


def test_page_record_count_budgets_top_level_entities_not_child_metadata() -> None:
    page = NormalizedPage(
        (
            NormalizedItem("post", "1", {}),
            NormalizedItem("account", "2", {}),
            NormalizedItem("post_tag", "1:tag", {}),
            NormalizedItem("media_occurrence", "1:p0", {}),
            NormalizedItem("external_reference", "1:source", {}),
        )
    )
    assert page.record_count == 2


def test_response_envelope_rejects_secret_bearing_identity_and_headers() -> None:
    common = {
        "provider": "pixiv",
        "instance": "pixiv",
        "operation": AdapterOperation.FETCH_POST,
        "status_code": 200,
        "payload": b"{}",
        "observed_at": "2026-08-10T00:00:00Z",
        "adapter_version": "v1",
        "schema_version": "v1",
    }
    with pytest.raises(ValueError, match="secret-bearing parameter"):
        ResponseEnvelope(request_identity="pixiv:api_key=sentinel", headers={}, **common)
    with pytest.raises(ValueError, match="secret-bearing header"):
        ResponseEnvelope(
            request_identity="pixiv:fetch_post:1",
            headers={"Authorization": "Bearer sentinel"},
            **common,
        )


def test_redacted_fixture_suites_cover_required_contract_cases() -> None:
    pixiv = load_fixture_suite(FIXTURES / "pixiv.json")
    danbooru = load_fixture_suite(FIXTURES / "danbooru.json")
    aibooru = load_fixture_suite(FIXTURES / "aibooru.json")
    oracle = load_fixture_suite(FIXTURES / "gallery_dl_1_32_2.json")

    assert {case.name for case in pixiv.cases} >= {
        "profile",
        "single_page_artwork",
        "multi_page_artwork",
        "ugoira",
        "artwork_listing_page",
        "restricted_artwork",
        "authentication_required",
    }
    assert {case.name for case in danbooru.cases} >= {
        "post_with_attribution",
        "artist_record",
        "post_listing_keyset",
        "deleted_post",
        "rate_limited",
    }
    assert {case.name for case in aibooru.cases} == {
        "compatible_post",
        "incompatible_shape",
    }
    assert "2e88d6ae29780dbed02e4a5172a1aa0a1b1c91b5" in oracle.manifest.adapter_version


def test_fixtures_are_json_only_and_contain_no_secret_or_media_payload_markers() -> None:
    forbidden = (
        "refresh_token",
        "access_token",
        "api_key",
        "authorization",
        "set-cookie",
        "data:image/",
        "base64,",
    )
    for path in sorted(FIXTURES.glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        json.loads(raw)
        lowered = raw.lower()
        assert not any(marker in lowered for marker in forbidden), path
        assert path.stat().st_size < 20_000
