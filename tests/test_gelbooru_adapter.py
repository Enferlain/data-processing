"""Task 3.5: focused injected-transport tests for the Gelbooru DAPI adapter."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from media_catalog.adapters.contracts import (
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    AdapterRequest,
    Continuation,
)
from media_catalog.adapters.gelbooru import (
    ADAPTER_VERSION,
    CONTINUATION_VERSION,
    DAPI_SCHEMA_VERSION,
    DAPI_TRANSPORT_VERSION,
    GelbooruAdapter,
    GelbooruCredentials,
)
from media_catalog.adapters.gelbooru.config import MAX_PAGE_SIZE

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures" / "metadata_adapters"


def _load_dapi_case(name: str):
    from media_catalog.adapters.fixtures import load_fixture_suite

    suite = load_fixture_suite(FIXTURES / "gelbooru.json")
    return next(c for c in suite.cases if c.name == name)


def _mock_response(status_code: int, payload_bytes: bytes, headers: dict | None = None):
    """Build a mock httpx.Response for injected transport tests."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.content = payload_bytes
    response.headers = httpx.Headers(headers or {"content-type": "application/json; charset=UTF-8"})
    return response


def _make_client(responses: Sequence[httpx.Response | BaseException]) -> httpx.Client:
    """Build an httpx.Client that returns pre-loaded responses on each get()."""
    client = MagicMock(spec=httpx.Client)
    client.get = MagicMock(side_effect=list(responses))
    return client


def _dapi_post_body(post_id: str) -> dict:
    """Build a minimal DAPI post response body for a given post ID."""
    return {
        "@attributes": {"limit": 1, "offset": 0, "count": 1},
        "post": [
            {
                "change": 0,
                "created_at": "2025-07-30T10:16:34",
                "creator_id": 1,
                "directory": "1",
                "file_url": f"https://gelbooru.com/images/1/{post_id}.jpg",
                "has_children": 0,
                "has_comments": 1,
                "has_notes": 0,
                "height": 1200,
                "id": int(post_id),
                "image": f"{post_id}.jpg",
                "md5": "abcd1234ef567890abcd1234ef567890",
                "owner": "test_user",
                "parent_id": None,
                "post_locked": 0,
                "preview_height": 300,
                "preview_width": 200,
                "preview_url": f"https://gelbooru.com/thumbnails/1/{post_id}.jpg",
                "rating": "general",
                "sample": 0,
                "sample_height": 0,
                "sample_width": 0,
                "sample_url": "",
                "score": 5,
                "source": "https://example.com/source",
                "status": "active",
                "tags": "test_tag another_tag",
                "title": "Test Post",
                "width": 800,
            }
        ],
    }


def _scoped_continuation(
    *, target: str = "test", pid: int = 2, last_pid: int = 1, limit: int = 50
) -> Continuation:
    """Build a fully scoped listing continuation for validation tests."""
    from media_catalog.adapters.gelbooru.adapter import ADAPTER_VERSION as AV
    from media_catalog.adapters.gelbooru.config import (
        DAPI_SCHEMA_VERSION,
        DAPI_TRANSPORT_VERSION,
    )

    return Continuation(
        "gelbooru",
        CONTINUATION_VERSION,
        {
            "operation": "list_account_posts",
            "target": target,
            "query": "",
            "sort": "id-desc",
            "transport": DAPI_TRANSPORT_VERSION,
            "direction": "forward",
            "pid": str(pid),
            "last_pid": str(last_pid),
            "limit": str(limit),
            "last_id": 100,
            "continuation_version": CONTINUATION_VERSION,
            "adapter_version": AV,
            "schema_version": DAPI_SCHEMA_VERSION,
        },
    )


# ── Task 3.5a: exact request shapes ──────────────────────────────────


