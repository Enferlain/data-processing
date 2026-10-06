"""Gelbooru bounded reverse-lookup contract tests (add-gelbooru-bounded-lookup).

These tests cover the capability declaration, provider-neutral planning context,
exact credentialed DAPI request rendering, digest-only identities, fail-closed
rejection of undeclared strategies and malformed tokens, pid continuation, and
evidence-shaped result normalization through the shared lookup service.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import (
    AdapterFailure,
    AdapterOutcome,
    LookupContinuation,
    LookupPlanContext,
    LookupQueryMaterial,
    LookupRequest,
    LookupStrategy,
)
from media_catalog.adapters.gelbooru import (
    ADAPTER_VERSION,
    DAPI_SCHEMA_VERSION,
    GELBOORU,
    PROVIDER_KEY,
    GelbooruAdapter,
    GelbooruCredentials,
)
from media_catalog.candidate_lookup import (
    CandidateLookupService,
    LookupLimits,
    plan_candidate_lookup,
)
from media_catalog.database import CatalogDatabase
from media_catalog.records import PostRecord
from media_catalog.writer import CatalogWriter

NOW = "2026-10-06T00:00:00Z"
CREDENTIALS = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
MD5 = "0123456789abcdef0123456789abcdef"

_DECLARED = (
    LookupStrategy.SOURCE_POST_URL,
    LookupStrategy.DECLARED_MD5,
    LookupStrategy.VERIFIED_MD5,
)


def _adapter(handler=None) -> GelbooruAdapter:
    if handler is None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[], request=request)

    return GelbooruAdapter(
        GELBOORU,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        credentials=CREDENTIALS,
        clock=lambda: NOW,
    )


def _capture():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[], request=request)

    return requests, handler


def _lookup_post_body(*, source: str = "https://x.com/acme/status/1") -> dict[str, object]:
    return {
        "@attributes": {"limit": 200, "offset": 0, "count": 1},
        "post": [
            {
                "id": 12370900,
                "created_at": "2026-01-01 00:00:00",
                "creator_id": 42,
                "owner": "sample_owner",
                "rating": "general",
                "status": "active",
                "source": source,
                "md5": MD5,
                "tags": "artist_a solo",
                "file_url": "https://sample.gelbooru.com/images/sample/sample.jpg",
                "preview_url": "https://sample.gelbooru.com/thumbnails/sample/thumb.jpg",
                "width": 100,
                "height": 80,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Capability declaration and neutral planning context
# ---------------------------------------------------------------------------


def test_lookup_capabilities_declare_exact_three_strategies() -> None:
    capabilities = GELBOORU.lookup_capabilities
    assert set(capabilities) == set(_DECLARED)
    assert LookupStrategy.EXTERNAL_POST_ID not in capabilities
    assert LookupStrategy.ARTIST_EXACT_NAME not in capabilities
    assert LookupStrategy.ARTIST_TEXT not in capabilities
    by_strategy = {item.strategy: item for item in capabilities.declarations}
    for strategy in _DECLARED:
        assert by_strategy[strategy].result_kind == "post"
        assert by_strategy[strategy].pagination == "page"

    adapter = _adapter()
    assert adapter.lookup_capabilities is GELBOORU.lookup_capabilities


def test_lookup_plan_context_is_gelbooru_identity() -> None:
    context = GELBOORU.lookup_plan_context
    assert isinstance(context, LookupPlanContext)
    assert context.provider == PROVIDER_KEY == "gelbooru"
    assert context.instance_key == "gelbooru"
    assert context.adapter_version == ADAPTER_VERSION
    assert context.schema_version == DAPI_SCHEMA_VERSION
    assert context.lookup_capabilities is GELBOORU.lookup_capabilities

    adapter = _adapter()
    assert adapter.lookup_plan_context == GELBOORU.lookup_plan_context
    assert adapter.lookup_plan_context.lookup_capabilities is GELBOORU.lookup_capabilities


# ---------------------------------------------------------------------------
# Bounded request rendering
# ---------------------------------------------------------------------------


def test_lookup_renders_exact_source_and_md5_post_queries() -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)

    source = LookupRequest(LookupStrategy.SOURCE_POST_URL, "https://x.com/acme/status/1")
    envelope = adapter.fetch_lookup(source)
    source_params = dict(requests[0].url.params)
    assert requests[0].url.path == "/index.php"
    assert source_params["tags"] == "source:https://x.com/acme/status/1"
    assert source_params["limit"] == "100"
    assert source_params["pid"] == "0"
    assert source_params["user_id"] == "12345"
    assert envelope.lookup_strategy is LookupStrategy.SOURCE_POST_URL
    assert envelope.lookup_query_digest == source.material.digest
    assert envelope.lookup_material is source.material
    assert envelope.request_identity.startswith("lookup:")

    declared = LookupRequest(
        LookupStrategy.DECLARED_MD5,
        LookupQueryMaterial(LookupStrategy.DECLARED_MD5, MD5),
    )
    adapter.fetch_lookup(declared)
    assert dict(requests[1].url.params)["tags"] == f"md5:{MD5}"

    verified = LookupRequest(
        LookupStrategy.VERIFIED_MD5,
        LookupQueryMaterial(LookupStrategy.VERIFIED_MD5, MD5),
    )
    adapter.fetch_lookup(verified)
    assert dict(requests[2].url.params)["tags"] == f"md5:{MD5}"


def test_lookup_identity_is_digest_only_and_alias_sensitive() -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)

    material = LookupQueryMaterial(
        LookupStrategy.SOURCE_POST_URL,
        ("https://x.com/acme/status/1", "https://twitter.com/acme/status/1"),
    )
    first = adapter.fetch_lookup(LookupRequest(LookupStrategy.SOURCE_POST_URL, material))
    page = adapter.normalize_lookup(first, LookupRequest(LookupStrategy.SOURCE_POST_URL, material))
    assert page.continuation is not None
    assert page.continuation.alias_index == 1
    assert page.continuation.page is None

    second = adapter.fetch_lookup(
        LookupRequest(LookupStrategy.SOURCE_POST_URL, material, continuation=page.continuation)
    )

    assert len(requests) == 2
    assert dict(requests[1].url.params)["tags"] == ("source:https://twitter.com/acme/status/1")
    assert "acme" not in first.request_identity
    assert first.request_identity != second.request_identity
    assert first.lookup_query_digest == second.lookup_query_digest


def test_lookup_full_page_advances_pid_under_bounds() -> None:
    requests: list[httpx.Request] = []
    posts = [
        {"id": index, "created_at": "2026-01-01 00:00:00", "tags": "solo"} for index in range(1, 3)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json={"@attributes": {"limit": 2, "offset": 0, "count": 2}, "post": posts}
        )

    adapter = _adapter(handler=handler)
    request = LookupRequest(LookupStrategy.DECLARED_MD5, MD5, limit=2)
    envelope = adapter.fetch_lookup(request)
    page = adapter.normalize_lookup(envelope, request)

    assert dict(requests[0].url.params)["limit"] == "2"
    assert page.continuation is not None
    assert page.continuation.page == "2"
    assert page.continuation.alias_index == 0


# ---------------------------------------------------------------------------
# Fail-closed behavior
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "strategy",
    (
        LookupStrategy.EXTERNAL_POST_ID,
        LookupStrategy.ARTIST_EXACT_NAME,
        LookupStrategy.ARTIST_ALIAS,
        LookupStrategy.ARTIST_TEXT,
    ),
)
def test_undeclared_strategy_is_rejected_before_request(strategy: LookupStrategy) -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)
    with pytest.raises(ValueError, match="does not support lookup strategy"):
        adapter.fetch_lookup(LookupRequest(strategy, "material"))
    assert requests == []


@pytest.mark.parametrize(
    "value",
    ("https://example.test/path*", "https://example.test/a path"),
)
def test_non_exact_source_syntax_fails_closed_before_request(value: str) -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)
    with pytest.raises(ValueError, match="one exact source token"):
        adapter.fetch_lookup(LookupRequest(LookupStrategy.SOURCE_POST_URL, value))
    assert requests == []


def test_non_hex_md5_fails_closed_at_material_construction() -> None:
    # The neutral material contract rejects non-hex MD5 values before any
    # adapter code or request exists; the adapter's token guard is the
    # defense-in-depth layer behind it.
    with pytest.raises(ValueError):
        LookupQueryMaterial(LookupStrategy.DECLARED_MD5, "not-a-hash")


def test_missing_credentials_fail_closed_before_request() -> None:
    adapter = GelbooruAdapter(GELBOORU, client=httpx.Client(), clock=lambda: NOW)
    with pytest.raises(ValueError, match="DAPI requests require credentials"):
        adapter.fetch_lookup(LookupRequest(LookupStrategy.DECLARED_MD5, MD5))


def test_incompatible_lookup_continuation_is_rejected_before_request() -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)
    material = LookupQueryMaterial(LookupStrategy.DECLARED_MD5, MD5)
    bad_adapter = LookupContinuation(
        "danbooru", DAPI_SCHEMA_VERSION, LookupStrategy.DECLARED_MD5, material.digest, "0", 0
    )
    bad_page = LookupContinuation(
        PROVIDER_KEY, DAPI_SCHEMA_VERSION, LookupStrategy.DECLARED_MD5, material.digest, "next", 0
    )
    bad_index = LookupContinuation(
        PROVIDER_KEY, DAPI_SCHEMA_VERSION, LookupStrategy.DECLARED_MD5, material.digest, None, 1
    )

    def fetch_with(cursor: LookupContinuation) -> None:
        adapter.fetch_lookup(
            LookupRequest(LookupStrategy.DECLARED_MD5, material, continuation=cursor)
        )

    with pytest.raises(ValueError, match="incompatible Gelbooru lookup continuation"):
        fetch_with(bad_adapter)
    with pytest.raises(ValueError, match="pid offset"):
        fetch_with(bad_page)
    with pytest.raises(ValueError, match="alias index is out of range"):
        fetch_with(bad_index)
    assert requests == []


# ---------------------------------------------------------------------------
# Result normalization
# ---------------------------------------------------------------------------


def test_lookup_result_normalizes_evidence_without_conclusions() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_lookup_post_body())

    adapter = _adapter(handler=handler)
    request = LookupRequest(LookupStrategy.SOURCE_POST_URL, "https://x.com/acme/status/1")
    envelope = adapter.fetch_lookup(request)
    page = adapter.normalize_lookup(envelope, request)

    assert page.record_count == 1
    result = page.results[0]
    assert result.result_kind == "post"
    assert result.native_id == "12370900"
    data = result.data
    assert data["platform"] == "gelbooru"
    assert data["query_kind"] == "source_post_url"
    assert data["query"] == "https://x.com/acme/status/1"
    assert data["source"] == "https://x.com/acme/status/1"
    assert data["declared_md5"] == MD5
    assert data["uploader_id"] == 42
    assert data["uploader_name"] == "sample_owner"
    assert data["availability"] == "available"
    assert data["lookup_provenance"]["strategy"] == "source_post_url"
    kinds = {item.object_kind for item in result.items}
    assert {"post", "post_tag", "media_occurrence"} <= kinds


def test_lookup_count_zero_envelope_yields_clean_empty_page() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"@attributes": {"limit": 200, "offset": 0, "count": 0}})

    adapter = _adapter(handler=handler)
    request = LookupRequest(LookupStrategy.DECLARED_MD5, MD5)
    page = adapter.normalize_lookup(adapter.fetch_lookup(request), request)
    assert page.results == ()
    assert page.continuation is None


def test_lookup_error_envelope_fails_typed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "Invalid API key"})

    adapter = _adapter(handler=handler)
    request = LookupRequest(LookupStrategy.DECLARED_MD5, MD5)
    envelope = adapter.fetch_lookup(request)
    with pytest.raises(AdapterFailure) as failure:
        adapter.normalize_lookup(envelope, request)
    assert failure.value.outcome is AdapterOutcome.MALFORMED_RESPONSE


def test_lookup_envelope_never_leaks_query_material_or_credentials() -> None:
    _requests, handler = _capture()
    adapter = _adapter(handler=handler)
    material = LookupQueryMaterial(LookupStrategy.DECLARED_MD5, MD5)
    envelope = adapter.fetch_lookup(LookupRequest(LookupStrategy.DECLARED_MD5, material))

    public = repr(CREDENTIALS) + repr(adapter) + repr(envelope)
    assert "abcdef1234567890" not in public
    assert MD5 not in repr(envelope)
    assert envelope.request_identity.startswith("lookup:")
    assert MD5 not in envelope.request_identity


# ---------------------------------------------------------------------------
# Service-level execution and offline planning
# ---------------------------------------------------------------------------


def _seed_post(database: CatalogDatabase) -> int:
    with database.transaction():
        return (
            CatalogWriter(database)
            .upsert_post(
                PostRecord(
                    "x",
                    "1837662117949800671",
                    NOW,
                    canonical_url="https://x.com/thiccwithaq/status/1837662117949800671",
                )
            )
            .id
        )


def test_lookup_run_lands_pending_candidate_without_deciding(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        body = _lookup_post_body(
            source="https://twitter.com/thiccwithaq/status/1837662117949800671"
        )
        return httpx.Response(200, json=body)

    with CatalogDatabase(path) as database:
        post_id = _seed_post(database)
        service = CandidateLookupService(
            database,
            _adapter(handler=handler),
            minimum_interval_seconds=0,
            maximum_retries=0,
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
        )
        plan = service.plan(
            f"post:{post_id}",
            (LookupStrategy.SOURCE_POST_URL,),
            limits=LookupLimits(2, 2, 10, 30),
        )
        assert plan.provider == "gelbooru"
        assert len(plan.items) == 1
        result = service.execute(plan)[0]
        assert result.status == "complete"
        assert result.result_count == 2  # one result per URL alias request
        assert (
            database.connection.execute("SELECT COUNT(*) FROM post_match_candidates").fetchone()[0]
            == 1
        )
        candidate = database.connection.execute(
            "SELECT relation_kind, current_state FROM post_match_candidates"
        ).fetchone()
        assert tuple(candidate) == ("sourced_from", "pending")
        assert (
            database.connection.execute("SELECT COUNT(*) FROM post_candidate_decisions").fetchone()[
                0
            ]
            == 0
        )
        assert len(requested) == 2
        assert "x.com" in requested[0]
        assert "twitter.com" in requested[1]


def test_plan_supports_gelbooru_offline_without_credentials(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        post_id = _seed_post(database)

    def fail_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    socket_default = socket.socket.connect
    socket.socket.connect = fail_connect
    try:
        plan = plan_candidate_lookup(
            path,
            f"post:{post_id}",
            GELBOORU,
            (LookupStrategy.SOURCE_POST_URL, LookupStrategy.ARTIST_EXACT_NAME),
            limits=LookupLimits(1, 1, 10, 30),
        )
    finally:
        socket.socket.connect = socket_default

    assert plan.provider == "gelbooru"
    assert len(plan.items) == 1
    assert plan.items[0].material.values == (
        "https://x.com/thiccwithaq/status/1837662117949800671",
        "https://twitter.com/thiccwithaq/status/1837662117949800671",
    )
    assert plan.exclusions == (
        {"strategy": "artist_exact_name", "reason": "unsupported_provider_capability"},
    )
    assert json.dumps(plan.as_dict())  # serializable public plan


def test_lookup_rejects_strategy_gelbooru_never_declares(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path) as database:
        post_id = _seed_post(database)
    plan = plan_candidate_lookup(
        path,
        f"post:{post_id}",
        GELBOORU,
        (LookupStrategy.EXTERNAL_POST_ID,),
        limits=LookupLimits(1, 1, 10, 30),
    )
    assert plan.items == ()
    assert plan.exclusions == (
        {"strategy": "external_post_id", "reason": "unsupported_provider_capability"},
    )
