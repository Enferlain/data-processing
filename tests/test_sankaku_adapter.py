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
    ResponseEnvelope,
)
from media_catalog.adapters.fixtures import load_fixture_suite
from media_catalog.adapters.sankaku import (
    ADAPTER_VERSION,
    API_SCHEMA_VERSION,
    CONTINUATION_VERSION,
    SANKAKU,
    SANKAKU_INSTANCES,
    SankakuAdapter,
    SankakuCredentials,
    SankakuInstance,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"
SUITE = load_fixture_suite(FIXTURES / "sankaku.json")
POST_CASE = next(case for case in SUITE.cases if case.name == "post_wvaemE6YDaz")
LISTING_CASE = next(case for case in SUITE.cases if case.name == "keyset_rating_g_first_page")
NOW = "2026-10-29T00:00:00Z"
NEXT_CURSOR = json.loads(LISTING_CASE.response.payload)["meta"]["next"]

SENTINEL_LOGIN = "sentinel-login"
SENTINEL_PASSWORD = "sentinel-password"
SENTINEL_TOKEN = "sentinel-access-token-value"
CREDENTIALS = SankakuCredentials(SENTINEL_LOGIN, SENTINEL_PASSWORD)


def _token_response(token: str = SENTINEL_TOKEN, success: bool = True) -> httpx.Response:
    return httpx.Response(
        200,
        json={"success": success, "access_token": token if success else None},
    )


def _adapter(handler) -> SankakuAdapter:
    return SankakuAdapter(
        client=httpx.Client(transport=httpx.MockTransport(handler)), credentials=CREDENTIALS
    )


def test_instance_policy_and_registry() -> None:
    assert set(SANKAKU_INSTANCES) == {"sankaku"}
    assert SANKAKU.platform_key == "sankaku"
    with pytest.raises(ValueError, match="platform key"):
        SankakuInstance(platform_key="other")
    with pytest.raises(ValueError, match="canonical HTTPS"):
        SankakuInstance(base_url="http://sankakuapi.com")
    with pytest.raises(ValueError, match="minimum interval"):
        SankakuInstance(minimum_interval_seconds=0.5)
    with pytest.raises(ValueError, match="page size"):
        SankakuInstance(page_size=0)


def test_credentials_resolve_externally_and_stay_secret() -> None:
    for environ in ({}, {SANKAKU.login_env: "user"}):
        with pytest.raises(ValueError, match="configure both"):
            SankakuCredentials.from_environment(SANKAKU, environ)
    resolved = SankakuCredentials.from_environment(
        SANKAKU, {SANKAKU.login_env: "user", SANKAKU.password_env: "secret-value"}
    )
    assert resolved.secret_values() == ("user", "secret-value")
    assert "secret-value" not in repr(resolved)


def test_token_exchange_and_authorized_wire_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/auth/token":
            return _token_response()
        return httpx.Response(
            200,
            stream=httpx.ByteStream(POST_CASE.response.payload),
            headers={"content-type": "application/json"},
        )

    adapter = _adapter(handler)
    envelope = adapter.fetch(
        AdapterRequest(operation=AdapterOperation.FETCH_POST, target="wvaemE6YDaz")
    )
    token_call, data_call = requests[0], requests[1]
    assert token_call.url.host == "sankakuapi.com"
    assert json.loads(token_call.content) == {
        "login": SENTINEL_LOGIN,
        "password": SENTINEL_PASSWORD,
    }
    assert data_call.headers.get("Authorization") == f"Bearer {SENTINEL_TOKEN}"
    assert dict(data_call.url.params)["tags"] == "id_range:wvaemE6YDaz"
    # The bearer token never enters identities, targets, URLs, or the envelope.
    assert SENTINEL_TOKEN not in envelope.request_identity
    assert envelope.request_target == "post:wvaemE6YDaz"
    assert envelope.schema_version == API_SCHEMA_VERSION
    assert envelope.adapter_version == ADAPTER_VERSION
    assert adapter.normalize(envelope).items


def test_invalid_token_reexchanges_once() -> None:
    exchanges: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            exchanges.append(1)
            return _token_response()
        authorization = request.headers.get("Authorization", "")
        if "stale" in authorization:
            return httpx.Response(401)
        return httpx.Response(
            200,
            stream=httpx.ByteStream(POST_CASE.response.payload),
            headers={"content-type": "application/json"},
        )

    adapter = SankakuAdapter(
        client=httpx.Client(transport=httpx.MockTransport(handler)), credentials=CREDENTIALS
    )
    adapter._token = "stale-token"
    envelope = adapter.fetch(
        AdapterRequest(operation=AdapterOperation.FETCH_POST, target="wvaemE6YDaz")
    )
    assert len(exchanges) == 1  # exactly one re-exchange
    assert envelope.status_code == 200
    assert adapter.normalize(envelope).items


def test_refused_token_exchange_fails_before_data_requests() -> None:
    data_calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(401, json={"success": False})
        data_calls.append(request)
        return httpx.Response(200)

    adapter = _adapter(handler)
    with pytest.raises(AdapterFailure) as exc_info:
        adapter.fetch(AdapterRequest(operation=AdapterOperation.FETCH_POST, target="wvaemE6YDaz"))
    assert exc_info.value.outcome == AdapterOutcome.AUTHENTICATION_REQUIRED
    assert data_calls == []


def test_listing_wire_request_and_cursor_round_trip() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/auth/token":
            return _token_response()
        return httpx.Response(
            200,
            stream=httpx.ByteStream(LISTING_CASE.response.payload),
            headers={"content-type": "application/json"},
        )

    adapter = _adapter(handler)
    first = adapter.fetch(
        AdapterRequest(operation=AdapterOperation.LIST_ACCOUNT_POSTS, target="rating:g")
    )
    assert dict(requests[-1].url.params)["tags"] == "rating:g"
    assert "next" not in dict(requests[-1].url.params)
    page = adapter.normalize(first)
    assert page.continuation is not None
    assert page.continuation.value == {
        "query": "rating:g",
        "next": NEXT_CURSOR,
    }
    second = adapter.fetch(
        AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "rating:g",
            continuation=page.continuation,
        )
    )
    assert dict(requests[-1].url.params)["next"] == NEXT_CURSOR
    assert f":{NEXT_CURSOR}" in second.request_identity