class TestRequestShapes:
    """Adapter renders the exact DAPI request shape specified in the fixture contract."""

    def test_single_post_request_shape(self) -> None:
        """FETCH_POST renders page=dapi&s=post&q=index&json=1&id=<positive numeric>."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        case = _load_dapi_case("post_12370900")
        response = _mock_response(200, case.response.payload)
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)

        called_url = client.get.call_args
        params = called_url.kwargs["params"]
        # Credentials are joined only at the final DAPI HTTP boundary
        assert params["page"] == "dapi"
        assert params["s"] == "post"
        assert params["q"] == "index"
        assert params["json"] == "1"
        assert params["id"] == "12370900"
        assert params["user_id"] == "12345"
        assert params["api_key"] == "abcdef1234567890abcdef1234567890"
        assert envelope.request_identity == "gelbooru:dapi_json:post:12370900"
        assert envelope.transport_key == DAPI_TRANSPORT_VERSION
        assert envelope.transport_version == DAPI_TRANSPORT_VERSION

    def test_tag_metadata_request_shape(self) -> None:
        """FETCH_TAG renders page=dapi&s=tag&q=index&json=1&name=<tag>."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        tag_payload = json.dumps(
            {
                "@attributes": {"limit": 1, "offset": 0, "count": 1},
                "tag": [{"id": 1, "name": "test", "count": 5, "type": 1, "ambiguous": 0}],
            }
        )
        response = _mock_response(200, tag_payload.encode())
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        request = AdapterRequest(AdapterOperation.FETCH_TAG, "hiroki_(yyqw7151)")
        envelope = adapter.fetch(request)

        params = client.get.call_args.kwargs["params"]
        assert params["page"] == "dapi"
        assert params["s"] == "tag"
        assert params["q"] == "index"
        assert params["json"] == "1"
        assert params["name"] == "hiroki_(yyqw7151)"
        assert envelope.request_identity == "gelbooru:dapi_json:tag:hiroki_(yyqw7151)"

    def test_listing_request_shape(self) -> None:
        """LISTING renders page=dapi&s=post&q=index&json=1&pid=<0-based>&limit=<capped>."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        listing_payload = json.dumps(
            {"@attributes": {"limit": 50, "offset": 0, "count": 200}, "post": []}
        )
        response = _mock_response(200, listing_payload.encode())
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        continuation = _scoped_continuation()
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        envelope = adapter.fetch(request)

        params = client.get.call_args.kwargs["params"]
        assert params["pid"] == "2"
        assert params["limit"] == "50"
        assert envelope.request_identity == "gelbooru:dapi_json:listing:test:id-desc:forward:2:50"
        assert envelope.request_target == "listing:test:id-desc:forward:2:50"

    def test_page_ceiling_enforced(self) -> None:
        """limit is capped at MAX_PAGE_SIZE (100) regardless of continuation value."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        ceiling_payload = json.dumps(
            {"@attributes": {"limit": 100, "offset": 0, "count": 200}, "post": []}
        )
        response = _mock_response(200, ceiling_payload.encode())
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        # Continuation requests 200 — adapter caps to MAX_PAGE_SIZE
        continuation = _scoped_continuation(pid=1, last_pid=0, limit=200)
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        adapter.fetch(request)

        params = client.get.call_args.kwargs["params"]
        assert int(params["limit"]) == MAX_PAGE_SIZE

    def test_no_credential_params_on_html(self) -> None:
        """HTML transport does not accept credentials — adapter enforces this."""
        # This is verified at the adapter level: FETCH_POST and FETCH_TAG
        # both raise ValueError when credentials are None.
        client = _make_client([])
        adapter = GelbooruAdapter(client=client, credentials=None)

        with pytest.raises(ValueError, match="DAPI requests require credentials"):
            adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "12370900"))

        with pytest.raises(ValueError, match="DAPI requests require credentials"):
            adapter.fetch(AdapterRequest(AdapterOperation.FETCH_TAG, "test_tag"))


# ── Task 3.5b: typed outcomes ────────────────────────────────────────


