"""Focused e621 lookup contract tests (OpenSpec tasks 5.2/5.3).

These tests cover capability declaration, the provider-neutral planning context,
bounded fixed request rendering, secret-free request identity/material, injected
transport + UA/auth reuse, fail-closed rejection of ``ARTIST_TEXT`` and
unsupported external platforms, continuation admission, and conservative result
normalization/interpretation.
"""

from __future__ import annotations

import httpx
import pytest

from media_catalog.adapters import (
    AdapterFailure,
    LookupContinuation,
    LookupPlanContext,
    LookupQueryMaterial,
    LookupRequest,
    LookupStrategy,
    NormalizedPage,
)
from media_catalog.adapters.e621 import (
    ADAPTER_VERSION,
    E621,
    PROVIDER_KEY,
    SCHEMA_VERSION,
    E621Adapter,
    E621Credentials,
)
from media_catalog.candidate_lookup.interpretation import LookupInterpreter
from media_catalog.database import CatalogDatabase
from media_catalog.records import PostRecord, RawRecord
from media_catalog.remote_sync.persistence import NormalizedPageWriter
from media_catalog.writer import CatalogWriter

NOW = "2026-08-13T00:00:00Z"

_POST_STRATEGIES = (
    LookupStrategy.SOURCE_POST_URL,
    LookupStrategy.EXTERNAL_POST_ID,
    LookupStrategy.DECLARED_MD5,
    LookupStrategy.VERIFIED_MD5,
)
_ARTIST_STRATEGIES = (LookupStrategy.ARTIST_EXACT_NAME, LookupStrategy.ARTIST_ALIAS)
# Declared exact contract: six strategies, never ARTIST_TEXT.
_DECLARED = (*_POST_STRATEGIES, *_ARTIST_STRATEGIES)


def _adapter(handler=None, credentials=None) -> E621Adapter:
    if handler is None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[], request=request)

    return E621Adapter(
        E621,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        credentials=credentials,
        clock=lambda: NOW,
    )


def _capture():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[], request=request)

    return requests, handler


# ---------------------------------------------------------------------------
# Capability declaration and neutral planning context
# ---------------------------------------------------------------------------


def test_lookup_capabilities_declare_exact_six_strategies_and_exclude_text() -> None:
    capabilities = E621.lookup_capabilities
    assert set(capabilities) == set(_DECLARED)
    assert LookupStrategy.ARTIST_TEXT not in capabilities
    assert not capabilities.supports(LookupStrategy.ARTIST_TEXT)

    by_strategy = {item.strategy: item for item in capabilities.declarations}
    for strategy in _POST_STRATEGIES:
        assert by_strategy[strategy].result_kind == "post"
    for strategy in _ARTIST_STRATEGIES:
        assert by_strategy[strategy].result_kind == "attribution"
    for declaration in capabilities.declarations:
        assert declaration.pagination == "keyset"

    adapter = _adapter()
    assert adapter.lookup_capabilities is E621.lookup_capabilities


def test_lookup_plan_context_is_e621_identity() -> None:
    context = E621.lookup_plan_context
    assert isinstance(context, LookupPlanContext)
    assert context.provider == "e621"
    assert context.instance_key == "e621"
    assert context.adapter_version == ADAPTER_VERSION == "e621-native-v1"
    assert context.schema_version == SCHEMA_VERSION == "e621-json-v1"
    assert context.lookup_capabilities is E621.lookup_capabilities

    adapter = _adapter()
    assert adapter.provider_key == PROVIDER_KEY == context.provider
    assert adapter.adapter_version == context.adapter_version
    assert adapter.schema_version == context.schema_version


# ---------------------------------------------------------------------------
# Bounded fixed request rendering
# ---------------------------------------------------------------------------


