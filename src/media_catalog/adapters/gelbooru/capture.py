"""Credential-safe fixture capture utility for Gelbooru DAPI and HTML post requests."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from media_catalog.adapters.gelbooru.config import (
    DAPI_SCHEMA_VERSION,
    GELBOORU,
    HTML_PARSER_VERSION,
    GelbooruInstance,
    GelbooruTransport,
)
from media_catalog.adapters.gelbooru.credentials import GelbooruCredentials
from media_catalog.adapters.gelbooru.redaction import sanitize_exception

_ALLOWED_MEDIA_TYPES = {
    "application/json",
    "text/html",
    "text/plain",
    "application/xml",
    "text/xml",
}
_ALLOWED_CHARSETS = {"utf-8", "iso-8859-1", "us-ascii"}


class GelbooruCaptureError(Exception):
    """Base error for Gelbooru fixture capture failures."""


class GelbooruCaptureOversizedError(GelbooruCaptureError):
    """Raised when the response payload exceeds configured byte limits."""


class GelbooruCaptureTimeoutError(GelbooruCaptureError):
    """Raised when the request times out."""


class GelbooruCaptureRedirectError(GelbooruCaptureError):
    """Raised when a redirect response is received."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _transport_message(
    prefix: str, error: BaseException, credentials: GelbooruCredentials | None
) -> str:
    secrets = () if credentials is None else credentials.secret_values()
    detail = sanitize_exception(error, secrets)
    return f"{prefix}: {detail}" if detail else prefix


def validate_post_id(post_id: int | str) -> str:
    """Validate and normalize an explicit positive numeric post ID."""
    if isinstance(post_id, bool) or not isinstance(post_id, (int, str)):
        raise TypeError("post_id must be a positive numeric post ID")
    val = str(post_id).strip()
    if not val.isascii() or not val.isdigit() or len(val) > 20 or int(val) <= 0:
        raise ValueError("post_id must be a positive numeric post ID")
    return str(int(val))


def _sanitize_content_type(raw: str) -> str:
    parts = [p.strip().lower() for p in raw.split(";") if p.strip()]
    if not parts or parts[0] not in _ALLOWED_MEDIA_TYPES:
        return "application/octet-stream"
    for param in parts[1:]:
        if param.startswith("charset=") and param[8:].strip("\"'") in _ALLOWED_CHARSETS:
            return f"{parts[0]}; charset={param[8:].strip('"\'')}"
    return parts[0]