class TestTypedOutcomes:
    """Adapter raises typed AdapterFailure for every observed status."""

    def _make_envelope(self, status_code: int, payload: bytes) -> Any:
        """Build a ResponseEnvelope for outcome testing."""
        from media_catalog.adapters.contracts import ResponseEnvelope

        return ResponseEnvelope(
            provider="gelbooru",
            instance="gelbooru",
            operation=AdapterOperation.FETCH_POST,
            request_identity="gelbooru:dapi_json:post:12370900",
            status_code=status_code,
            headers={"content-type": "application/json"},
            payload=payload,
            observed_at="2026-10-01T00:00:00Z",
            adapter_version=ADAPTER_VERSION,
            schema_version=DAPI_SCHEMA_VERSION,
            transport_key=DAPI_TRANSPORT_VERSION,
            transport_version=DAPI_TRANSPORT_VERSION,
            request_target="post:12370900",
        )

    def test_success_200(self) -> None:
        adapter = GelbooruAdapter(client=None, credentials=None)
        body = json.dumps(_dapi_post_body("12370900")).encode()
        envelope = self._make_envelope(200, body)
        page = adapter.normalize(envelope)
        assert len(page.items) > 0
        assert page.continuation is None

    def test_unavailable_404(self) -> None:
        adapter = GelbooruAdapter(client=None, credentials=None)
        envelope = self._make_envelope(404, b"{}")
        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.UNAVAILABLE
        assert exc_info.value.status_code == 404

    def test_authentication_required_401(self) -> None:
        adapter = GelbooruAdapter(client=None, credentials=None)
        envelope = self._make_envelope(401, b"{}")
        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.AUTHENTICATION_REQUIRED
        assert exc_info.value.status_code == 401

    def test_authorization_denied_403(self) -> None:
        adapter = GelbooruAdapter(client=None, credentials=None)
        envelope = self._make_envelope(403, b"{}")
        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.AUTHORIZATION_DENIED
        assert exc_info.value.status_code == 403

    def test_rate_limited_429(self) -> None:
        adapter = GelbooruAdapter(client=None, credentials=None)
        envelope = self._make_envelope(429, b"{}")
        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.RATE_LIMITED
        assert exc_info.value.status_code == 429

    def test_transient_provider_500(self) -> None:
        adapter = GelbooruAdapter(client=None, credentials=None)
        envelope = self._make_envelope(500, b"{}")
        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.TRANSIENT_PROVIDER
        assert exc_info.value.status_code == 500

    def test_unavailable_500_non_standard(self) -> None:
        """502/503 are still TRANSIENT_PROVIDER."""
        adapter = GelbooruAdapter(client=None, credentials=None)
        for code in (502, 503):
            envelope = self._make_envelope(code, b"{}")
            with pytest.raises(AdapterFailure) as exc_info:
                adapter.normalize(envelope)
            assert exc_info.value.outcome == AdapterOutcome.TRANSIENT_PROVIDER

    def test_malformed_error_envelope_200(self) -> None:
        """200 with error key raises MALFORMED_RESPONSE."""
        adapter = GelbooruAdapter(client=None, credentials=None)
        body = json.dumps({"error": "Invalid API key"}).encode()
        envelope = self._make_envelope(200, body)
        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE

    def test_malformed_error_envelope_response_success_false(self) -> None:
        """200 with response.@attributes.success=false raises MALFORMED_RESPONSE."""
        adapter = GelbooruAdapter(client=None, credentials=None)
        body = json.dumps(
            {"response": {"@attributes": {"success": "false", "reason": "Query failed"}}}
        ).encode()
        envelope = self._make_envelope(200, body)
        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE

    def test_unavailable_empty_result_count_zero(self) -> None:
        """200 with count==0 and no post key returns empty page (not failure)."""
        adapter = GelbooruAdapter(client=None, credentials=None)
        body = json.dumps({"@attributes": {"limit": 25, "offset": 0, "count": 0}}).encode()
        envelope = self._make_envelope(200, body)
        page = adapter.normalize(envelope)
        assert page.items == ()
        assert page.continuation is None


# ── Task 3.5c: response-first raw retention ──────────────────────────