def test_lookup_renders_bounded_source_url_and_md5_post_queries() -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)

    source = LookupRequest(LookupStrategy.SOURCE_POST_URL, "https://x.com/acme/status/1")
    envelope = adapter.fetch_lookup(source)
    assert requests[0].url.path == "/posts.json"
    assert dict(requests[0].url.params)["tags"] == "source:https://x.com/acme/status/1"
    assert dict(requests[0].url.params)["limit"] == "200"
    assert envelope.operation.value == "fetch_post"
    assert envelope.request_identity.startswith("lookup:")
    assert "x.com" not in envelope.request_identity
    assert envelope.lookup_strategy is LookupStrategy.SOURCE_POST_URL
    assert envelope.lookup_query_digest == source.material.digest
    assert envelope.lookup_material is source.material

    md5 = LookupRequest(LookupStrategy.DECLARED_MD5, "0123456789abcdef0123456789abcdef")
    adapter.fetch_lookup(md5)
    assert dict(requests[1].url.params)["tags"] == "md5:0123456789abcdef0123456789abcdef"

    verified = LookupRequest(
        LookupStrategy.VERIFIED_MD5,
        LookupQueryMaterial(LookupStrategy.VERIFIED_MD5, "abcdef0123456789abcdef0123456789"),
    )
    adapter.fetch_lookup(verified)
    assert dict(requests[2].url.params)["tags"] == "md5:abcdef0123456789abcdef0123456789"


def test_lookup_external_post_id_renders_exact_pixiv_source_query() -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)

    material = LookupQueryMaterial(LookupStrategy.EXTERNAL_POST_ID, "9001", platform="pixiv")
    adapter.fetch_lookup(LookupRequest(LookupStrategy.EXTERNAL_POST_ID, material))

    assert requests[0].url.path == "/posts.json"
    assert dict(requests[0].url.params)["tags"] == "source:https://www.pixiv.net/artworks/9001"


def test_lookup_artist_strategies_use_exact_metadata_not_fuzzy_text() -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)

    artist = LookupRequest(LookupStrategy.ARTIST_EXACT_NAME, "artist_a")
    artist_envelope = adapter.fetch_lookup(artist)
    assert requests[0].url.path == "/tags.json"
    assert dict(requests[0].url.params)["search[name]"] == "artist_a"
    assert dict(requests[0].url.params)["limit"] == "1"
    assert "*" not in str(requests[0].url)
    assert artist_envelope.operation.value == "fetch_attribution"

    alias = LookupRequest(LookupStrategy.ARTIST_ALIAS, "artist_a")
    adapter.fetch_lookup(alias)
    assert requests[1].url.path == "/tag_aliases.json"
    alias_params = dict(requests[1].url.params)
    assert alias_params["search[antecedent_name]"] == "artist_a"
    assert alias_params["search[status]"] == "active"
    assert alias_params["limit"] == "1"


def test_lookup_identity_is_digest_only_and_stable() -> None:
    adapter = _adapter()
    material = LookupQueryMaterial(LookupStrategy.SOURCE_POST_URL, "https://x.com/acme/status/1")
    first = adapter.fetch_lookup(LookupRequest(LookupStrategy.SOURCE_POST_URL, material))
    second = adapter.fetch_lookup(LookupRequest(LookupStrategy.SOURCE_POST_URL, material))
    assert first.request_identity == second.request_identity
    assert first.request_identity.startswith("lookup:")
    assert all(token not in first.request_identity for token in ("acme", "x.com", "status"))


# ---------------------------------------------------------------------------
# Injected transport, UA/auth reuse, and privacy
# ---------------------------------------------------------------------------


def test_lookup_reuses_injected_transport_user_agent_and_auth() -> None:
    requests, handler = _capture()
    credentials = E621Credentials("example-user", "sentinel-secret")
    adapter = _adapter(handler=handler, credentials=credentials)
    adapter.fetch_lookup(
        LookupRequest(LookupStrategy.DECLARED_MD5, "0123456789abcdef0123456789abcdef")
    )

    assert len(requests) == 1
    assert requests[0].headers["user-agent"] == E621.user_agent
    assert requests[0].headers["accept"] == "application/json"
    assert requests[0].headers["authorization"].startswith("Basic ")