def test_malformed_continuation_refused_before_network() -> None:
    adapter = _adapter(lambda request: pytest.fail("network contacted"))
    for continuation in (
        Continuation("danbooru", CONTINUATION_VERSION, {"query": "rating:g", "next": "x"}),
        Continuation("sankaku", "other-v1", {"query": "rating:g", "next": "x"}),
        Continuation("sankaku", CONTINUATION_VERSION, {"query": "other", "next": "x"}),
        Continuation("sankaku", CONTINUATION_VERSION, {"next": "x"}),
    ):
        with pytest.raises(ValueError, match=r"continuation|different listing"):
            adapter.fetch(
                AdapterRequest(
                    AdapterOperation.LIST_ACCOUNT_POSTS,
                    "rating:g",
                    continuation=continuation,
                )
            )


def test_invalid_post_target_refused_before_network() -> None:
    adapter = _adapter(lambda request: pytest.fail("network contacted"))
    for target in ("has space", "tag:one", "x" * 65):
        with pytest.raises(ValueError, match="opaque"):
            adapter.fetch(AdapterRequest(operation=AdapterOperation.FETCH_POST, target=target))


def test_captured_post_contract_normalizes() -> None:
    adapter = _adapter(lambda request: pytest.fail("network contacted"))
    envelope = ResponseEnvelope(
        provider="sankaku",
        instance="sankaku",
        operation=AdapterOperation.FETCH_POST,
        request_identity=POST_CASE.request_identity,
        status_code=200,
        headers={"content-type": "application/json"},
        payload=POST_CASE.response.payload,
        observed_at=NOW,
        adapter_version=ADAPTER_VERSION,
        schema_version=API_SCHEMA_VERSION,
    )
    page = adapter.normalize(envelope)
    expected = POST_CASE.expected
    post = next(item for item in page.items if item.object_kind == "post")
    assert post.native_id == expected["post_ids"][0]
    assert post.data["rating"] == expected["rating"]
    assert post.data["status"] == expected["status"]
    assert post.data["created_at"] == "2026-10-29T11:56:36Z"
    # The provider reports the removed source as a sentinel, not a URL.
    assert post.data["source"] is None
    occurrence = next(item for item in page.items if item.object_kind == "media_occurrence")
    assert occurrence.data["declared_md5"] == expected["declared_md5"]
    assert (occurrence.data["width"], occurrence.data["height"]) == (
        expected["width"],
        expected["height"],
    )
    assert [variant["role"] for variant in occurrence.data["variants"]] == expected["variants"]
    categories: dict[str, int] = {}
    for item in page.items:
        if item.object_kind == "post_tag":
            categories[item.data["category"]] = categories.get(item.data["category"], 0) + 1
    assert categories == expected["tag_categories"]
    tag_items = [item for item in page.items if item.object_kind == "post_tag"]
    assert len(tag_items) == expected["tag_count"]