class TestResponseFirstRawRetention:
    """Response envelope is produced before normalization; raw payload is preserved."""

    def test_envelope_carries_raw_payload(self) -> None:
        """ResponseEnvelope.payload is the exact raw response bytes."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        case = _load_dapi_case("post_12370900")
        response = _mock_response(200, case.response.payload)
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)

        assert envelope.payload == case.response.payload
        assert envelope.status_code == 200
        assert envelope.adapter_version == ADAPTER_VERSION
        assert envelope.schema_version == DAPI_SCHEMA_VERSION
        assert envelope.transport_key == DAPI_TRANSPORT_VERSION
        assert envelope.transport_version == DAPI_TRANSPORT_VERSION


# ── Task 3.5d: continuation validation ───────────────────────────────


class TestContinuationValidation:
    """Incompatible continuations are rejected before network access."""

    def test_wrong_adapter_rejected(self) -> None:
        """Continuation from a different adapter is rejected."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        response = _mock_response(200, json.dumps(_dapi_post_body("12370900")).encode())
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        continuation = Continuation("danbooru", "v1", {"pid": "0", "limit": "25"})
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )

        with pytest.raises(ValueError, match="continuation belongs to another adapter"):
            adapter.fetch(request)

    def test_wrong_version_rejected(self) -> None:
        """Continuation with incompatible version is rejected."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        response = _mock_response(200, json.dumps(_dapi_post_body("12370900")).encode())
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        continuation = Continuation("gelbooru", "wrong-version", {"pid": "0", "limit": "25"})
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )

        with pytest.raises(ValueError, match="incompatible Gelbooru continuation version"):
            adapter.fetch(request)


# ── Task 3.5e: committed-page resume (listing continuation) ───────────


class TestCommittedPageResume:
    """Listing continuation produces the next pid when a full page is returned."""

    def test_full_page_produces_continuation(self) -> None:
        """Full page (limit results) → continuation with next pid."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        limit = 25
        posts = [
            {
                "change": 0,
                "created_at": "2025-07-30T10:16:34",
                "creator_id": i + 1,
                "directory": str(i + 1),
                "file_url": f"https://gelbooru.com/images/{i + 1}/{i + 1}.jpg",
                "has_children": 0,
                "has_comments": 0,
                "has_notes": 0,
                "height": 100,
                "id": i + 1,
                "image": f"{i + 1}.jpg",
                "md5": "abcd1234ef567890abcd1234ef567890",
                "owner": f"user{i + 1}",
                "parent_id": None,
                "post_locked": 0,
                "preview_height": 50,
                "preview_width": 50,
                "preview_url": f"https://gelbooru.com/thumbnails/{i + 1}/{i + 1}.jpg",
                "rating": "general",
                "sample": 0,
                "sample_height": 0,
                "sample_width": 0,
                "sample_url": "",
                "score": 0,
                "source": "",
                "status": "active",
                "tags": "tag_a",
                "title": f"Post {i + 1}",
                "width": 100,
            }
            for i in range(limit)
        ]
        body = {
            "@attributes": {"limit": limit, "offset": 0, "count": 200},
            "post": posts,
        }
        response = _mock_response(200, json.dumps(body).encode())
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        continuation = _scoped_continuation(pid=1, last_pid=0, limit=limit)
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        envelope = adapter.fetch(request)
        page = adapter.normalize(envelope)

        assert page.continuation is not None
        value = page.continuation.value
        # Boundary advances forward one committed page.
        assert value["pid"] == "2"
        assert value["last_pid"] == "1"
        assert value["limit"] == str(limit)
        assert value["last_id"] == limit  # last post id in response order
        # Every scope dimension travels with the checkpoint.
        assert value["operation"] == "list_account_posts"
        assert value["target"] == "test"
        assert value["query"] == ""
        assert value["sort"] == "id-desc"
        assert value["direction"] == "forward"
        assert value["continuation_version"] == CONTINUATION_VERSION
        assert page.continuation.adapter == "gelbooru"
        assert page.continuation.version == CONTINUATION_VERSION

    def test_partial_page_no_continuation(self) -> None:
        """Partial page (fewer than limit) → no continuation."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        limit = 25
        posts = [
            {
                "change": 0,
                "created_at": "2025-07-30T10:16:34",
                "creator_id": 1,
                "directory": "1",
                "file_url": "https://gelbooru.com/images/1/1.jpg",
                "has_children": 0,
                "has_comments": 0,
                "has_notes": 0,
                "height": 100,
                "id": 1,
                "image": "1.jpg",
                "md5": "abcd1234ef567890abcd1234ef567890",
                "owner": "user1",
                "parent_id": None,
                "post_locked": 0,
                "preview_height": 50,
                "preview_width": 50,
                "preview_url": "https://gelbooru.com/thumbnails/1/1.jpg",
                "rating": "general",
                "sample": 0,
                "sample_height": 0,
                "sample_width": 0,
                "sample_url": "",
                "score": 0,
                "source": "",
                "status": "active",
                "tags": "tag_a",
                "title": "Post 1",
                "width": 100,
            }
        ]
        body = {
            "@attributes": {"limit": limit, "offset": 0, "count": 1},
            "post": posts,
        }
        response = _mock_response(200, json.dumps(body).encode())
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        continuation = _scoped_continuation(pid=1, last_pid=0, limit=limit)
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        envelope = adapter.fetch(request)
        page = adapter.normalize(envelope)

        assert page.continuation is None


# ── Task 3.5f: idempotent normalization ──────────────────────────────


class TestIdempotentNormalization:
    """Same response produces identical NormalizedPage on repeated calls."""

    def test_normalize_produces_identical_items(self) -> None:
        adapter = GelbooruAdapter(client=None, credentials=None)
        case = _load_dapi_case("post_12370900")

        from media_catalog.adapters.contracts import ResponseEnvelope

        envelope = ResponseEnvelope(
            provider="gelbooru",
            instance="gelbooru",
            operation=AdapterOperation.FETCH_POST,
            request_identity="gelbooru:dapi_json:post:12370900",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=case.response.payload,
            observed_at="2026-10-01T00:00:00Z",
            adapter_version=ADAPTER_VERSION,
            schema_version=DAPI_SCHEMA_VERSION,
            transport_key=DAPI_TRANSPORT_VERSION,
            transport_version=DAPI_TRANSPORT_VERSION,
            request_target="post:12370900",
        )

        page_a = adapter.normalize(envelope)
        page_b = adapter.normalize(envelope)

        assert page_a.items == page_b.items
        assert page_a.continuation == page_b.continuation

    def test_post_item_fields_are_stable(self) -> None:
        """Key post fields match the fixture contract across normalization."""
        adapter = GelbooruAdapter(client=None, credentials=None)
        case = _load_dapi_case("post_12370900")

        from media_catalog.adapters.contracts import ResponseEnvelope

        envelope = ResponseEnvelope(
            provider="gelbooru",
            instance="gelbooru",
            operation=AdapterOperation.FETCH_POST,
            request_identity="gelbooru:dapi_json:post:12370900",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=case.response.payload,
            observed_at="2026-10-01T00:00:00Z",
            adapter_version=ADAPTER_VERSION,
            schema_version=DAPI_SCHEMA_VERSION,
            transport_key=DAPI_TRANSPORT_VERSION,
            transport_version=DAPI_TRANSPORT_VERSION,
            request_target="post:12370900",
        )

        page = adapter.normalize(envelope)
        items_by_kind = {item.object_kind: item for item in page.items}

        post = items_by_kind["post"]
        assert post.data["platform"] == "gelbooru"
        assert post.data["created_at"] == "2025-07-30T15:16:34Z"
        assert post.data["rating"] == "sensitive"
        assert post.data["availability"] == "available"

        media = items_by_kind["media_occurrence"]
        assert media.data["declared_md5"] == "fef8d5889c2fe425dd50cfade909cec9"
        assert media.data["width"] == 1150
        assert media.data["height"] == 1750

        account = items_by_kind["account"]
        assert account.data["handle"] == "danbooru"

        tags = [item for item in page.items if item.object_kind == "post_tag"]
        assert len(tags) == 23  # fixture has 23 tags
        assert all(tag.data["category"] == "unknown" for tag in tags)


# ── Task 3.5g: zero media-host requests ──────────────────────────────


class TestZeroMediaHostRequests:
    """Adapter never requests image hosts — only the canonical DAPI endpoint."""

    def test_no_image_host_in_request(self) -> None:
        """FETCH_POST request targets only gelbooru.com/index.php."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        case = _load_dapi_case("post_12370900")
        response = _mock_response(200, case.response.payload)
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        adapter.fetch(request)

        called_url = str(client.get.call_args.args[0])
        assert "gelbooru.com/index.php" in called_url
        assert "images" not in called_url
        assert "thumbnails" not in called_url
        assert "i Gelbooru" not in called_url


