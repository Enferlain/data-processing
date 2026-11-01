"""Native pawchive (kemono API family) metadata adapter.

Every contract fact here is live-captured (2026-11-01, anonymous):

- ``GET /api/v1/{service}/user/{id}/profile`` — flat creator object.
- ``GET /api/v1/{service}/user/{id}/posts?o={offset}`` — a bare array of at
  most 50 posts; offset pagination, no limit parameter.  The requested
  offset is embedded in the durable request target (the gelbooru pid
  pattern) so normalization can derive the next offset without client state.
- ``GET /api/v1/{service}/user/{id}/post/{post_id}`` — a flat post object
  (plus ``next``/``prev`` sibling ids), not the ``{post, attachments}``
  envelope older consumers expect.
- Media entries are ``{name, path}`` in the stable form; paywalled-preview
  posts add ``preview_only`` and an expiring signed ``temp_url`` that the
  catalog never retains (the sankaku signature rule).  The original-by-stable
  -path host no longer serves anonymous requests; only the thumbnail host
  does, so occurrences carry ``name``+``path`` identity and a thumbnail URL.
- ``tags`` is a brace-wrapped comma string (``"{A,B,C}"``) or null — not an
  array (observed on a large captured page that the fixture size cap keeps
  out of the suite; the manifest records that evidence).
"""

from __future__ import annotations

import datetime as _datetime
import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

import httpx

from media_catalog.adapters.contracts import (
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    AdapterRequest,
    Continuation,
    NormalizedItem,
    NormalizedPage,
    ResponseEnvelope,
)
from media_catalog.adapters.pawchive.config import (
    ADAPTER_VERSION,
    API_ROOT,
    CONTINUATION_VERSION,
    PAWCHIVE,
    PROVIDER_KEY,
    SCHEMA_VERSION,
    THUMBNAIL_BASE_URL,
    PawchiveInstance,
)

__all__ = [
    "ADAPTER_VERSION",
    "PAWCHIVE",
    "PROVIDER_KEY",
    "SCHEMA_VERSION",
    "PawchiveAdapter",
    "PawchiveInstance",
]


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, f"missing {label}")
    return value


def _account_target(target: str) -> tuple[str, str]:
    parts = target.split(":")
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise ValueError("pawchive account target must be service:user-id")
    return parts[0], parts[1]


def _post_target(target: str) -> tuple[str, str, str]:
    parts = target.split(":")
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise ValueError("pawchive post target must be service:user-id:post-id")
    return parts[0], parts[1], parts[2]