def test_lookup_envelope_never_leaks_secrets_or_query_material() -> None:
    _requests, handler = _capture()
    credentials = E621Credentials("example-user", "sentinel-secret")
    adapter = _adapter(handler=handler, credentials=credentials)
    material = LookupQueryMaterial(LookupStrategy.SOURCE_POST_URL, "https://x.com/acme/status/1")
    envelope = adapter.fetch_lookup(LookupRequest(LookupStrategy.SOURCE_POST_URL, material))

    public = repr(credentials) + repr(adapter) + repr(envelope)
    assert "sentinel-secret" not in public
    assert "acme" not in repr(envelope)
    assert envelope.request_identity.startswith("lookup:")
    assert "acme" not in envelope.request_identity
    # The private material is retained for normalization but is repr-suppressed.
    assert envelope.lookup_material is material


# ---------------------------------------------------------------------------
# Fail-closed behavior
# ---------------------------------------------------------------------------


def test_artist_text_is_rejected_before_any_request() -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)
    with pytest.raises(ValueError, match="does not support lookup strategy"):
        adapter.fetch_lookup(LookupRequest(LookupStrategy.ARTIST_TEXT, "artist"))
    assert requests == []


def test_unsupported_external_platform_fails_closed_before_request() -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)
    material = LookupQueryMaterial(LookupStrategy.EXTERNAL_POST_ID, "1", platform="twitter")
    with pytest.raises(ValueError, match="external platform"):
        adapter.fetch_lookup(LookupRequest(LookupStrategy.EXTERNAL_POST_ID, material))
    assert requests == []


@pytest.mark.parametrize(
    "source",
    ("https://example.test/path*", "https://example.test/a path"),
)
def test_non_exact_source_syntax_fails_closed_before_request(source: str) -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)
    with pytest.raises(ValueError, match="one exact source token"):
        adapter.fetch_lookup(LookupRequest(LookupStrategy.SOURCE_POST_URL, source))
    assert requests == []


def test_non_numeric_external_post_id_fails_closed_before_request() -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)
    material = LookupQueryMaterial(LookupStrategy.EXTERNAL_POST_ID, "not-an-id", platform="pixiv")
    with pytest.raises(ValueError, match="positive numeric id"):
        adapter.fetch_lookup(LookupRequest(LookupStrategy.EXTERNAL_POST_ID, material))
    assert requests == []


# ---------------------------------------------------------------------------
# Continuation admission
# ---------------------------------------------------------------------------


def test_lookup_continuation_page_is_rendered_after_validation() -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)
    material = LookupQueryMaterial(LookupStrategy.SOURCE_POST_URL, "https://x.com/acme/status/1")
    cursor = LookupContinuation(
        PROVIDER_KEY,
        SCHEMA_VERSION,
        LookupStrategy.SOURCE_POST_URL,
        material.digest,
        "b5101",
        0,
    )
    adapter.fetch_lookup(
        LookupRequest(LookupStrategy.SOURCE_POST_URL, material, continuation=cursor)
    )
    assert dict(requests[0].url.params)["page"] == "b5101"