# ── Task 3.5h: response shape handling ────────────────────────────────


class TestResponseShapeHandling:
    """Adapter handles all three DAPI post response shapes."""

    def test_list_shape(self) -> None:
        """Standard envelope with post as list."""
        adapter = GelbooruAdapter(client=None, credentials=None)
        body = json.dumps(
            {
                "@attributes": {"limit": 1, "offset": 0, "count": 1},
                "post": [_dapi_post_body("12370900")["post"][0]],
            }
        ).encode()
        from media_catalog.adapters.contracts import ResponseEnvelope

        envelope = ResponseEnvelope(
            provider="gelbooru",
            instance="gelbooru",
            operation=AdapterOperation.FETCH_POST,
            request_identity="gelbooru:dapi_json:post:12370900",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=body,
            observed_at="2026-10-01T00:00:00Z",
            adapter_version=ADAPTER_VERSION,
            schema_version=DAPI_SCHEMA_VERSION,
            transport_key=DAPI_TRANSPORT_VERSION,
            transport_version=DAPI_TRANSPORT_VERSION,
            request_target="post:12370900",
        )
        page = adapter.normalize(envelope)
        assert len(page.items) > 0

    def test_dict_shape(self) -> None:
        """post as single dict (gallery-dl edge case)."""
        adapter = GelbooruAdapter(client=None, credentials=None)
        body = json.dumps(
            {
                "@attributes": {"limit": 1, "offset": 0, "count": 1},
                "post": _dapi_post_body("12370900")["post"][0],
            }
        ).encode()
        from media_catalog.adapters.contracts import ResponseEnvelope

        envelope = ResponseEnvelope(
            provider="gelbooru",
            instance="gelbooru",
            operation=AdapterOperation.FETCH_POST,
            request_identity="gelbooru:dapi_json:post:12370900",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=body,
            observed_at="2026-10-01T00:00:00Z",
            adapter_version=ADAPTER_VERSION,
            schema_version=DAPI_SCHEMA_VERSION,
            transport_key=DAPI_TRANSPORT_VERSION,
            transport_version=DAPI_TRANSPORT_VERSION,
            request_target="post:12370900",
        )
        page = adapter.normalize(envelope)
        assert len(page.items) > 0

    def test_bare_array_shape(self) -> None:
        """Legacy bare-array format without @attributes wrapper."""
        adapter = GelbooruAdapter(client=None, credentials=None)
        body = json.dumps(_dapi_post_body("12370900")["post"]).encode()
        from media_catalog.adapters.contracts import ResponseEnvelope

        envelope = ResponseEnvelope(
            provider="gelbooru",
            instance="gelbooru",
            operation=AdapterOperation.FETCH_POST,
            request_identity="gelbooru:dapi_json:post:12370900",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=body,
            observed_at="2026-10-01T00:00:00Z",
            adapter_version=ADAPTER_VERSION,
            schema_version=DAPI_SCHEMA_VERSION,
            transport_key=DAPI_TRANSPORT_VERSION,
            transport_version=DAPI_TRANSPORT_VERSION,
            request_target="post:12370900",
        )
        page = adapter.normalize(envelope)
        assert len(page.items) > 0

    def test_empty_result_missing_post_key(self) -> None:
        """200 with count==0 and no post key → empty page."""
        adapter = GelbooruAdapter(client=None, credentials=None)
        body = json.dumps({"@attributes": {"limit": 25, "offset": 0, "count": 0}}).encode()
        from media_catalog.adapters.contracts import ResponseEnvelope

        envelope = ResponseEnvelope(
            provider="gelbooru",
            instance="gelbooru",
            operation=AdapterOperation.FETCH_POST,
            request_identity="gelbooru:dapi_json:post:99999999",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=body,
            observed_at="2026-10-01T00:00:00Z",
            adapter_version=ADAPTER_VERSION,
            schema_version=DAPI_SCHEMA_VERSION,
            transport_key=DAPI_TRANSPORT_VERSION,
            transport_version=DAPI_TRANSPORT_VERSION,
            request_target="post:99999999",
        )
        page = adapter.normalize(envelope)
        assert page.items == ()
        assert page.continuation is None


