from __future__ import annotations

import httpx
import pytest

from media_catalog.adapters.gelbooru import (
    DAPI_SCHEMA_VERSION,
    DAPI_TRANSPORT_VERSION,
    GELBOORU,
    HTML_PARSER_VERSION,
    HTML_SCHEMA_VERSION,
    GelbooruCaptureError,
    GelbooruCaptureOversizedError,
    GelbooruCaptureRedirectError,
    GelbooruCaptureResult,
    GelbooruCaptureTimeoutError,
    GelbooruCredentials,
    GelbooruTransport,
    capture_gelbooru_dapi_post,
    capture_gelbooru_html_post,
    capture_gelbooru_post,
    validate_post_id,
)

SENTINEL_USER = "sentinel_user_id_999"
SENTINEL_KEY = "sentinel_api_key_xyz888"
CREDENTIALS = GelbooruCredentials(SENTINEL_USER, SENTINEL_KEY)
NOW = "2026-08-15T00:00:00Z"


def test_validate_post_id() -> None:
    assert validate_post_id(12370900) == "12370900"
    assert validate_post_id("12370900") == "12370900"
    assert validate_post_id(" 12370900 ") == "12370900"
    for invalid in (0, -1, "-1", "0", "²", "1" * 21, "secret_payload", "", "  "):
        with pytest.raises(ValueError) as exc:
            validate_post_id(invalid)
        assert "secret_payload" not in str(exc.value)
    for invalid_type in (True, False, 12.34, None, [1]):
        with pytest.raises(TypeError) as exc:
            validate_post_id(invalid_type)  # type: ignore[arg-type]
        assert "True" not in str(exc.value)


def test_dapi_exact_wire_request_and_auth_cookie_stripping() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b'{"post": [{"id": 12370900}]}'),
            headers={"content-type": "application/json; charset=utf-8"},
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        auth=("client_user", "client_pass"),
        cookies={"client_cookie": "cookie_secret"},
    )
    result = capture_gelbooru_dapi_post(
        12370900, client=client, credentials=CREDENTIALS, clock=lambda: NOW
    )
    assert len(requests) == 1
    req = requests[0]
    assert req.method == "GET"
    assert req.url.scheme == "https"
    assert req.url.host == "gelbooru.com"
    assert req.url.path == "/index.php"
    assert dict(req.url.params) == {
        "page": "dapi",
        "s": "post",
        "q": "index",
        "json": "1",
        "id": "12370900",
        "api_key": SENTINEL_KEY,
        "user_id": SENTINEL_USER,
    }
    assert req.headers.get("user-agent") == GELBOORU.user_agent
    assert "cookie" not in req.headers
    assert "authorization" not in req.headers

    assert isinstance(result, GelbooruCaptureResult)
    assert result.provider == "gelbooru"
    assert result.post_id == "12370900"
    assert result.transport_key == GelbooruTransport.DAPI_JSON.value
    assert result.transport_version == DAPI_TRANSPORT_VERSION
    assert result.parser_version == DAPI_SCHEMA_VERSION
    assert result.schema_version == DAPI_SCHEMA_VERSION
    assert result.status_code == 200
    assert result.content_type == "application/json; charset=utf-8"
    assert result.observed_at == NOW
    assert result.request_identity == "gelbooru:dapi_json:post:12370900"
    assert result.byte_count == len(result.payload)
    assert result.payload == b'{"post": [{"id": 12370900}]}'
    assert result.response_bytes == result.payload


def test_dapi_requires_credentials_before_network() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=httpx.ByteStream(b"ok"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="user ID and API key"):
        capture_gelbooru_post(GelbooruTransport.DAPI_JSON, 12370900, client=client)
    assert calls == 0


def test_html_exact_wire_request_and_cookie_isolation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"<!DOCTYPE html><html><body>post 12370900</body></html>"),
            headers={"content-type": "text/html; charset=utf-8"},
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        auth=("client_user", "client_pass"),
        cookies={"sentinel_cookie": "secret_cookie_value_999"},
    )
    result = capture_gelbooru_html_post("12370900", client=client, clock=lambda: NOW)
    assert len(requests) == 1
    req = requests[0]
    assert req.method == "GET"
    assert req.url.scheme == "https"
    assert req.url.host == "gelbooru.com"
    assert req.url.path == "/index.php"
    assert dict(req.url.params) == {"page": "post", "s": "view", "id": "12370900"}
    assert req.headers.get("user-agent") == GELBOORU.user_agent
    assert "cookie" not in req.headers
    assert "authorization" not in req.headers
    assert "api_key" not in req.url.params
    assert "user_id" not in req.url.params

    assert result.provider == "gelbooru"
    assert result.post_id == "12370900"
    assert result.transport_key == GelbooruTransport.HTML_POST.value
    assert result.transport_version == HTML_PARSER_VERSION
    assert result.parser_version == HTML_PARSER_VERSION
    assert result.schema_version == HTML_SCHEMA_VERSION
    assert result.status_code == 200
    assert result.content_type == "text/html; charset=utf-8"
    assert result.observed_at == NOW
    assert result.request_identity == "gelbooru:html_post:post:12370900"


def test_html_rejects_credentials() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=httpx.ByteStream(b"ok"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="HTML transport does not accept credentials"):
        capture_gelbooru_post(
            GelbooruTransport.HTML_POST, 12370900, client=client, credentials=CREDENTIALS
        )
    assert calls == 0