def test_incompatible_lookup_continuation_is_rejected_before_request() -> None:
    requests, handler = _capture()
    adapter = _adapter(handler=handler)
    material = LookupQueryMaterial(LookupStrategy.SOURCE_POST_URL, "https://x.com/acme/status/1")
    bad_adapter = LookupContinuation(
        "danbooru", SCHEMA_VERSION, LookupStrategy.SOURCE_POST_URL, material.digest, "b5101", 0
    )
    bad_strategy = LookupContinuation(
        PROVIDER_KEY,
        SCHEMA_VERSION,
        LookupStrategy.DECLARED_MD5,
        material.digest,
        "b5101",
        0,
    )
    bad_version = LookupContinuation(
        PROVIDER_KEY,
        "old-schema",
        LookupStrategy.SOURCE_POST_URL,
        material.digest,
        "b5101",
        0,
    )
    other_material = LookupQueryMaterial(
        LookupStrategy.SOURCE_POST_URL, "https://x.com/acme/status/2"
    )
    bad_digest = LookupContinuation(
        PROVIDER_KEY,
        SCHEMA_VERSION,
        LookupStrategy.SOURCE_POST_URL,
        other_material.digest,
        "b5101",
        0,
    )
    bad_index = LookupContinuation(
        PROVIDER_KEY,
        SCHEMA_VERSION,
        LookupStrategy.SOURCE_POST_URL,
        material.digest,
        "b5101",
        1,
    )
    bad_page = LookupContinuation(
        PROVIDER_KEY,
        SCHEMA_VERSION,
        LookupStrategy.SOURCE_POST_URL,
        material.digest,
        "2",
        0,
    )

    def fetch_with(cursor: LookupContinuation) -> None:
        adapter.fetch_lookup(
            LookupRequest(LookupStrategy.SOURCE_POST_URL, material, continuation=cursor)
        )

    with pytest.raises(ValueError, match="incompatible e621 lookup continuation"):
        fetch_with(bad_adapter)
    with pytest.raises(ValueError, match="incompatible e621 lookup continuation"):
        fetch_with(bad_strategy)
    with pytest.raises(ValueError, match="incompatible e621 lookup continuation"):
        fetch_with(bad_version)
    with pytest.raises(ValueError, match="incompatible e621 lookup continuation"):
        fetch_with(bad_digest)
    with pytest.raises(ValueError, match="alias index is out of range"):
        fetch_with(bad_index)
    with pytest.raises(ValueError, match="opaque b<ID> boundary"):
        fetch_with(bad_page)
    assert requests == []


# ---------------------------------------------------------------------------
# Lookup normalization and conservative interpretation (OpenSpec task 5.3)
# ---------------------------------------------------------------------------


def _lookup_adapter(payload: object) -> E621Adapter:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    return _adapter(handler=handler)


def test_post_lookup_reuses_nested_normalization_and_safe_provenance() -> None:
    post = {
        "id": 5001,
        "sources": ["https://www.pixiv.net/artworks/9001", "https://x.com/acme/status/7"],
        "uploader_id": 42,
        "file": {
            "md5": "abcdef0123456789abcdef0123456789",
            "ext": "jpg",
            "size": 10,
            "width": 20,
            "height": 30,
            "url": None,
        },
        "sample": {"url": None, "width": None, "height": None},
        "preview": {"url": None, "width": None, "height": None},
        "tags": {"artist": ["artist_a"], "general": ["solo"], "species": ["fox"]},
        "relationships": {"parent_id": 0, "children": []},
        "flags": {"deleted": False},
    }
    adapter = _lookup_adapter([post])
    request = LookupRequest(LookupStrategy.SOURCE_POST_URL, "https://x.com/acme/status/7")
    page = adapter.normalize_lookup(adapter.fetch_lookup(request), request)

    assert page.continuation is None
    result = page.results[0]
    assert result.result_kind == "post"
    assert result.native_id == "5001"
    assert result.data["declared_md5"] == post["file"]["md5"]
    assert result.data["external_ids"] == {"pixiv_id": "9001"}
    assert result.data["sources"] == post["sources"]
    assert result.data["artist_tags"] == ["artist_a"]
    assert {item.object_kind for item in result.items} >= {
        "post",
        "account",
        "post_participant",
        "post_tag",
        "media_occurrence",
        "external_reference",
    }
    assert all(item.data["lookup_provenance"]["provider"] == "e621" for item in result.items)
    assert result.items[-1].data["lookup_provenance"]["query_digest"] == request.material.digest

    media = next(item for item in result.items if item.object_kind == "media_occurrence")
    assert result.data["availability"] == "available"
    assert media.data["availability"] == "unavailable"
    assert media.data["variants"][0]["availability"] == "unavailable"


