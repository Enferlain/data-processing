"""Sankaku capi adapter: bearer-token metadata fetches under the run contract.

The provider's API lives at one HTTPS host (live-verified 2026-10-29:
``sankakuapi.com``; the historical ``capi-v2`` host refuses this client).
Credentials are exchanged once per process for a bearer token that exists
only in HTTP headers; the login/password pair itself travels only to the
token endpoint, and neither secrets nor tokens ever reach durable identities,
observations, logs, or diagnostics.  Response contracts are blessed only by
the captured fixture suite (Bead data-processing-4ly).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from media_catalog.adapters import (
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    AdapterRequest,
    Continuation,
    NormalizedItem,
    NormalizedPage,
    ResponseEnvelope,
)
from media_catalog.adapters.sankaku.config import (
    ADAPTER_VERSION,
    API_SCHEMA_VERSION,
    CONTINUATION_VERSION,
    SANKAKU,
    TAG_CATEGORY_BY_TYPE,
    TRANSPORT_KEY,
    SankakuInstance,
)
from media_catalog.adapters.sankaku.credentials import SankakuCredentials

_POST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_INVALID_TOKEN_SUFFIXES = ("unauthorized", "invalid-token", "invalid_token")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _scrub(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def _unix_to_iso(value: str) -> str | None:
    try:
        seconds = int(value.strip())
        return datetime.fromtimestamp(seconds, tz=UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


class SankakuAdapter:
    """Metadata-only Sankaku client speaking the provider's API v2 shapes."""

    provider_key = "sankaku"
    adapter_version = ADAPTER_VERSION
    schema_version = API_SCHEMA_VERSION

    def __init__(
        self,
        instance: SankakuInstance = SANKAKU,
        *,
        client: httpx.Client,
        credentials: SankakuCredentials,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self.instance = instance
        self.instance_key = instance.platform_key
        self._client = client
        self._credentials = credentials
        self._clock = clock
        self._token: str | None = None

    @property
    def transport_key(self) -> str:
        return TRANSPORT_KEY

    @property
    def transport_version(self) -> str:
        return API_SCHEMA_VERSION

    @property
    def minimum_interval_seconds(self) -> float:
        return self.instance.minimum_interval_seconds

    # ── Token boundary ──────────────────────────────────────────────────

    def _exchange_token(self) -> str:
        """Exchange the external credentials for a process-ephemeral token."""
        secrets = self._credentials.secret_values()
        try:
            response = self._client.post(
                f"{self.instance.base_url}/auth/token",
                json={"login": self._credentials.login, "password": self._credentials.password},
                headers={"user-agent": self.instance.user_agent},
            )
        except httpx.HTTPError as error:
            raise AdapterFailure(
                AdapterOutcome.TRANSIENT_PROVIDER,
                f"Sankaku token transport error: {_scrub(str(error), secrets)}",
            ) from None
        if response.status_code >= 400:
            raise AdapterFailure(
                AdapterOutcome.AUTHENTICATION_REQUIRED,
                "Sankaku token exchange was refused",
                status_code=response.status_code,
            )
        try:
            document = response.json()
        except ValueError:
            raise AdapterFailure(
                AdapterOutcome.AUTHENTICATION_REQUIRED,
                "Sankaku token exchange returned a non-JSON body",
                status_code=response.status_code,
            ) from None
        token = document.get("access_token") if isinstance(document, dict) else None
        if not isinstance(document, dict) or not document.get("success") or not token:
            raise AdapterFailure(
                AdapterOutcome.AUTHENTICATION_REQUIRED,
                "Sankaku token exchange failed",
                status_code=response.status_code,
            )
        self._token = token
        return token

    def _authorized_get(self, endpoint: str, params: dict[str, str]) -> httpx.Response:
        """GET with the bearer token; one re-exchange on an invalid-token signal."""

        response: httpx.Response | None = None
        for attempt in (0, 1):
            if self._token is None:
                self._exchange_token()
            assert self._token is not None
            try:
                response = self._client.get(
                    endpoint,
                    params=params,
                    headers={
                        "user-agent": self.instance.user_agent,
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self._token}",
                    },
                )
            except httpx.HTTPError as error:
                secrets = (*self._credentials.secret_values(), self._token)
                raise AdapterFailure(
                    AdapterOutcome.TRANSIENT_PROVIDER,
                    f"Sankaku transport error: {_scrub(str(error), secrets)}",
                ) from None
            if attempt == 0 and self._token_invalid(response):
                self._token = None
                continue
            return response
        assert response is not None
        return response

    def _token_invalid(self, response: httpx.Response) -> bool:
        if response.status_code == 401:
            return True
        if response.status_code != 200:
            return False
        try:
            document = json.loads(response.content)
        except ValueError:
            return False
        if not isinstance(document, dict) or document.get("success") is not False:
            return False
        code = document.get("code")
        return isinstance(code, str) and code.endswith(_INVALID_TOKEN_SUFFIXES)

    # ── Request rendering ───────────────────────────────────────────────

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        """Render one API request and return the provider response as an envelope."""
        if request.operation is AdapterOperation.FETCH_POST:
            endpoint, params, identity, request_target = self._post_request(request.target)
        elif request.operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            endpoint, params, identity, request_target = self._listing_request(
                request.target, request.continuation
            )
        else:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                f"unsupported Sankaku operation: {request.operation.value}",
            )

        response = self._authorized_get(endpoint, params)
        if len(response.content) > self.instance.max_response_bytes:
            raise AdapterFailure(
                AdapterOutcome.RESPONSE_TOO_LARGE,
                "Sankaku response exceeded the transport byte limit",
                status_code=response.status_code,
            )
        return ResponseEnvelope(
            provider=self.provider_key,
            instance=self.instance_key,
            operation=request.operation,
            request_identity=identity,
            status_code=response.status_code,
            headers=dict(response.headers),
            payload=response.content or b"{}",
            observed_at=self._clock(),
            adapter_version=self.adapter_version,
            schema_version=self.schema_version,
            transport_key=self.transport_key,
            transport_version=self.transport_version,
            request_target=request_target,
        )

    def _post_request(self, target: str) -> tuple[str, dict[str, str], str, str]:
        post_id = self._opaque_post_id(target)
        params = {"lang": "en", "limit": "1", "tags": f"id_range:{post_id}"}
        identity = f"{self.instance_key}:api_v2:post:{post_id}"
        return f"{self.instance.base_url}/v2/posts", params, identity, f"post:{post_id}"

    def _listing_request(
        self, target: str, continuation: Continuation | None
    ) -> tuple[str, dict[str, str], str, str]:
        query = self._listing_target_text(target)
        cursor = self._listing_cursor(continuation, query)
        params: dict[str, str] = {
            "lang": "en",
            "limit": str(self.instance.page_size),
            "tags": query,
        }
        if cursor:
            params["next"] = cursor
        identity = f"{self.instance_key}:api_v2:listing:{query}:{cursor or 'start'}"
        request_target = f"listing:{query}:{cursor or 'start'}"
        return f"{self.instance.base_url}/v2/posts/keyset", params, identity, request_target

    @staticmethod
    def _opaque_post_id(target: str) -> str:
        value = target.strip()
        if not _POST_ID_PATTERN.fullmatch(value):
            raise ValueError("Sankaku post id must be an opaque [A-Za-z0-9_-] identifier")
        return value

    @staticmethod
    def _listing_target_text(target: str) -> str:
        value = target.strip()
        if not value or len(value) > 200 or any(ord(character) < 32 for character in value):
            raise ValueError("Sankaku listing target must be 1-200 printable characters")
        return value

    def _listing_cursor(self, continuation: Continuation | None, query: str) -> str | None:
        if continuation is None:
            return None
        if (
            continuation.adapter != self.instance_key
            or continuation.version != CONTINUATION_VERSION
        ):
            raise ValueError("malformed Sankaku continuation")
        value = continuation.value
        if not isinstance(value, Mapping) or set(value) != {"query", "next"}:
            raise ValueError("malformed Sankaku continuation")
        if value["query"] != query:
            raise ValueError("Sankaku continuation belongs to a different listing query")
        next_cursor = value["next"]
        if not isinstance(next_cursor, str) or not 0 < len(next_cursor) <= 256:
            raise ValueError("malformed Sankaku continuation")
        return next_cursor

    # ── Normalization ───────────────────────────────────────────────────

    def normalize(self, response: ResponseEnvelope) -> NormalizedPage:
        """Turn an API response envelope into a page of provider-neutral items."""
        self._validate_envelope(response)
        self._raise_for_outcome(response)
        try:
            body = json.loads(response.payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "provider returned invalid JSON",
            ) from error
        if (
            isinstance(body, dict)
            and body.get("success") is False
            and isinstance(body.get("code"), str)
            and body["code"].endswith(_INVALID_TOKEN_SUFFIXES)
        ):
            # A repeated invalid-token body after the fetch-time re-exchange.
            raise AdapterFailure(
                AdapterOutcome.AUTHENTICATION_REQUIRED,
                "Sankaku authentication failed",
                status_code=response.status_code,
            )

        if response.operation is AdapterOperation.FETCH_POST:
            if not isinstance(body, list):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "Sankaku post response is not an array",
                )
            if len(body) > 1:
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "Sankaku post query returned more than one post",
                )
            items: list[NormalizedItem] = []
            if body:
                items = self._post_items(body[0])
            return NormalizedPage(tuple(items))

        if response.operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "Sankaku keyset response is not a data/meta object",
                )
            meta = body.get("meta")
            if not isinstance(meta, dict):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "Sankaku keyset response has no meta object",
                )
            items = []
            for post in body["data"]:
                items.extend(self._post_items(post))
            next_cursor = meta.get("next")
            if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "Sankaku keyset meta has a malformed next cursor",
                )
            if isinstance(next_cursor, str) and len(next_cursor) > 256:
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "Sankaku keyset next cursor is unreasonably long",
                )
            continuation = None
            if next_cursor:
                continuation = Continuation(
                    self.instance_key,
                    CONTINUATION_VERSION,
                    {"query": self._query_of(response), "next": next_cursor},
                )
            return NormalizedPage(tuple(items), continuation)

        raise AdapterFailure(
            AdapterOutcome.MALFORMED_RESPONSE,
            f"unsupported Sankaku operation: {response.operation.value}",
        )

    @staticmethod
    def _query_of(response: ResponseEnvelope) -> str:
        # The listing request target is "listing:<query>:<cursor or start>";
        # drop the kind prefix, then the final cursor segment.
        target = response.request_target or ""
        body = target.removeprefix("listing:")
        return body.rsplit(":", 1)[0] if ":" in body else body

    def _post_items(self, post: object) -> list[NormalizedItem]:
        """Produce normalized items from one API post record."""
        if not isinstance(post, dict):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Sankaku post record is not an object"
            )
        post_id = post.get("id")
        if not isinstance(post_id, str) or not _POST_ID_PATTERN.fullmatch(post_id):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Sankaku post record has no opaque id"
            )

        created_at = post.get("created_at")
        created_iso: str | None = None
        if created_at is not None:
            seconds = created_at.get("s") if isinstance(created_at, dict) else None
            if isinstance(seconds, bool) or not isinstance(seconds, int):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "Sankaku post record has a malformed created_at",
                )
            try:
                created_iso = (
                    datetime.fromtimestamp(seconds, tz=UTC).isoformat().replace("+00:00", "Z")
                )
            except (OverflowError, OSError):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "Sankaku post record has a malformed created_at",
                ) from None

        status = post.get("status")
        if status is not None and not isinstance(status, str):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Sankaku post record has a malformed status"
            )
        rating = post.get("rating")
        if rating is not None and not isinstance(rating, str):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Sankaku post record has a malformed rating"
            )
        source = post.get("source")
        if source is not None and not isinstance(source, str):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Sankaku post record has a malformed source"
            )
        # The provider reports removed sources as the sentinel "removed";
        # only URL-shaped sources are retained as external references.
        source_url = source if isinstance(source, str) and source.startswith("http") else None
        total_score = post.get("total_score")
        score = (
            {"total": total_score}
            if isinstance(total_score, int) and not isinstance(total_score, bool)
            else None
        )

        items: list[NormalizedItem] = [
            NormalizedItem(
                "post",
                post_id,
                {
                    "platform": self.instance_key,
                    "canonical_url": f"https://sankaku.app/posts/{post_id}",
                    "created_at": created_iso,
                    "rating": rating,
                    "availability": "deleted" if status == "deleted" else "available",
                    "status": status,
                    "title": None,
                    "source": source_url,
                    "score": score,
                },
            )
        ]

        parent_id = post.get("parent_id")
        if isinstance(parent_id, str) and parent_id:
            items.append(
                NormalizedItem(
                    "post_relation",
                    f"{parent_id}:parent_of:{post_id}",
                    {
                        "platform": self.instance_key,
                        "source_post_id": parent_id,
                        "target_post_id": post_id,
                        "relation_type": "parent_of",
                    },
                )
            )

        items.extend(self._tag_items(post_id, post))
        occurrence = self._occurrence_item(post_id, post)
        if occurrence is not None:
            items.append(occurrence)
        if source_url is not None:
            items.append(
                NormalizedItem(
                    "external_reference",
                    source_url,
                    {
                        "platform": self.instance_key,
                        "post_id": post_id,
                        "reference_kind": "source_url",
                        "value": source_url,
                        "evidence_only": True,
                    },
                )
            )
        return items

    def _tag_items(self, post_id: str, post: Mapping[str, Any]) -> list[NormalizedItem]:
        """All evidenced tags: typed objects plus the fuller name array.

        The API embeds only a handful of typed tag objects per post while
        ``tag_names`` carries the complete set; typed categories land typed
        (kernel categories only) and every remaining evidenced name lands as
        an unknown-category observation instead of being silently dropped.
        """

        typed = post.get("tags")
        names = post.get("tag_names")
        if typed is None and names is None:
            return []
        if typed is not None and not isinstance(typed, list):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Sankaku post record has malformed tags"
            )
        if names is not None and not isinstance(names, list):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Sankaku post record has malformed tag names"
            )
        items: list[NormalizedItem] = []
        seen: set[str] = set()
        position = 0
        if typed is not None:
            for entry in typed:
                if not isinstance(entry, dict):
                    raise AdapterFailure(
                        AdapterOutcome.MALFORMED_RESPONSE, "Sankaku tag entry is not an object"
                    )
                name = entry.get("tagName")
                tag_type = entry.get("type")
                if not isinstance(name, str) or not name.strip():
                    raise AdapterFailure(
                        AdapterOutcome.MALFORMED_RESPONSE, "Sankaku tag entry has no name"
                    )
                if isinstance(tag_type, bool) or not isinstance(tag_type, int):
                    raise AdapterFailure(
                        AdapterOutcome.MALFORMED_RESPONSE, "Sankaku tag entry has no type"
                    )
                items.append(
                    NormalizedItem(
                        "post_tag",
                        f"{post_id}:{TAG_CATEGORY_BY_TYPE.get(tag_type, 'unknown')}:{name}",
                        {
                            "platform": self.instance_key,
                            "post_id": post_id,
                            "category": TAG_CATEGORY_BY_TYPE.get(tag_type, "unknown"),
                            "normalized_name": name.lower(),
                            "spelling": name,
                            "position": position,
                        },
                    )
                )
                seen.add(name)
                position += 1
        if names is not None:
            for name in names:
                if not isinstance(name, str) or not name.strip():
                    raise AdapterFailure(
                        AdapterOutcome.MALFORMED_RESPONSE, "Sankaku tag name is not text"
                    )
                if name in seen:
                    continue
                items.append(
                    NormalizedItem(
                        "post_tag",
                        f"{post_id}:unknown:{name}",
                        {
                            "platform": self.instance_key,
                            "post_id": post_id,
                            "category": "unknown",
                            "normalized_name": name.lower(),
                            "spelling": name,
                            "position": position,
                        },
                    )
                )
                position += 1
        return items

    def _occurrence_item(self, post_id: str, post: Mapping[str, Any]) -> NormalizedItem | None:
        file_url = _text_or_none(post.get("file_url"))
        sample_url = _text_or_none(post.get("sample_url"))
        preview_url = _text_or_none(post.get("preview_url"))
        if file_url is None and sample_url is None and preview_url is None:
            return None
        file_type = post.get("file_type")
        mime_type = file_type if isinstance(file_type, str) and "/" in file_type else None
        variants: list[dict[str, object]] = []
        if file_url is not None:
            variants.append({"role": "original", "url": file_url})
        if sample_url is not None:
            variants.append(
                {
                    "role": "sample",
                    "url": sample_url,
                    "width": _int_or_none(post.get("sample_width")),
                    "height": _int_or_none(post.get("sample_height")),
                }
            )
        if preview_url is not None:
            variants.append(
                {
                    "role": "preview",
                    "url": preview_url,
                    "width": _int_or_none(post.get("preview_width")),
                    "height": _int_or_none(post.get("preview_height")),
                }
            )
        return NormalizedItem(
            "media_occurrence",
            post_id,
            {
                "platform": self.instance_key,
                "post_id": post_id,
                "source_key": "primary",
                "index": 0,
                "role": "primary",
                "remote_url": file_url,
                "preview_url": preview_url,
                "mime_type": mime_type,
                "width": _int_or_none(post.get("width")),
                "height": _int_or_none(post.get("height")),
                "declared_md5": _text_or_none(post.get("md5")),
                "variants": variants,
            },
        )

    # ── Outcome mapping ─────────────────────────────────────────────────

    def _raise_for_outcome(self, response: ResponseEnvelope) -> None:
        """Map HTTP status codes to typed AdapterFailure outcomes."""
        if response.status_code == 401:
            raise AdapterFailure(
                AdapterOutcome.AUTHENTICATION_REQUIRED,
                "Sankaku authentication failed",
                status_code=401,
            )
        if response.status_code == 403:
            raise AdapterFailure(
                AdapterOutcome.AUTHORIZATION_DENIED,
                "provider access was denied",
                status_code=403,
            )
        if response.status_code == 404:
            raise AdapterFailure(
                AdapterOutcome.UNAVAILABLE, "provider record is unavailable", status_code=404
            )
        if response.status_code == 429:
            retry_at = _unix_to_iso(response.headers.get("x-ratelimit-reset", ""))
            raise AdapterFailure(
                AdapterOutcome.RATE_LIMITED,
                "provider rate limit reached",
                status_code=429,
                retry_at=retry_at,
            )
        if response.status_code >= 500:
            raise AdapterFailure(
                AdapterOutcome.TRANSIENT_PROVIDER,
                "provider is temporarily unavailable",
                status_code=response.status_code,
            )
        if not 200 <= response.status_code < 300:
            raise AdapterFailure(
                AdapterOutcome.UNAVAILABLE,
                "provider request was unsuccessful",
                status_code=response.status_code,
            )

    def _validate_envelope(self, response: ResponseEnvelope) -> None:
        """Confirm the envelope belongs to this adapter instance."""
        if response.provider != self.provider_key or response.instance != self.instance_key:
            raise ValueError("response belongs to another provider instance")
        if response.schema_version != self.schema_version:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "incompatible provider schema version",
            )


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