class PawchiveAdapter:
    """Metadata-only adapter for the pawchive instance of the kemono API."""

    provider_key = PROVIDER_KEY
    adapter_version = ADAPTER_VERSION
    schema_version = SCHEMA_VERSION
    # Single maintained instance: the platform key is the instance key.  A
    # revived family sibling reintroduces per-instance identity here.
    instance_key = PROVIDER_KEY

    def __init__(
        self,
        instance: PawchiveInstance = PAWCHIVE,
        *,
        client: httpx.Client,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.instance = instance
        self._client = client
        self._clock = clock or _default_clock

    @property
    def minimum_interval_seconds(self) -> float:
        """The authoritative provider pacing floor exposed for the request gate."""

        return self.instance.minimum_interval_seconds

    # ── Transport ───────────────────────────────────────────────────────

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        endpoint, params, identity, request_target = self._request_parts(request)
        response = self._client.get(
            self.instance.base_url + endpoint,
            params=params,
            headers={
                "User-Agent": self.instance.user_agent,
                # Evidenced on every live capture (2026-11-01); the captured
                # header stays exactly as served.
                "Accept": "text/css",
            },
        )
        if len(response.content) > self.instance.max_response_bytes:
            raise AdapterFailure(
                AdapterOutcome.RESPONSE_TOO_LARGE,
                "pawchive response exceeded the transport byte limit",
                status_code=response.status_code,
            )
        return ResponseEnvelope(
            provider=self.provider_key,
            instance=self.instance_key,
            operation=request.operation,
            request_identity=identity,
            status_code=response.status_code,
            headers=_public_headers(response.headers),
            payload=response.content or b"{}",
            observed_at=self._clock(),
            adapter_version=self.adapter_version,
            schema_version=self.schema_version,
            request_target=request_target,
        )

    def _request_parts(self, request: AdapterRequest) -> tuple[str, dict[str, str], str, str]:
        operation = request.operation
        if operation is AdapterOperation.FETCH_ACCOUNT:
            service, user_id = _account_target(request.target)
            endpoint = f"{API_ROOT}/{_seg(service)}/user/{_seg(user_id)}/profile"
            identity = f"{self.instance_key}:fetch_account:{service}:{user_id}"
            return endpoint, {}, identity, f"account:{service}:{user_id}"
        if operation is AdapterOperation.FETCH_POST:
            service, user_id, post_id = _post_target(request.target)
            endpoint = f"{API_ROOT}/{_seg(service)}/user/{_seg(user_id)}/post/{_seg(post_id)}"
            identity = f"{self.instance_key}:fetch_post:{service}:{user_id}:{post_id}"
            return endpoint, {}, identity, f"post:{service}:{user_id}:{post_id}"
        if operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            service, user_id = _account_target(request.target)
            offset = _listing_offset(request.continuation)
            endpoint = f"{API_ROOT}/{_seg(service)}/user/{_seg(user_id)}/posts"
            identity = f"{self.instance_key}:list_account_posts:{service}:{user_id}"
            return (
                endpoint,
                {"o": str(offset)},
                identity,
                f"listing:{service}:{user_id}:{offset}",
            )
        raise AdapterFailure(
            AdapterOutcome.MALFORMED_RESPONSE,
            f"unsupported pawchive operation: {operation.value}",
        )

    # ── Normalization ───────────────────────────────────────────────────

    def normalize(self, response: ResponseEnvelope) -> NormalizedPage:
        self._validate_envelope(response)
        self._raise_for_outcome(response)
        try:
            body = json.loads(response.payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "provider returned invalid JSON"
            ) from error
        operation = response.operation
        if operation is AdapterOperation.FETCH_ACCOUNT:
            return NormalizedPage(tuple(self._account_items(body)))
        if operation is AdapterOperation.FETCH_POST:
            return NormalizedPage(tuple(self._post_items(body)))
        if operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            return self._listing_page(body, response.request_target or "")
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "unsupported response operation")

    def _listing_page(self, body: object, request_target: str) -> NormalizedPage:
        if not isinstance(body, list):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "post listing must be a JSON array"
            )
        items: list[NormalizedItem] = []
        for entry in body:
            items.extend(self._post_items(entry))
        # The offset rides the durable request target, but offline replay
        # rebuilds envelopes without one; a full replayed page then has no
        # derivable next offset and is treated as terminal (the gelbooru
        # listing precedent) instead of failing a perfectly valid payload.
        offset = _target_offset(request_target)
        continuation = None
        if offset is not None and len(body) >= self.instance.page_size:
            continuation = Continuation(
                adapter=PROVIDER_KEY,
                version=CONTINUATION_VERSION,
                value={"offset": offset + len(body)},
            )
        return NormalizedPage(tuple(items), continuation)

    def _account_items(self, body: object) -> list[NormalizedItem]:
        if (
            not isinstance(body, dict)
            or isinstance(body.get("id"), bool)
            or not isinstance(body.get("id"), (str, int))
        ):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "account response has no stable id"
            )
        service = _nonempty_text(body.get("service"), "account service")
        return [
            NormalizedItem(
                object_kind="account",
                native_id=str(body["id"]),
                data={
                    "platform": self.instance_key,
                    "name": body.get("name"),
                    "service": service,
                    "public_id": body.get("public_id"),
                    "indexed_at": body.get("indexed"),
                    "updated_at": body.get("updated"),
                    "availability": "available",
                },
            )
        ]

    def _post_items(self, body: object) -> list[NormalizedItem]:
        if (
            not isinstance(body, dict)
            or isinstance(body.get("id"), bool)
            or not isinstance(body.get("id"), (str, int))
            or not str(body.get("id")).strip()
        ):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "post response has no stable id"
            )
        user = body.get("user")
        service = body.get("service")
        if (
            isinstance(user, bool)
            or not isinstance(user, (str, int))
            or not isinstance(service, str)
        ):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "post response lacks creator identity"
            )
        post_id = str(body["id"])
        user_id = str(user)
        items: list[NormalizedItem] = [
            NormalizedItem(
                object_kind="post",
                native_id=post_id,
                data={
                    "platform": self.instance_key,
                    "service": service,
                    "user_id": user_id,
                    "canonical_url": (
                        f"{self.instance.base_url}/{service}/user/{user_id}/post/{post_id}"
                    ),
                    "title": body.get("title"),
                    "content": body.get("content"),
                    "created_at": body.get("published"),
                    "updated_at": body.get("edited"),
                    "availability": "available",
                },
            ),
            NormalizedItem(
                object_kind="account",
                native_id=user_id,
                data={"platform": self.instance_key, "name": None, "service": service},
            ),
            NormalizedItem(
                object_kind="post_participant",
                native_id=f"{post_id}:creator:{user_id}",
                data={
                    "platform": self.instance_key,
                    "post_id": post_id,
                    "account_id": user_id,
                    "role": "creator",
                },
            ),
        ]
        for position, tag in enumerate(_parse_tags(body.get("tags"))):
            items.append(
                NormalizedItem(
                    object_kind="post_tag",
                    native_id=f"{post_id}:{tag}",
                    data={
                        "platform": self.instance_key,
                        "post_id": post_id,
                        "category": "unknown",
                        "normalized_name": tag,
                        "spelling": tag,
                        "position": position,
                    },
                )
            )
        for index, entry in enumerate(_media_entries(body)):
            path = entry.get("path")
            if not isinstance(path, str) or not path:
                # Evidence-free entries (observed: ``file: {}``) stay absent
                # rather than becoming empty occurrences.
                continue
            name = entry.get("name")
            preview_only = bool(entry.get("preview_only"))
            source_key = "primary" if index == 0 else f"attachment-{index}"
            occurrence: dict[str, Any] = {
                "platform": self.instance_key,
                "post_id": post_id,
                "source_key": source_key,
                "index": 0 if index == 0 else index,
                "role": "primary" if index == 0 else "attachment",
                "file_name": name if isinstance(name, str) else None,
                "path": path,
                "preview_only": preview_only,
                # Expiring signed temp URLs are never retained (sankaku rule).
                "remote_url": None,
                "variants": [
                    {
                        "role": "thumbnail",
                        "url": THUMBNAIL_BASE_URL + path,
                        "preview_only": preview_only,
                    }
                ],
            }
            items.append(
                NormalizedItem(
                    object_kind="media_occurrence",
                    native_id=f"{post_id}:{source_key}",
                    data=occurrence,
                )
            )
        return items

    # ── Outcomes ────────────────────────────────────────────────────────

    def _validate_envelope(self, response: ResponseEnvelope) -> None:
        if response.provider != self.provider_key or response.instance != self.instance_key:
            raise ValueError("response belongs to another provider instance")
        if response.schema_version != self.schema_version:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "incompatible provider schema version"
            )

    def _raise_for_outcome(self, response: ResponseEnvelope) -> None:
        status = response.status_code
        if status == 401:
            raise AdapterFailure(
                AdapterOutcome.AUTHENTICATION_REQUIRED,
                "provider authentication is required",
                status_code=401,
            )
        if status == 403:
            raise AdapterFailure(
                AdapterOutcome.AUTHORIZATION_DENIED,
                "provider access was denied",
                status_code=403,
            )
        if status == 404:
            raise AdapterFailure(
                AdapterOutcome.UNAVAILABLE, "provider record is unavailable", status_code=404
            )
        if status == 410:
            raise AdapterFailure(
                AdapterOutcome.DELETED, "provider record is deleted", status_code=410
            )
        if status == 429:
            raise AdapterFailure(
                AdapterOutcome.RATE_LIMITED, "provider rate limit reached", status_code=429
            )
        if status >= 500:
            raise AdapterFailure(
                AdapterOutcome.TRANSIENT_PROVIDER,
                "provider is temporarily unavailable",
                status_code=status,
            )
        if not 200 <= status < 300:
            raise AdapterFailure(
                AdapterOutcome.UNAVAILABLE,
                "provider request was unsuccessful",
                status_code=status,
            )