def test_lookup_post_candidate_is_pending_and_source_evidence_is_reviewable(tmp_path) -> None:
    post = {
        "id": 5001,
        "sources": ["https://x.com/acme/status/7"],
        "file": {"md5": "abcdef0123456789abcdef0123456789", "ext": "jpg", "url": None},
        "tags": {"artist": ["artist_a"]},
        "flags": {"deleted": False},
    }
    adapter = _lookup_adapter([post])
    request = LookupRequest(LookupStrategy.SOURCE_POST_URL, "https://x.com/acme/status/7")
    page = adapter.normalize_lookup(adapter.fetch_lookup(request), request)

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            seed_post_id = writer.upsert_post(
                PostRecord(
                    "x",
                    "7",
                    NOW,
                    canonical_url="https://x.com/acme/status/7",
                )
            ).id
            raw_id = writer.store_raw(
                RawRecord(
                    payload=b"lookup",
                    media_type="application/json",
                    object_kind="candidate_lookup",
                    native_id=request.material.digest,
                    observed_at=NOW,
                    platform="e621",
                    adapter_version=ADAPTER_VERSION,
                    schema_version=SCHEMA_VERSION,
                    status="200",
                )
            )
            NormalizedPageWriter(writer).write(
                NormalizedPage(page.items),
                observed_at=NOW,
                raw_observation_id=raw_id,
                adapter_version=ADAPTER_VERSION,
            )
            interpreted = LookupInterpreter(database.connection).interpret(
                page.results[0],
                seed_post_id=seed_post_id,
                seed_account_id=None,
                strategy=request.strategy,
                raw_observation_id=raw_id,
                observed_at=NOW,
                seed_material_digest=request.material.digest,
                query_values=request.material.values,
            )

        assert interpreted.result_kind == "post_match"
        assert interpreted.post_candidate_id is not None
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


def test_lookup_resume_boundary_and_artist_pagination_fail_closed() -> None:
    post = {
        "id": 5002,
        "file": {"md5": "abcdef0123456789abcdef0123456789", "ext": "jpg", "url": None},
        "tags": {"artist": ["artist_a"]},
        "flags": {"deleted": False},
    }
    adapter = _lookup_adapter([post])
    material = LookupQueryMaterial(LookupStrategy.SOURCE_POST_URL, "https://x.com/a/status/7")
    cursor = LookupContinuation(
        PROVIDER_KEY, SCHEMA_VERSION, material.strategy, material.digest, "b5002"
    )
    request = LookupRequest(LookupStrategy.SOURCE_POST_URL, material, continuation=cursor)
    with pytest.raises(AdapterFailure, match="keyset boundary"):
        adapter.normalize_lookup(adapter.fetch_lookup(request), request)

    artist_material = LookupQueryMaterial(LookupStrategy.ARTIST_EXACT_NAME, "artist_a")
    artist_cursor = LookupContinuation(
        PROVIDER_KEY, SCHEMA_VERSION, artist_material.strategy, artist_material.digest, "b123"
    )
    artist_request = LookupRequest(
        LookupStrategy.ARTIST_EXACT_NAME, artist_material, continuation=artist_cursor
    )
    with pytest.raises(ValueError, match="does not support pagination"):
        adapter.fetch_lookup(artist_request)


@pytest.mark.parametrize("payload", [{"id": 1}, [{"id": 1}]])
def test_malformed_lookup_shapes_fail_typed(payload: object) -> None:
    request = LookupRequest(LookupStrategy.DECLARED_MD5, "abcdef0123456789abcdef0123456789")
    adapter = _lookup_adapter(payload)
    with pytest.raises(AdapterFailure, match=r"(list|categorized tags)"):
        adapter.normalize_lookup(adapter.fetch_lookup(request), request)


def test_artist_tag_lookup_requires_exact_current_artist_category() -> None:
    adapter = _lookup_adapter(
        [
            {
                "id": 7001,
                "name": "artist_a",
                "category": 1,
                "post_count": 123,
                "is_locked": False,
            }
        ]
    )
    request = LookupRequest(LookupStrategy.ARTIST_EXACT_NAME, "artist_a")
    page = adapter.normalize_lookup(adapter.fetch_lookup(request), request)
    result = page.results[0]

    assert result.result_kind == "attribution"
    assert result.native_id == "7001"
    assert result.data["attribution_kind"] == "artist_tag"
    assert result.data["attribution_native_id"] == "tag:7001"
    assert {item.object_kind for item in result.items} == {"tag", "attribution"}
    assert all(
        item.data["account"] is False for item in result.items if item.object_kind == "attribution"
    )

    non_artist = _lookup_adapter([{"id": 7002, "name": "artist_a", "category": 5, "post_count": 1}])
    assert non_artist.normalize_lookup(non_artist.fetch_lookup(request), request).results == ()