def test_repeated_invalid_token_body_classifies_authentication() -> None:
    adapter = _adapter(lambda request: pytest.fail("network contacted"))
    envelope = ResponseEnvelope(
        provider="sankaku",
        instance="sankaku",
        operation=AdapterOperation.FETCH_POST,
        request_identity="sankaku:api_v2:post:x",
        status_code=200,
        headers={"content-type": "application/json"},
        payload=json.dumps({"success": False, "code": "access__invalid-token"}).encode(),
        observed_at=NOW,
        adapter_version=ADAPTER_VERSION,
        schema_version=API_SCHEMA_VERSION,
    )
    with pytest.raises(AdapterFailure) as exc_info:
        adapter.normalize(envelope)
    assert exc_info.value.outcome == AdapterOutcome.AUTHENTICATION_REQUIRED


def test_unbounded_and_overflowing_values_classify_typed() -> None:
    adapter = _adapter(lambda request: pytest.fail("network contacted"))

    def _envelope(payload: bytes) -> ResponseEnvelope:
        return ResponseEnvelope(
            provider="sankaku",
            instance="sankaku",
            operation=AdapterOperation.FETCH_POST,
            request_identity="sankaku:api_v2:post:x",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=payload,
            observed_at=NOW,
            adapter_version=ADAPTER_VERSION,
            schema_version=API_SCHEMA_VERSION,
        )

    # A created_at far outside unix range stays typed, not an untyped crash.
    with pytest.raises(AdapterFailure) as exc_info:
        adapter.normalize(
            _envelope(json.dumps([{"id": "ok", "created_at": {"s": 10**20}}]).encode())
        )
    assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE
    # A non-text tag name in the fuller array rejects the whole document.
    with pytest.raises(AdapterFailure) as exc_info:
        adapter.normalize(_envelope(json.dumps([{"id": "ok", "tag_names": ["ok", 5]}]).encode()))
    assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE

    listing = ResponseEnvelope(
        provider="sankaku",
        instance="sankaku",
        operation=AdapterOperation.LIST_ACCOUNT_POSTS,
        request_identity="sankaku:api_v2:listing:x:start",
        status_code=200,
        headers={"content-type": "application/json"},
        payload=json.dumps({"data": [], "meta": {"next": "c" * 257}}).encode(),
        observed_at=NOW,
        adapter_version=ADAPTER_VERSION,
        schema_version=API_SCHEMA_VERSION,
        request_target="listing:x:start",
    )
    with pytest.raises(AdapterFailure) as exc_info:
        adapter.normalize(listing)
    assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE

    # A garbage rate-limit reset header degrades to an untyped retry_at.
    envelope = ResponseEnvelope(
        provider="sankaku",
        instance="sankaku",
        operation=AdapterOperation.FETCH_POST,
        request_identity="sankaku:api_v2:post:x",
        status_code=429,
        headers={"x-ratelimit-reset": "99999999999999999999"},
        payload=b"{}",
        observed_at=NOW,
        adapter_version=ADAPTER_VERSION,
        schema_version=API_SCHEMA_VERSION,
    )
    with pytest.raises(AdapterFailure) as exc_info:
        adapter.normalize(envelope)
    assert exc_info.value.outcome == AdapterOutcome.RATE_LIMITED
    assert exc_info.value.retry_at is None


def test_captured_keyset_page_normalizes_with_cursor() -> None:
    adapter = _adapter(lambda request: pytest.fail("network contacted"))
    envelope = ResponseEnvelope(
        provider="sankaku",
        instance="sankaku",
        operation=AdapterOperation.LIST_ACCOUNT_POSTS,
        request_identity=LISTING_CASE.request_identity,
        status_code=200,
        headers={"content-type": "application/json"},
        payload=LISTING_CASE.response.payload,
        observed_at=NOW,
        adapter_version=ADAPTER_VERSION,
        schema_version=API_SCHEMA_VERSION,
        request_target="listing:rating:g:start",
    )
    page = adapter.normalize(envelope)
    ids = [item.native_id for item in page.items if item.object_kind == "post"]
    assert ids == LISTING_CASE.expected["post_ids"]
    assert (page.continuation is not None) == LISTING_CASE.expected["has_next"]