def _media_entries(body: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    entries: list[Mapping[str, Any]] = []
    file_entry = body.get("file")
    if isinstance(file_entry, dict) and file_entry:
        entries.append(file_entry)
    attachments = body.get("attachments")
    if isinstance(attachments, list):
        entries.extend(entry for entry in attachments if isinstance(entry, dict))
    return entries


def _parse_tags(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, str):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "tags must be text or null")
    text = value.strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    return [part.strip() for part in text.split(",") if part.strip()]


def _listing_offset(continuation: Continuation | None) -> int:
    if continuation is None:
        return 0
    if continuation.adapter != PROVIDER_KEY or continuation.version != CONTINUATION_VERSION:
        raise ValueError("incompatible pawchive listing continuation")
    offset = continuation.value.get("offset")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("incompatible pawchive listing continuation")
    return offset


def _target_offset(request_target: str) -> int | None:
    parts = request_target.split(":")
    if len(parts) != 4 or parts[0] != "listing":
        return None
    try:
        return int(parts[3])
    except ValueError:
        return None


def _seg(value: str) -> str:
    return quote(value.strip(), safe="")


def _public_headers(headers: httpx.Headers) -> dict[str, str]:
    allowed = {"content-type", "retry-after", "x-rate-limit"}
    return {key: value for key, value in headers.items() if key.lower() in allowed}


def _default_clock() -> str:
    return _datetime.datetime.now(_datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