def _validate_timestamp(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("observed_at must be a valid ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError):
        raise ValueError("observed_at must be a valid ISO timestamp with timezone") from None


@dataclass(frozen=True, slots=True)
class GelbooruCaptureResult:
    """Immutable, secret-free manifest and raw payload for a captured Gelbooru post response."""

    provider: str
    post_id: str
    transport_key: str
    transport_version: str
    parser_version: str
    schema_version: str
    status_code: int
    content_type: str
    observed_at: str
    request_identity: str
    byte_count: int
    payload: bytes

    @property
    def response_bytes(self) -> bytes:
        return self.payload

    def __repr__(self) -> str:
        return (
            f"GelbooruCaptureResult(provider={self.provider!r}, post_id={self.post_id!r}, "
            f"transport_key={self.transport_key!r}, status_code={self.status_code}, "
            f"byte_count={self.byte_count})"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "post_id": self.post_id,
            "transport_key": self.transport_key,
            "transport_version": self.transport_version,
            "parser_version": self.parser_version,
            "schema_version": self.schema_version,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "observed_at": self.observed_at,
            "request_identity": self.request_identity,
            "byte_count": self.byte_count,
        }


def capture_gelbooru_post(
    transport: GelbooruTransport | str,
    post_id: int | str,
    *,
    client: httpx.Client,
    credentials: GelbooruCredentials | None = None,
    instance: GelbooruInstance = GELBOORU,
    max_response_bytes: int | None = None,
    request_timeout_seconds: float | None = None,
    clock: Callable[[], str] = _utc_now,
    monotonic: Callable[[], float] = time.monotonic,
) -> GelbooruCaptureResult:
    """Capture a single Gelbooru post response using the specified transport."""
    resolved = (
        transport if isinstance(transport, GelbooruTransport) else GelbooruTransport(transport)
    )
    validated_id = validate_post_id(post_id)
    max_bytes = instance.max_response_bytes if max_response_bytes is None else max_response_bytes
    timeout_sec = (
        instance.request_timeout_seconds
        if request_timeout_seconds is None
        else request_timeout_seconds
    )
    if (
        isinstance(max_bytes, bool)
        or isinstance(timeout_sec, bool)
        or max_bytes < 1
        or timeout_sec <= 0
    ):
        raise ValueError("max_response_bytes and request_timeout_seconds must be positive numbers")

    url = f"{instance.base_url}/index.php"
    headers = {"user-agent": instance.user_agent}
    transport_key = resolved.value
    transport_version = instance.transport_version(resolved)
    parser_version = (
        DAPI_SCHEMA_VERSION if resolved is GelbooruTransport.DAPI_JSON else HTML_PARSER_VERSION
    )
    request_identity = f"{instance.platform_key}:{transport_key}:post:{validated_id}"

    if resolved is GelbooruTransport.DAPI_JSON:
        if credentials is None:
            raise ValueError("both Gelbooru user ID and API key are required")
        # Credential values join the query only here, at the final DAPI HTTP boundary.
        params = credentials.authenticated_query(
            {
                "page": "dapi",
                "s": "post",
                "q": "index",
                "json": "1",
                "id": validated_id,
            }
        )
    elif resolved is GelbooruTransport.HTML_POST:
        if credentials is not None:
            raise ValueError("HTML transport does not accept credentials")
        params = {"page": "post", "s": "view", "id": validated_id}
    else:
        raise ValueError(f"unsupported transport: {resolved}")

    request = httpx.Request(
        "GET",
        url,
        params=params,
        headers=headers,
        extensions={
            "timeout": {
                "connect": timeout_sec,
                "read": timeout_sec,
                "write": timeout_sec,
                "pool": timeout_sec,
            }
        },
    )

    start_time, chunks, total_bytes = monotonic(), [], 0
    try:
        response = client.send(request, stream=True, follow_redirects=False, auth=None)
        try:
            if 300 <= response.status_code < 400:
                raise GelbooruCaptureRedirectError(
                    f"Redirect response {response.status_code} is rejected"
                )
            content_type = _sanitize_content_type(response.headers.get("content-type", ""))
            status_code = response.status_code
            for chunk in response.iter_raw():
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise GelbooruCaptureOversizedError(
                        f"Response exceeded maximum allowed size of {max_bytes} bytes"
                    )
                chunks.append(chunk)
                if monotonic() - start_time > timeout_sec:
                    raise GelbooruCaptureTimeoutError(
                        f"Capture exceeded time limit of {timeout_sec}s"
                    )
            if monotonic() - start_time > timeout_sec:
                raise GelbooruCaptureTimeoutError(f"Capture exceeded time limit of {timeout_sec}s")
        finally:
            response.close()
    except GelbooruCaptureError:
        raise
    except httpx.TimeoutException as error:
        raise GelbooruCaptureTimeoutError(
            _transport_message("Request timed out", error, credentials)
        ) from None
    except httpx.RequestError as error:
        raise GelbooruCaptureError(
            _transport_message("HTTP request failed", error, credentials)
        ) from None

    payload = b"".join(chunks)
    # Numeric user IDs are ordinary provider data and may legitimately occur in a post response.
    # The high-entropy API key must never be admitted into captured response bytes.
    if credentials is not None and credentials.api_key.encode() in payload:
        raise GelbooruCaptureError("Response payload contains credential material")

    return GelbooruCaptureResult(
        provider=instance.platform_key,
        post_id=validated_id,
        transport_key=transport_key,
        transport_version=transport_version,
        parser_version=parser_version,
        schema_version=instance.schema_version(resolved),
        status_code=status_code,
        content_type=content_type,
        observed_at=_validate_timestamp(clock()),
        request_identity=request_identity,
        byte_count=len(payload),
        payload=payload,
    )


def capture_gelbooru_dapi_post(
    post_id: int | str, *, client: httpx.Client, credentials: GelbooruCredentials, **kw: Any
) -> GelbooruCaptureResult:
    """Capture a single Gelbooru DAPI JSON post response."""
    return capture_gelbooru_post(
        GelbooruTransport.DAPI_JSON, post_id, client=client, credentials=credentials, **kw
    )


def capture_gelbooru_html_post(
    post_id: int | str, *, client: httpx.Client, **kw: Any
) -> GelbooruCaptureResult:
    """Capture a single Gelbooru HTML post response."""
    return capture_gelbooru_post(
        GelbooruTransport.HTML_POST, post_id, client=client, credentials=None, **kw
    )