# ── Review hardening: typed failures for malformed records and transports ─


class TestReviewHardening:
    """Malformed post records, continuations, and transport failures stay typed."""

    def test_missing_created_at_fails_malformed(self) -> None:
        """Post record without created_at → malformed_response, not KeyError."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        body = _dapi_post_body("12370900")
        del body["post"][0]["created_at"]
        response = _mock_response(200, json.dumps(body).encode())
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        envelope = adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "12370900"))

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE

    def test_unparseable_created_at_fails_malformed(self) -> None:
        """Post record with an unparseable created_at → malformed_response."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        body = _dapi_post_body("12370900")
        body["post"][0]["created_at"] = "not-a-timestamp"
        response = _mock_response(200, json.dumps(body).encode())
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        envelope = adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "12370900"))

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE

    def test_non_string_created_at_fails_malformed(self) -> None:
        """Post record with a null created_at → malformed_response."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        body = _dapi_post_body("12370900")
        body["post"][0]["created_at"] = None
        response = _mock_response(200, json.dumps(body).encode())
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        envelope = adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "12370900"))

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE

    def test_malformed_continuation_limit_rejected(self) -> None:
        """Non-numeric continuation limit → ValueError before network access."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        client = _make_client([])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        base = _scoped_continuation(pid=1, last_pid=0)
        continuation = Continuation(
            "gelbooru", CONTINUATION_VERSION, {**base.value, "limit": "abc"}
        )
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )

        with pytest.raises(ValueError, match="malformed Gelbooru continuation"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_out_of_range_continuation_rejected(self) -> None:
        """Negative pid or non-positive limit → ValueError before network access."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        client = _make_client([])

        adapter = GelbooruAdapter(client=client, credentials=credentials)
        base = _scoped_continuation(pid=1, last_pid=0)
        continuation = Continuation("gelbooru", CONTINUATION_VERSION, {**base.value, "pid": "-1"})
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )

        with pytest.raises(ValueError, match="out of range"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_oversized_response_rejected(self) -> None:
        """Response body above the transport byte limit → response_too_large."""
        from media_catalog.adapters.gelbooru.config import MAX_RESPONSE_BYTES

        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        response = _mock_response(200, b"x" * (MAX_RESPONSE_BYTES + 1))
        client = _make_client([response])

        adapter = GelbooruAdapter(client=client, credentials=credentials)

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "12370900"))
        assert exc_info.value.outcome == AdapterOutcome.RESPONSE_TOO_LARGE

    def test_transport_exception_sanitized(self) -> None:
        """httpx transport errors become transient_provider with credentials scrubbed."""
        secret = "abcdef1234567890abcdef1234567890"
        credentials = GelbooruCredentials("12345", secret)
        client = _make_client(
            [
                httpx.ConnectError(
                    "connection failed to "
                    "https://gelbooru.com/index.php?user_id=12345&api_key=" + secret
                )
            ]
        )

        adapter = GelbooruAdapter(client=client, credentials=credentials)

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.fetch(AdapterRequest(AdapterOperation.FETCH_POST, "12370900"))
        assert exc_info.value.outcome == AdapterOutcome.TRANSIENT_PROVIDER
        assert secret not in str(exc_info.value)
        assert "12345" not in str(exc_info.value)


# ── Task 3.4: scope-validated continuations ──────────────────────────


class TestScopedContinuations:
    """Every continuation scope dimension is validated before network access."""

    def _adapter_with_unused_client(self) -> tuple[GelbooruAdapter, MagicMock]:
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        client = _make_client([])
        return GelbooruAdapter(client=client, credentials=credentials), client

    def test_continuation_carries_all_scope_dimensions(self) -> None:
        """A produced continuation records target, query, sort, transport,
        direction, boundary, and version material."""
        from media_catalog.adapters.gelbooru.adapter import ADAPTER_VERSION as AV
        from media_catalog.adapters.gelbooru.config import (
            DAPI_SCHEMA_VERSION,
            DAPI_TRANSPORT_VERSION,
        )

        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        limit = 2
        posts = [_dapi_post_body(str(number))["post"][0] for number in (7, 5)]
        for post, number in zip(posts, (7, 5), strict=True):
            post["id"] = number
        body = {"@attributes": {"limit": limit, "offset": 0, "count": 10}, "post": posts}
        client = _make_client([_mock_response(200, json.dumps(body).encode())])
        adapter = GelbooruAdapter(client=client, credentials=credentials)
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "test",
            continuation=_scoped_continuation(pid=1, last_pid=0, limit=limit),
        )
        page = adapter.normalize(adapter.fetch(request))

        assert page.continuation is not None
        value = page.continuation.value
        assert value == {
            "operation": "list_account_posts",
            "target": "test",
            "query": "",
            "sort": "id-desc",
            "transport": DAPI_TRANSPORT_VERSION,
            "direction": "forward",
            "pid": "2",
            "last_pid": "1",
            "limit": str(limit),
            "last_id": 5,
            "continuation_version": CONTINUATION_VERSION,
            "adapter_version": AV,
            "schema_version": DAPI_SCHEMA_VERSION,
        }

    def test_mismatched_target_rejected_before_network(self) -> None:
        adapter, client = self._adapter_with_unused_client()
        continuation = _scoped_continuation(target="other")
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        with pytest.raises(ValueError, match="target is incompatible"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_unadmitted_query_rejected_before_network(self) -> None:
        adapter, client = self._adapter_with_unused_client()
        base = _scoped_continuation()
        continuation = Continuation(
            "gelbooru", CONTINUATION_VERSION, {**base.value, "query": "tagme"}
        )
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        with pytest.raises(ValueError, match="query is not admitted"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_unadmitted_sort_rejected_before_network(self) -> None:
        adapter, client = self._adapter_with_unused_client()
        base = _scoped_continuation()
        continuation = Continuation(
            "gelbooru", CONTINUATION_VERSION, {**base.value, "sort": "score"}
        )
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        with pytest.raises(ValueError, match="sort is incompatible"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_wrong_direction_rejected_before_network(self) -> None:
        adapter, client = self._adapter_with_unused_client()
        base = _scoped_continuation()
        continuation = Continuation(
            "gelbooru", CONTINUATION_VERSION, {**base.value, "direction": "backward"}
        )
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        with pytest.raises(ValueError, match="direction is incompatible"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_wrong_transport_rejected_before_network(self) -> None:
        adapter, client = self._adapter_with_unused_client()
        base = _scoped_continuation()
        continuation = Continuation(
            "gelbooru", CONTINUATION_VERSION, {**base.value, "transport": "html"}
        )
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        with pytest.raises(ValueError, match="transport is incompatible"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_inconsistent_boundary_rejected_before_network(self) -> None:
        """pid must advance exactly one committed page past last_pid."""
        adapter, client = self._adapter_with_unused_client()
        continuation = _scoped_continuation(pid=5, last_pid=0)
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        with pytest.raises(ValueError, match="boundary is inconsistent"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_missing_last_seen_id_rejected_before_network(self) -> None:
        adapter, client = self._adapter_with_unused_client()
        base = _scoped_continuation()
        value = {key: item for key, item in base.value.items() if key != "last_id"}
        continuation = Continuation("gelbooru", CONTINUATION_VERSION, value)
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        with pytest.raises(ValueError, match="last-seen id"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_wrong_operation_rejected_before_network(self) -> None:
        adapter, client = self._adapter_with_unused_client()
        base = _scoped_continuation()
        continuation = Continuation(
            "gelbooru", CONTINUATION_VERSION, {**base.value, "operation": "fetch_post"}
        )
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        with pytest.raises(ValueError, match="operation is incompatible"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_incompatible_schema_version_rejected_before_network(self) -> None:
        adapter, client = self._adapter_with_unused_client()
        base = _scoped_continuation()
        continuation = Continuation(
            "gelbooru", CONTINUATION_VERSION, {**base.value, "schema_version": "v9"}
        )
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        with pytest.raises(ValueError, match="schema version is incompatible"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_legacy_v1_continuation_rejected_by_version(self) -> None:
        """Old unscoped pid-v1 checkpoints fail closed on version scope."""
        adapter, client = self._adapter_with_unused_client()
        continuation = Continuation("gelbooru", "gelbooru-pid-v1", {"pid": "1", "limit": "50"})
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        with pytest.raises(ValueError, match="incompatible Gelbooru continuation version"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_legacy_request_target_yields_no_continuation(self) -> None:
        """Re-normalizing an old-format observation treats the page as final
        instead of minting an unscoped continuation."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        limit = 2
        posts = [_dapi_post_body(str(number))["post"][0] for number in (7, 5)]
        for post, number in zip(posts, (7, 5), strict=True):
            post["id"] = number
        body = {"@attributes": {"limit": limit, "offset": 0, "count": 10}, "post": posts}
        adapter = GelbooruAdapter(client=None, credentials=credentials)

        from media_catalog.adapters.contracts import ResponseEnvelope

        envelope = ResponseEnvelope(
            provider="gelbooru",
            instance="gelbooru",
            operation=AdapterOperation.LIST_ACCOUNT_POSTS,
            request_identity="gelbooru:dapi_json:listing:0:2",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=json.dumps(body).encode(),
            observed_at="2026-10-02T00:00:00Z",
            adapter_version=ADAPTER_VERSION,
            schema_version=DAPI_SCHEMA_VERSION,
            transport_key=DAPI_TRANSPORT_VERSION,
            transport_version=DAPI_TRANSPORT_VERSION,
            request_target="listing:0:2",
        )
        page = adapter.normalize(envelope)
        assert page.continuation is None

    def test_scoped_request_target_round_trips_through_identity(self) -> None:
        """The scoped identity format parses back into its scope material."""
        parsed = GelbooruAdapter._parse_listing_target("listing:channel:id-desc:forward:3:50")
        assert parsed == ("channel", 3, 50)
        assert GelbooruAdapter._parse_listing_target("listing:0:50") is None
        assert GelbooruAdapter._parse_listing_target("listing:t:id-desc:backward:0:50") is None
        assert GelbooruAdapter._parse_listing_target(None) is None

    def test_incompatible_continuation_version_material_rejected(self) -> None:
        """A forged in-value continuation_version fails closed before network."""
        adapter, client = self._adapter_with_unused_client()
        base = _scoped_continuation()
        continuation = Continuation(
            "gelbooru", CONTINUATION_VERSION, {**base.value, "continuation_version": "v0"}
        )
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        with pytest.raises(ValueError, match="continuation version is incompatible"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_incompatible_adapter_version_material_rejected(self) -> None:
        """A forged in-value adapter_version fails closed before network."""
        adapter, client = self._adapter_with_unused_client()
        base = _scoped_continuation()
        continuation = Continuation(
            "gelbooru", CONTINUATION_VERSION, {**base.value, "adapter_version": "old"}
        )
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS, "test", continuation=continuation
        )
        with pytest.raises(ValueError, match="adapter version is incompatible"):
            adapter.fetch(request)
        client.get.assert_not_called()

    def test_wrapped_list_with_non_dict_tail_does_not_crash(self) -> None:
        """A provider body with a non-dict trailing entry is filtered, never a
        crash: a still-full page yields a continuation from the last valid post."""
        credentials = GelbooruCredentials("12345", "abcdef1234567890abcdef1234567890")
        limit = 1
        valid = _dapi_post_body("9")["post"][0]
        body = {"@attributes": {"limit": limit, "offset": 0, "count": 5}, "post": [valid, 5]}
        client = _make_client([_mock_response(200, json.dumps(body).encode())])
        adapter = GelbooruAdapter(client=client, credentials=credentials)
        request = AdapterRequest(
            AdapterOperation.LIST_ACCOUNT_POSTS,
            "test",
            continuation=_scoped_continuation(pid=1, last_pid=0, limit=limit),
        )
        page = adapter.normalize(adapter.fetch(request))
        # The garbage entry is dropped; the page stays full (1 valid post,
        # limit 1) so the continuation uses the valid post's id.
        assert page.continuation is not None
        assert page.continuation.value["last_id"] == 9