@pytest.mark.parametrize("status_code", [301, 302, 307, 308])
def test_rejects_redirects(status_code: int) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status_code,
            headers={"location": "https://gelbooru.com/other"},
            stream=httpx.ByteStream(b""),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GelbooruCaptureRedirectError, match=f"Redirect response {status_code}"):
        capture_gelbooru_dapi_post(12370900, client=client, credentials=CREDENTIALS)
    assert calls == 1


def test_size_and_time_limits_fail_closed() -> None:
    client_oversized = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=httpx.ByteStream(b"x" * 200))
        )
    )
    with pytest.raises(GelbooruCaptureOversizedError, match="exceeded maximum allowed size"):
        capture_gelbooru_dapi_post(
            12370900, client=client_oversized, credentials=CREDENTIALS, max_response_bytes=100
        )

    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    client_timeout = httpx.Client(transport=httpx.MockTransport(timeout_handler))
    with pytest.raises(GelbooruCaptureTimeoutError, match="timed out"):
        capture_gelbooru_dapi_post(12370900, client=client_timeout, credentials=CREDENTIALS)

    ticks = [0.0, 5.0, 20.0]
    client_stream_overrun = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=httpx.ByteStream(b"stream chunk 1 stream chunk 2"))
        )
    )
    with pytest.raises(GelbooruCaptureTimeoutError, match="Capture exceeded time limit"):
        capture_gelbooru_dapi_post(
            12370900,
            client=client_stream_overrun,
            credentials=CREDENTIALS,
            request_timeout_seconds=10.0,
            monotonic=lambda: ticks.pop(0) if ticks else 25.0,
        )


def test_credential_echo_fails_closed_and_secret_free() -> None:
    echo_payload = f'{{"error":"invalid key {SENTINEL_KEY}"}}'.encode()
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=httpx.ByteStream(echo_payload))
        )
    )
    with pytest.raises(GelbooruCaptureError) as exc_info:
        capture_gelbooru_dapi_post(12370900, client=client, credentials=CREDENTIALS)
    assert SENTINEL_KEY not in str(exc_info.value)
    assert SENTINEL_KEY not in repr(exc_info.value)
    assert "credential material" in str(exc_info.value)


def test_numeric_user_id_in_response_is_not_a_false_credential_echo() -> None:
    credentials = GelbooruCredentials("3", SENTINEL_KEY)
    body = b'{"post":[{"id":123,"creator_id":3,"score":30}]}'
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(body)))
    )
    result = capture_gelbooru_dapi_post(123, client=client, credentials=credentials)
    assert result.payload == body


@pytest.mark.parametrize("status", [401, 404, 500])
def test_error_status_is_captured_without_followup(status: int) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, stream=httpx.ByteStream(b"provider error"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = capture_gelbooru_dapi_post(123, client=client, credentials=CREDENTIALS)
    assert (result.status_code, result.payload, calls) == (status, b"provider error", 1)


def test_privacy_and_content_type_whitelist() -> None:
    secret_payload = b'{"post":[{"id":12370900,"file_url":"https://img3.gelbooru.com/sample.jpg"}]}'
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                stream=httpx.ByteStream(secret_payload),
                headers={"content-type": "application/json; secret_token=12345; charset=utf-8"},
            )
        )
    )
    result = capture_gelbooru_dapi_post(12370900, client=client, credentials=CREDENTIALS)
    manifest_dict = result.as_dict()
    result_repr = repr(result)

    for sentinel in (SENTINEL_USER, SENTINEL_KEY):
        assert sentinel not in result_repr
        assert sentinel not in str(manifest_dict)
        assert sentinel not in result.request_identity

    assert "https://img3.gelbooru.com" not in result_repr
    assert "https://img3.gelbooru.com" not in str(manifest_dict)
    assert "sample.jpg" not in result_repr
    assert "sample.jpg" not in str(manifest_dict)
    assert result.content_type == "application/json; charset=utf-8"
    assert "secret_token" not in result.content_type


def test_invalid_clock_text_is_generic() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(b"{}")))
    )
    with pytest.raises(ValueError) as exc:
        capture_gelbooru_dapi_post(
            12370900, client=client, credentials=CREDENTIALS, clock=lambda: "secret_bad_clock"
        )
    assert "secret_bad_clock" not in str(exc.value)


def test_unified_routing_and_parameter_validation() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(b"ok")))
    )
    res_dapi = capture_gelbooru_post("dapi_json", 12370900, client=client, credentials=CREDENTIALS)
    assert res_dapi.transport_key == "dapi_json"
    res_html = capture_gelbooru_post(GelbooruTransport.HTML_POST, 12370900, client=client)
    assert res_html.transport_key == "html_post"
    with pytest.raises(ValueError):
        capture_gelbooru_post("invalid_transport", 12370900, client=client)

    with pytest.raises(ValueError, match="positive"):
        capture_gelbooru_post(
            GelbooruTransport.DAPI_JSON,
            123,
            client=client,
            credentials=CREDENTIALS,
            max_response_bytes=0,
        )
    with pytest.raises(ValueError, match="positive"):
        capture_gelbooru_post(
            GelbooruTransport.DAPI_JSON,
            123,
            client=client,
            credentials=CREDENTIALS,
            request_timeout_seconds=True,  # type: ignore[arg-type]
        )