def test_shape_violations_classify_malformed() -> None:
    adapter = _adapter(lambda request: pytest.fail("network contacted"))

    def _envelope(payload: bytes, operation: AdapterOperation) -> ResponseEnvelope:
        return ResponseEnvelope(
            provider="sankaku",
            instance="sankaku",
            operation=operation,
            request_identity="sankaku:api_v2:post:x",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=payload,
            observed_at=NOW,
            adapter_version=ADAPTER_VERSION,
            schema_version=API_SCHEMA_VERSION,
        )

    for payload, operation in (
        (b'{"data": []}', AdapterOperation.FETCH_POST),
        (json.dumps([{}, {}]).encode(), AdapterOperation.FETCH_POST),
        (b"[]", AdapterOperation.LIST_ACCOUNT_POSTS),
        (json.dumps({"data": []}).encode(), AdapterOperation.LIST_ACCOUNT_POSTS),
        (
            json.dumps({"data": [], "meta": {"next": 7}}).encode(),
            AdapterOperation.LIST_ACCOUNT_POSTS,
        ),
        (json.dumps([{"id": "ok", "tags": ["nope"]}]).encode(), AdapterOperation.FETCH_POST),
        (
            json.dumps([{"id": "ok", "created_at": {"s": "x"}}]).encode(),
            AdapterOperation.FETCH_POST,
        ),
    ):
        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(_envelope(payload, operation))
        assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE, payload


def test_rate_limit_maps_reset_time() -> None:
    adapter = _adapter(lambda request: pytest.fail("network contacted"))
    envelope = ResponseEnvelope(
        provider="sankaku",
        instance="sankaku",
        operation=AdapterOperation.FETCH_POST,
        request_identity="sankaku:api_v2:post:x",
        status_code=429,
        headers={"x-ratelimit-reset": "1793300000"},
        payload=b"{}",
        observed_at=NOW,
        adapter_version=ADAPTER_VERSION,
        schema_version=API_SCHEMA_VERSION,
    )
    with pytest.raises(AdapterFailure) as exc_info:
        adapter.normalize(envelope)
    assert exc_info.value.outcome == AdapterOutcome.RATE_LIMITED
    assert exc_info.value.retry_at is not None
    assert exc_info.value.retry_at.endswith("Z")


def test_sankaku_cli_routes_and_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import media_catalog.cli as cli_module
    from media_catalog.cli import main
    from media_catalog.database import CatalogDatabase
    from media_catalog.remote_sync import MetadataSyncService, SyncLimits

    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return _token_response()
        return httpx.Response(
            200,
            stream=httpx.ByteStream(POST_CASE.response.payload),
            headers={"content-type": "application/json"},
        )

    monkeypatch.setenv("SANKAKU_LOGIN", SENTINEL_LOGIN)
    monkeypatch.setenv("SANKAKU_PASSWORD", SENTINEL_PASSWORD)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        CatalogDatabase(catalog) as database,
    ):
        adapter = SankakuAdapter(SANKAKU, client=client, credentials=CREDENTIALS)
        result = MetadataSyncService(database, adapter, minimum_interval_seconds=0.0).synchronize(
            AdapterOperation.FETCH_POST,
            "wvaemE6YDaz",
            limits=SyncLimits(1, 1, 100, 60),
        )
        assert (result.status, result.outcome) == ("complete", "success")
        row = database.connection.execute(
            "SELECT p.native_post_id, pl.platform_key FROM posts p"
            " JOIN platforms pl USING(platform_id)"
        ).fetchone()
        assert tuple(row) == ("wvaemE6YDaz", "sankaku")

    # The command surface resolves credentials externally and routes the operation.
    constructed: list[tuple[object, object]] = []

    class FakeAdapter:
        instance_key = "sankaku"
        adapter_version = ADAPTER_VERSION
        schema_version = API_SCHEMA_VERSION

        def __init__(self, instance: object, *, client: object, credentials: object) -> None:
            constructed.append((instance, credentials))

    class FakeService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def synchronize(self, *_args: object, **_kwargs: object) -> object:
            from media_catalog.remote_sync import SyncResult

            return SyncResult(
                remote_run_id=1,
                platform="sankaku",
                operation="fetch_post",
                target="wvaemE6YDaz",
                status="complete",
                outcome="success",
                request_count=1,
                page_count=1,
                record_count=1,
                resumed_from_run_id=None,
            )

    monkeypatch.setattr(cli_module, "SankakuAdapter", FakeAdapter)
    monkeypatch.setattr(cli_module, "MetadataSyncService", FakeService)
    main(["metadata", "sankaku-post", str(catalog), "wvaemE6YDaz", "--json"])
    assert len(constructed) == 1
    assert isinstance(constructed[0][1], SankakuCredentials)