@pytest.mark.parametrize(
    "status, expected_count",
    [("active", 1), ("approved", 1), ("pending", 0), ("deleted", 0)],
)
def test_alias_lookup_only_emits_unambiguous_active_attribution_leads(
    status: str, expected_count: int
) -> None:
    adapter = _lookup_adapter(
        [
            {
                "id": 8001,
                "antecedent_name": "artist_old",
                "consequent_name": "artist_canonical",
                "status": status,
            }
        ]
    )
    request = LookupRequest(LookupStrategy.ARTIST_ALIAS, "artist_old")
    page = adapter.normalize_lookup(adapter.fetch_lookup(request), request)
    assert len(page.results) == expected_count
    if expected_count:
        result = page.results[0]
        assert result.data["name"] == "artist_canonical"
        assert result.data["attribution_kind"] == "approved_artist_alias"
        assert result.data["status"] == status
        assert {item.object_kind for item in result.items} == {"tag_alias", "attribution"}


def test_lookup_interpreter_keeps_e621_attribution_weak_and_posts_reviewable(tmp_path) -> None:
    tag_adapter = _lookup_adapter(
        [{"id": 7001, "name": "artist_a", "category": 1, "post_count": 123}]
    )
    tag_request = LookupRequest(LookupStrategy.ARTIST_EXACT_NAME, "artist_a")
    tag_page = tag_adapter.normalize_lookup(tag_adapter.fetch_lookup(tag_request), tag_request)

    post = {
        "id": 5001,
        "file": {"md5": "abcdef0123456789abcdef0123456789", "ext": "jpg", "url": None},
        "tags": {"artist": ["artist_a"]},
        "flags": {"deleted": False},
    }
    post_adapter = _lookup_adapter([post])
    post_request = LookupRequest(LookupStrategy.DECLARED_MD5, "abcdef0123456789abcdef0123456789")
    post_page = post_adapter.normalize_lookup(post_adapter.fetch_lookup(post_request), post_request)

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            raw_id = writer.store_raw(
                RawRecord(
                    payload=b"[]",
                    media_type="application/json",
                    object_kind="candidate_lookup",
                    native_id=tag_request.material.digest,
                    observed_at=NOW,
                    platform="e621",
                    adapter_version=ADAPTER_VERSION,
                    schema_version=SCHEMA_VERSION,
                    status="200",
                )
            )
            NormalizedPageWriter(writer).write(
                NormalizedPage(tag_page.items),
                observed_at=NOW,
                raw_observation_id=raw_id,
                adapter_version=ADAPTER_VERSION,
            )
            NormalizedPageWriter(writer).write(
                NormalizedPage(post_page.items),
                observed_at=NOW,
                raw_observation_id=raw_id,
                adapter_version=ADAPTER_VERSION,
            )

            interpreter = LookupInterpreter(database.connection)
            tag_interpreted = interpreter.interpret(
                tag_page.results[0],
                seed_post_id=None,
                seed_account_id=None,
                strategy=tag_request.strategy,
                raw_observation_id=raw_id,
                observed_at=NOW,
                seed_material_digest=tag_request.material.digest,
                query_values=tag_request.material.values,
            )
            post_interpreted = interpreter.interpret(
                post_page.results[0],
                seed_post_id=None,
                seed_account_id=None,
                strategy=post_request.strategy,
                raw_observation_id=raw_id,
                observed_at=NOW,
                seed_material_digest=post_request.material.digest,
                query_values=post_request.material.values,
            )

        assert tag_interpreted.result_kind == "weak_lead"
        assert tag_interpreted.account_candidate_id is None
        assert post_interpreted.result_kind == "post_match"
        assert post_interpreted.post_candidate_id is None
