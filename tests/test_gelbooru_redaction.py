from __future__ import annotations

import httpx
import pytest

from media_catalog.adapters.gelbooru import (
    REDACTED,
    GelbooruCaptureError,
    GelbooruCredentials,
    capture_gelbooru_dapi_post,
    sanitize_exception,
    sanitize_mapping,
    sanitize_message,
    sanitize_text,
    sanitize_url,
)

SENTINEL_USER = "sentinel_user_id_999"
SENTINEL_KEY = "sentinel_api_key_xyz888"
CREDENTIALS = GelbooruCredentials(SENTINEL_USER, SENTINEL_KEY)
SECRETS = (SENTINEL_USER, SENTINEL_KEY)

AUTHENTICATED_URL = (
    "https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1&id=12370900"
    f"&api_key={SENTINEL_KEY}&user_id={SENTINEL_USER}"
)


def test_sanitize_text_replaces_every_secret_occurrence() -> None:
    scrubbed = sanitize_text(
        f"key={SENTINEL_KEY} user={SENTINEL_USER} key again {SENTINEL_KEY}", SECRETS
    )
    assert SENTINEL_USER not in scrubbed
    assert SENTINEL_KEY not in scrubbed
    assert scrubbed.count(REDACTED) == 3


def test_sanitize_text_skips_empty_secrets() -> None:
    assert sanitize_text("ordinary text", ("", SENTINEL_KEY)) == "ordinary text"


def test_sanitize_url_drops_only_credential_parameters() -> None:
    assert sanitize_url(AUTHENTICATED_URL) == (
        "https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1&id=12370900"
    )
    assert sanitize_url("https://gelbooru.com/index.php") == "https://gelbooru.com/index.php"


def test_sanitize_message_scrubs_embedded_authenticated_urls() -> None:
    scrubbed = sanitize_message(f"connection failed for {AUTHENTICATED_URL} retry later", SECRETS)
    assert SENTINEL_USER not in scrubbed
    assert SENTINEL_KEY not in scrubbed
    assert "api_key" not in scrubbed
    assert "user_id" not in scrubbed
    assert scrubbed.startswith("connection failed for https://gelbooru.com/index.php?")


def test_sanitize_exception_scrubs_transport_errors() -> None:
    scrubbed = sanitize_exception(httpx.ConnectError(f"failed for {AUTHENTICATED_URL}"), SECRETS)
    assert SENTINEL_USER not in scrubbed
    assert SENTINEL_KEY not in scrubbed
    assert "api_key" not in scrubbed


def test_sanitize_mapping_scrubs_nested_durable_material() -> None:
    attempt = {
        "request_url": AUTHENTICATED_URL,
        "detail": f"sent with {SENTINEL_KEY}",
        "nested": [f"response for {AUTHENTICATED_URL}", 7],
    }
    scrubbed = sanitize_mapping(attempt, SECRETS)
    rendered = str(scrubbed)
    assert SENTINEL_USER not in rendered
    assert SENTINEL_KEY not in rendered
    assert "api_key" not in rendered
    assert attempt["nested"][1] == 7


def test_credential_values_never_render_directly() -> None:
    assert SENTINEL_USER not in repr(CREDENTIALS)
    assert SENTINEL_KEY not in repr(CREDENTIALS)


def test_authenticated_query_joins_credentials_only_at_the_boundary() -> None:
    base = {"page": "dapi", "s": "post", "q": "index", "json": "1", "id": "42"}
    rendered = CREDENTIALS.authenticated_query(base)
    assert rendered == {
        "page": "dapi",
        "s": "post",
        "q": "index",
        "json": "1",
        "id": "42",
        "user_id": SENTINEL_USER,
        "api_key": SENTINEL_KEY,
    }
    assert base == {"page": "dapi", "s": "post", "q": "index", "json": "1", "id": "42"}


def test_capture_transport_errors_surface_sanitized_messages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connection failed for {request.url}")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(GelbooruCaptureError) as exc_info,
    ):
        capture_gelbooru_dapi_post(12370900, client=client, credentials=CREDENTIALS)

    message = str(exc_info.value)
    assert SENTINEL_USER not in message
    assert SENTINEL_KEY not in message
    assert "api_key" not in message
    assert "user_id" not in message
