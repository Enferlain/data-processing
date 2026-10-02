"""Task 4.4: focused tests for the Gelbooru anonymous HTML adapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from media_catalog.adapters.contracts import (
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    AdapterRequest,
)
from media_catalog.adapters.gelbooru import (
    HTML_PARSER_VERSION,
    HTML_SCHEMA_VERSION,
    GelbooruHtmlAdapter,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"

#: Raw Gelbooru CSS tag classes mapped onto the neutral category vocabulary.
_NEUTRAL_CATEGORY = {"metadata": "meta"}


def _load_html_case(name: str):
    from media_catalog.adapters.fixtures import load_fixture_suite

    suite = load_fixture_suite(FIXTURES / "gelbooru_html.json")
    return next(c for c in suite.cases if c.name == name)


def _html_body(case) -> str:
    """Decode the fixture payload from JSON-serialized bytes to HTML string."""
    return json.loads(case.response.payload)


def _mock_response(
    status_code: int, payload_bytes: bytes, content_type: str = "text/html; charset=utf-8"
):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.content = payload_bytes
    response.headers = httpx.Headers({"content-type": content_type})
    return response


def _make_client(responses):
    client = MagicMock(spec=httpx.Client)
    client.get = MagicMock(side_effect=list(responses))
    return client


# ── Task 4.4a: one-response behavior ─────────────────────────────────


class TestOneResponseBehavior:
    """HTML transport performs exactly one bounded HTTPS request."""

    def test_single_post_requests_once(self) -> None:
        """HTML fetch performs exactly one GET request."""
        case = _load_html_case("html_post_12370900")
        response = _mock_response(200, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        adapter.fetch(request)

        assert client.get.call_count == 1

    def test_no_credentials_accepted(self) -> None:
        """HTML adapter does not accept or use credentials."""
        case = _load_html_case("html_post_12370900")
        response = _mock_response(200, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        adapter.fetch(request)

        # Verify no credential params in the request
        called_url = str(client.get.call_args.args[0])
        called_params = client.get.call_args.kwargs.get("params", {})
        assert "user_id" not in called_params
        assert "api_key" not in called_params
        assert "gelbooru.com/index.php" in called_url

    def test_only_fetch_post_supported(self) -> None:
        """HTML transport only supports FETCH_POST; other operations raise."""
        client = _make_client([])
        adapter = GelbooruHtmlAdapter(client=client)

        with pytest.raises(AdapterFailure, match="HTML transport only supports fetch_post"):
            adapter.fetch(AdapterRequest(AdapterOperation.FETCH_TAG, "test"))

    def test_no_secondary_requests(self) -> None:
        """HTML adapter never requests image hosts or follows redirects."""
        case = _load_html_case("html_post_12370900")
        response = _mock_response(200, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        adapter.fetch(request)

        called_url = str(client.get.call_args.args[0])
        assert "gelbooru.com/index.php" in called_url
        assert "img4.gelbooru.com" not in called_url


# ── Task 4.4b: canonical request identity ────────────────────────────


class TestCanonicalRequestIdentity:
    """HTML requests use the canonical endpoint and identity format."""

    def test_request_identity_format(self) -> None:
        """Request identity follows gelbooru:html_post:post:<id> pattern."""
        case = _load_html_case("html_post_12370900")
        response = _mock_response(200, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)

        assert envelope.request_identity == "gelbooru:html_post:post:12370900"
        assert envelope.transport_key == HTML_PARSER_VERSION
        assert envelope.transport_version == HTML_PARSER_VERSION
        assert envelope.schema_version == HTML_SCHEMA_VERSION

    def test_canonical_url(self) -> None:
        """Request targets the canonical Gelbooru post page."""
        case = _load_html_case("html_post_12370900")
        response = _mock_response(200, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        adapter.fetch(request)

        called_url = str(client.get.call_args.args[0])
        assert called_url == "https://gelbooru.com/index.php"


# ── Task 4.4c: bounded parsing ───────────────────────────────────────


class TestBoundedParsing:
    """HTML parser only extracts fixture-proven stable markers."""

    def test_success_parses_all_markers(self) -> None:
        """Successful HTML page yields post, account, tags, media, and reference items."""
        case = _load_html_case("html_post_12370900")
        response = _mock_response(200, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)
        page = adapter.normalize(envelope)

        kinds = {item.object_kind for item in page.items}
        assert "post" in kinds
        assert "account" in kinds
        assert "post_participant" in kinds
        assert "post_tag" in kinds
        assert "media_occurrence" in kinds
        assert "external_reference" in kinds

    def test_category_preservation_from_css_classes(self) -> None:
        """HTML tag-type-* CSS classes map to neutral categories."""
        case = _load_html_case("html_post_12370900")
        response = _mock_response(200, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)
        page = adapter.normalize(envelope)

        tags = [item for item in page.items if item.object_kind == "post_tag"]
        categories = {tag.data["category"] for tag in tags}
        # Fixture CSS classes artist/copyright/general/metadata map onto the
        # neutral vocabulary (metadata → meta).
        assert "artist" in categories
        assert "general" in categories
        expected = {_NEUTRAL_CATEGORY.get(name, name) for name in case.expected["tag_categories"]}
        assert categories == expected

    def test_no_media_bytes_parsed(self) -> None:
        """HTML parser only extracts URLs and dimensions, never downloads media."""
        case = _load_html_case("html_post_12370900")
        response = _mock_response(200, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)
        page = adapter.normalize(envelope)

        media = [item for item in page.items if item.object_kind == "media_occurrence"]
        assert len(media) == 1
        # HTML never reveals original file_url
        assert media[0].data["remote_url"] is None


# ── Task 4.4d: unavailable/challenge/malformed handling ───────────────


class TestFailClosedHandling:
    """HTML adapter fails closed on missing markers, challenge pages, and malformed input."""

    def test_missing_title_fails_closed(self) -> None:
        """No <title> → malformed_response."""
        html = "<html><body><p>No title here</p></body></html>"
        client = _make_client([_mock_response(200, html.encode())])
        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE

    def test_missing_image_element_fails_closed(self) -> None:
        """No <img id="image"> (with tag-list and Posted: present) → malformed_response."""
        html = (
            "<html><head><title>Test Post</title></head><body>"
            '<ul id="tag-list"></ul>'
            "Posted: 2025-01-01 10:00:00<br />"
            "</body></html>"
        )
        client = _make_client([_mock_response(200, html.encode())])
        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE

    def test_challenge_page_fails_authorization_denied(self) -> None:
        """Page with no tag-list and no Posted:/Uploader: → authorization_denied."""
        html = (
            "<html><head><title>Login Required</title></head>"
            "<body><p>Please log in</p></body></html>"
        )
        client = _make_client([_mock_response(200, html.encode())])
        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.AUTHORIZATION_DENIED

    def test_not_found_404_unavailable(self) -> None:
        """HTTP 404 → unavailable."""
        client = _make_client([_mock_response(404, b"{}")])
        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "99999999")
        envelope = adapter.fetch(request)

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.UNAVAILABLE
        assert exc_info.value.status_code == 404

    def test_challenge_403_authorization_denied(self) -> None:
        """HTTP 403 → authorization_denied."""
        client = _make_client([_mock_response(403, b"{}")])
        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.AUTHORIZATION_DENIED
        assert exc_info.value.status_code == 403

    def test_malformed_html_empty_payload(self) -> None:
        """Empty response payload → malformed_response."""
        client = _make_client([_mock_response(200, b"{}")])
        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE

    def test_malformed_non_utf8(self) -> None:
        """Non-UTF-8 response → malformed_response."""
        client = _make_client([_mock_response(200, b"\xff\xfe")])
        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE


# ── Task 4.4e: fixture-backed normalization ───────────────────────────


class TestFixtureBackedNormalization:
    """HTML adapter normalizes captured fixture pages correctly."""

    def test_html_post_12370900_normalization(self) -> None:
        """Full normalization of html_post_12370900 fixture."""
        case = _load_html_case("html_post_12370900")
        response = _mock_response(200, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)
        page = adapter.normalize(envelope)

        assert case.expected["outcome"] == "success"
        assert case.expected["post_ids"] == ["12370900"]

        items_by_kind = {item.object_kind: item for item in page.items}
        post = items_by_kind["post"]
        assert post.data["platform"] == "gelbooru"
        assert post.data["availability"] == "available"

        account = items_by_kind["account"]
        assert account.data["handle"] == case.expected["uploader"]

        tags = [item for item in page.items if item.object_kind == "post_tag"]
        tag_categories = {tag.data["category"] for tag in tags}
        expected = {_NEUTRAL_CATEGORY.get(name, name) for name in case.expected["tag_categories"]}
        assert tag_categories == expected

    def test_html_not_found_fixture(self) -> None:
        """html_not_found fixture produces unavailable outcome."""
        case = _load_html_case("html_not_found")
        response = _mock_response(404, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, case.target)
        envelope = adapter.fetch(request)

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.UNAVAILABLE

    def test_html_challenge_fixture(self) -> None:
        """Challenge page (no tag-list, no Posted:) produces authorization_denied."""
        case = _load_html_case("html_challenge")
        response = _mock_response(200, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, case.target)
        envelope = adapter.fetch(request)

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.AUTHORIZATION_DENIED

    def test_html_malformed_fixture(self) -> None:
        """html_malformed fixture produces malformed_response outcome."""
        case = _load_html_case("html_malformed")
        response = _mock_response(200, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, case.target)
        envelope = adapter.fetch(request)

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.normalize(envelope)
        assert exc_info.value.outcome == AdapterOutcome.MALFORMED_RESPONSE


# ── Task 4.4f: retry-attempt history and idempotency ──────────────────


class TestRetryAndIdempotency:
    """HTML adapter normalization is idempotent and does not retry."""

    def test_normalize_is_idempotent(self) -> None:
        """Same envelope produces identical page on repeated normalization."""
        case = _load_html_case("html_post_12370900")
        response = _mock_response(200, _html_body(case).encode())
        client = _make_client([response])

        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope = adapter.fetch(request)

        page_a = adapter.normalize(envelope)
        page_b = adapter.normalize(envelope)

        assert page_a.items == page_b.items
        assert page_a.continuation is None

    def test_retry_after_failure_is_independent(self) -> None:
        """Failed HTML fetch does not pollute subsequent fetches."""
        client = _make_client(
            [
                _mock_response(404, b"{}"),
                _mock_response(200, _html_body(_load_html_case("html_post_12370900")).encode()),
            ]
        )
        adapter = GelbooruHtmlAdapter(client=client)

        # First request fails
        request = AdapterRequest(AdapterOperation.FETCH_POST, "99999999")
        envelope1 = adapter.fetch(request)
        with pytest.raises(AdapterFailure):
            adapter.normalize(envelope1)

        # Second request succeeds independently
        request2 = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")
        envelope2 = adapter.fetch(request2)
        page = adapter.normalize(envelope2)
        assert len(page.items) > 0


# ── Review hardening: transport byte limit and typed transport failures ──


class TestTransportHardening:
    """Oversized bodies and transport errors produce typed outcomes."""

    def test_oversized_response_rejected(self) -> None:
        """Response body above the transport byte limit → response_too_large."""
        from media_catalog.adapters.gelbooru.config import MAX_RESPONSE_BYTES

        client = _make_client([_mock_response(200, b"x" * (MAX_RESPONSE_BYTES + 1))])
        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.fetch(request)
        assert exc_info.value.outcome == AdapterOutcome.RESPONSE_TOO_LARGE

    def test_transport_error_transient(self) -> None:
        """httpx transport errors become transient_provider."""
        client = MagicMock(spec=httpx.Client)
        client.get = MagicMock(
            side_effect=httpx.ConnectError("connection failed to https://gelbooru.com/")
        )
        adapter = GelbooruHtmlAdapter(client=client)
        request = AdapterRequest(AdapterOperation.FETCH_POST, "12370900")

        with pytest.raises(AdapterFailure) as exc_info:
            adapter.fetch(request)
        assert exc_info.value.outcome == AdapterOutcome.TRANSIENT_PROVIDER
