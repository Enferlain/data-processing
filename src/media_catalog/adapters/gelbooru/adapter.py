"""Gelbooru DAPI JSON metadata adapter."""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from media_catalog.adapters.contracts import (
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    AdapterRequest,
    Continuation,
    LookupCapabilities,
    NormalizedItem,
    NormalizedPage,
    ResponseEnvelope,
)
from media_catalog.adapters.gelbooru.config import (
    ADAPTER_VERSION,
    CONTINUATION_VERSION,
    DAPI_SCHEMA_VERSION,
    DAPI_TRANSPORT_VERSION,
    GELBOORU,
    MAX_PAGE_SIZE,
    MAX_RESPONSE_BYTES,
    GelbooruInstance,
)
from media_catalog.adapters.gelbooru.credentials import GelbooruCredentials
from media_catalog.adapters.gelbooru.redaction import sanitize_exception


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# Listing enumeration scope admitted by this adapter.  DAPI serves posts
# newest-first (descending ids); `pid` offsets step forward through that
# fixed ordering, and the unfiltered listing carries no tag query.  These
# constants are the only values continuation scope validation admits.
_LISTING_SORT = "id-desc"
_LISTING_DIRECTION = "forward"
_LISTING_QUERY = ""


def _gelbooru_timestamp(value: str) -> str:
    """Convert Gelbooru timestamps to ISO 'YYYY-MM-DDTHH:MM:SSZ'.

    Handles both the documented 'YYYY-MM-DD HH:MM:SS' UTC format and the
    ctime-like 'Wed Jul 30 10:16:34 -0500 2025' format observed in live
    captures.
    """
    value = value.strip()
    # Try ctime-like format first (includes timezone offset).
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError):
        pass
    # Try 'YYYY-MM-DD HH:MM:SS' format (UTC assumed per fixture contract).
    normalized = value.replace(" ", "T") + "Z"
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError):
        raise ValueError(f"unrecognized Gelbooru timestamp format: {value!r}") from None


class GelbooruAdapter:
    """DAPI JSON metadata adapter for Gelbooru-compatible instances."""

    provider_key = "gelbooru"
    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        instance: GelbooruInstance = GELBOORU,
        *,
        client: httpx.Client,
        credentials: GelbooruCredentials | None = None,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self.instance = instance
        self.instance_key = instance.platform_key
        self.schema_version = DAPI_SCHEMA_VERSION
        self._client = client
        self._credentials = credentials
        self._clock = clock

    @property
    def transport_key(self) -> str:
        return DAPI_TRANSPORT_VERSION

    @property
    def minimum_interval_seconds(self) -> float:
        return self.instance.minimum_interval_seconds

    @property
    def transport_version(self) -> str:
        return DAPI_TRANSPORT_VERSION

    @property
    def lookup_capabilities(self) -> LookupCapabilities:
        """Gelbooru currently declares no bounded reverse-lookup strategies."""
        return LookupCapabilities()

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        """Render a DAPI request and return the provider response as an envelope."""
        if request.operation is AdapterOperation.FETCH_POST:
            endpoint, params, identity, request_target = self._dapi_post_request(
                request.target, request.continuation
            )
        elif request.operation is AdapterOperation.FETCH_TAG:
            endpoint, params, identity, request_target = self._dapi_tag_request(request.target)
        elif request.operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            endpoint, params, identity, request_target = self._dapi_listing_request(
                request.target, request.continuation
            )
        else:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                f"unsupported Gelbooru operation: {request.operation.value}",
            )

        headers = {"User-Agent": self.instance.user_agent, "Accept": "application/json"}
        try:
            response = self._client.get(
                endpoint,
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as error:
            secrets = self._credentials.secret_values() if self._credentials else ()
            raise AdapterFailure(
                AdapterOutcome.TRANSIENT_PROVIDER,
                f"DAPI transport error: {sanitize_exception(error, secrets)}",
            ) from error
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise AdapterFailure(
                AdapterOutcome.RESPONSE_TOO_LARGE,
                "DAPI response exceeded the transport byte limit",
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

    def normalize(self, response: ResponseEnvelope) -> NormalizedPage:
        """Turn a DAPI response envelope into a page of provider-neutral items."""
        self._validate_envelope(response)
        self._raise_for_outcome(response)
        try:
            body = json.loads(response.payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "provider returned invalid JSON",
            ) from error

        self._raise_for_error_envelope(body)

        if response.operation is AdapterOperation.FETCH_POST:
            items = self._normalize_dapi_post(body)
        elif response.operation is AdapterOperation.FETCH_TAG:
            items = self._normalize_dapi_tag(body)
        elif response.operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            items = self._normalize_dapi_listing(body, response)
            continuation = self._listing_continuation(response, body)
            return NormalizedPage(tuple(items), continuation)
        else:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                f"unsupported Gelbooru operation: {response.operation.value}",
            )
        return NormalizedPage(tuple(items))

    # ── Request rendering ──────────────────────────────────────────────

    def _dapi_post_request(
        self, target: str, continuation: Continuation | None
    ) -> tuple[str, dict[str, str], str, str]:
        """Render a DAPI single-post fetch request."""
        post_id = _stable_id(target, "post ID")
        if self._credentials is None:
            raise ValueError("DAPI requests require credentials")
        params = self._credentials.authenticated_query(
            {
                "page": "dapi",
                "s": "post",
                "q": "index",
                "json": "1",
                "id": post_id,
            }
        )
        identity = f"{self.instance_key}:dapi_json:post:{post_id}"
        request_target = f"post:{post_id}"
        return f"{self.instance.base_url}/index.php", params, identity, request_target

    def _dapi_tag_request(self, target: str) -> tuple[str, dict[str, str], str, str]:
        """Render a DAPI tag metadata request."""
        if self._credentials is None:
            raise ValueError("DAPI requests require credentials")
        params = self._credentials.authenticated_query(
            {
                "page": "dapi",
                "s": "tag",
                "q": "index",
                "json": "1",
                "name": target,
            }
        )
        identity = f"{self.instance_key}:dapi_json:tag:{target}"
        request_target = f"tag:{target}"
        return f"{self.instance.base_url}/index.php", params, identity, request_target

    def _dapi_listing_request(
        self, target: str, continuation: Continuation | None
    ) -> tuple[str, dict[str, str], str, str]:
        """Render a DAPI generic post listing request with pid/limit pagination.

        The listing target and the admitted scope (unfiltered query, id-desc
        sort, forward direction) are embedded in the request identity and
        target so every retained observation and continuation checkpoint
        records exactly which enumeration it belongs to.
        """
        listing_target = _listing_target_text(target)
        pid = 0
        limit = MAX_PAGE_SIZE
        if continuation is not None:
            pid, limit = self._validate_listing_continuation(continuation, target=listing_target)
        if self._credentials is None:
            raise ValueError("DAPI requests require credentials")
        params = self._credentials.authenticated_query(
            {
                "page": "dapi",
                "s": "post",
                "q": "index",
                "json": "1",
                "pid": str(pid),
                "limit": str(limit),
            }
        )
        identity = (
            f"{self.instance_key}:dapi_json:listing:{listing_target}:"
            f"{_LISTING_SORT}:{_LISTING_DIRECTION}:{pid}:{limit}"
        )
        request_target = (
            f"listing:{listing_target}:{_LISTING_SORT}:{_LISTING_DIRECTION}:{pid}:{limit}"
        )
        return f"{self.instance.base_url}/index.php", params, identity, request_target

    # ── Response outcome classification ────────────────────────────────

    def _raise_for_outcome(self, response: ResponseEnvelope) -> None:
        """Map HTTP status codes to typed AdapterFailure outcomes."""
        if response.status_code == 401:
            raise AdapterFailure(
                AdapterOutcome.AUTHENTICATION_REQUIRED,
                "provider authentication is required",
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
                AdapterOutcome.UNAVAILABLE,
                "provider record is unavailable",
                status_code=404,
            )
        if response.status_code == 429:
            raise AdapterFailure(
                AdapterOutcome.RATE_LIMITED,
                "provider rate limit reached",
                status_code=429,
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

    def _raise_for_error_envelope(self, body: object) -> None:
        """Detect Gelbooru error envelopes in a 200 response body."""
        if not isinstance(body, dict):
            return
        # Top-level "error" key (string or {"#text": …})
        if "error" in body:
            error_value = body["error"]
            if isinstance(error_value, str):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    f"provider returned error envelope: {error_value[:200]}",
                )
            if isinstance(error_value, dict) and isinstance(error_value.get("#text"), str):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    f"provider returned error envelope: {error_value['#text'][:200]}",
                )
        # response.@attributes.success=false with reason
        response_attrs = body.get("response", {}).get("@attributes", {})
        if response_attrs.get("success") == "false" and response_attrs.get("reason"):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                f"provider returned error: {response_attrs['reason'][:200]}",
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

    def _validate_continuation(self, continuation: Continuation) -> None:
        """Confirm a continuation is compatible with this adapter."""
        if continuation.adapter != self.provider_key:
            raise ValueError("continuation belongs to another adapter")
        if continuation.version != CONTINUATION_VERSION:
            raise ValueError("incompatible Gelbooru continuation version")

    def _validate_listing_continuation(
        self, continuation: Continuation, *, target: str
    ) -> tuple[int, int]:
        """Validate every continuation scope dimension before network access.

        Task 3.4: a continuation is admitted only when its operation, target,
        query, sort, transport, direction, boundary, and version material all
        match the enumeration this adapter is about to render.  Any mismatch
        raises ``ValueError`` before an HTTP request exists, so an incompatible
        resume fails closed instead of silently continuing a different query.
        """
        self._validate_continuation(continuation)
        value = continuation.value
        if value.get("operation") != AdapterOperation.LIST_ACCOUNT_POSTS.value:
            raise ValueError("Gelbooru listing continuation operation is incompatible")
        if value.get("target") != target:
            raise ValueError("Gelbooru listing continuation target is incompatible")
        if value.get("query") != _LISTING_QUERY:
            raise ValueError("Gelbooru listing continuation query is not admitted")
        if value.get("sort") != _LISTING_SORT:
            raise ValueError("Gelbooru listing continuation sort is incompatible")
        if value.get("transport") != self.transport_key:
            raise ValueError("Gelbooru listing continuation transport is incompatible")
        if value.get("direction") != _LISTING_DIRECTION:
            raise ValueError("Gelbooru listing continuation direction is incompatible")
        try:
            pid = int(str(value.get("pid", "")))
            last_pid = int(str(value.get("last_pid", "")))
            limit = int(str(value.get("limit", "")))
        except (TypeError, ValueError):
            raise ValueError("malformed Gelbooru continuation boundary") from None
        if pid < 0 or last_pid < 0 or limit < 1:
            raise ValueError("Gelbooru continuation pid/limit out of range")
        if pid != last_pid + 1:
            raise ValueError("Gelbooru continuation boundary is inconsistent")
        last_id = value.get("last_id")
        if not isinstance(last_id, int) or isinstance(last_id, bool) or last_id < 1:
            raise ValueError("Gelbooru continuation is missing its last-seen id")
        if value.get("continuation_version") != CONTINUATION_VERSION:
            raise ValueError("Gelbooru listing continuation version is incompatible")
        if value.get("adapter_version") != self.adapter_version:
            raise ValueError("Gelbooru listing continuation adapter version is incompatible")
        if value.get("schema_version") != self.schema_version:
            raise ValueError("Gelbooru listing continuation schema version is incompatible")
        return pid, min(limit, MAX_PAGE_SIZE)

    # ── Listing continuation helpers ───────────────────────────────────

    @staticmethod
    def _parse_listing_target(
        request_target: str | None,
    ) -> tuple[str, int, int] | None:
        """Extract (target, pid, limit) from a scoped listing request_target.

        Expected format: ``listing:{target}:{sort}:{direction}:{pid}:{limit}``.
        Legacy three-field targets are not understood and yield ``None`` so
        re-normalizing an old observation treats the page as final instead of
        minting an unscoped continuation.
        """
        if not request_target or not request_target.startswith("listing:"):
            return None
        parts = request_target.split(":")
        if len(parts) != 6:
            return None
        if parts[2] != _LISTING_SORT or parts[3] != _LISTING_DIRECTION:
            return None
        try:
            pid = int(parts[4])
            limit = int(parts[5])
        except (ValueError, IndexError):
            return None
        if pid < 0 or not (1 <= limit <= MAX_PAGE_SIZE):
            return None
        return parts[1], pid, limit

    def _listing_continuation(
        self, response: ResponseEnvelope, body: object
    ) -> Continuation | None:
        """Produce a fully scoped continuation for a listing page if it was full."""
        listing = self._parse_listing_target(response.request_target)
        if listing is None:
            return None
        target, pid, limit = listing
        posts = self._parse_dapi_post_body(body)
        if not posts or len(posts) < limit:
            return None
        last_post = posts[-1]
        last_id = last_post.get("id")
        if not isinstance(last_id, int) or isinstance(last_id, bool) or last_id < 1:
            return None
        # Full page received; the remote executor decides whether to continue
        # based on its own budget rules.  We signal that another page exists,
        # carrying every scope dimension so resume can be validated up front.
        next_pid = pid + 1
        return Continuation(
            self.provider_key,
            CONTINUATION_VERSION,
            {
                "operation": AdapterOperation.LIST_ACCOUNT_POSTS.value,
                "target": target,
                "query": _LISTING_QUERY,
                "sort": _LISTING_SORT,
                "transport": self.transport_key,
                "direction": _LISTING_DIRECTION,
                "pid": str(next_pid),
                "last_pid": str(pid),
                "limit": str(limit),
                "last_id": last_id,
                "continuation_version": CONTINUATION_VERSION,
                "adapter_version": self.adapter_version,
                "schema_version": self.schema_version,
            },
        )

    # ── DAPI response shape parsing ────────────────────────────────────

    @staticmethod
    def _parse_dapi_post_body(body: object) -> list[dict[str, Any]]:
        """Accept list, dict, or bare-array DAPI post response shapes."""
        if isinstance(body, list):
            # Legacy bare-array format: [{...}, {...}]
            return [entry for entry in body if isinstance(entry, dict)]
        if isinstance(body, dict):
            if "post" in body:
                post_value = body["post"]
                if isinstance(post_value, list):
                    # Non-dict entries are provider garbage; skip them exactly
                    # like the bare-array shape so downstream consumers can
                    # never crash on posts[-1].get(...).
                    return [entry for entry in post_value if isinstance(entry, dict)]
                if isinstance(post_value, dict):
                    return [post_value]
                return []
            # Single dict without wrapper key (gallery-dl edge case)
            if all(isinstance(k, str) for k in body):
                return [dict(body)]
        raise AdapterFailure(
            AdapterOutcome.MALFORMED_RESPONSE,
            "DAPI post response has an unsupported shape",
        )

    # ── DAPI post normalization ────────────────────────────────────────

    def _normalize_dapi_post(self, body: object) -> list[NormalizedItem]:
        """Normalize a DAPI post response into provider-neutral items."""
        # Empty result: count == 0 with no post key
        if isinstance(body, dict) and body.get("@attributes", {}).get("count", -1) == 0:
            return []

        posts = self._parse_dapi_post_body(body)
        if not posts:
            return []

        items: list[NormalizedItem] = []
        for post in posts:
            if not isinstance(post, dict) or not isinstance(post.get("id"), int):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "DAPI post record has no stable numeric ID",
                )
            items.extend(self._post_items(post))
        return items

    def _post_items(self, post: Mapping[str, Any]) -> list[NormalizedItem]:
        """Produce normalized items from one DAPI post record."""
        post_id = str(post["id"])
        rating = post.get("rating", "")
        availability = "available"
        status = post.get("status")
        if status == "deleted":
            availability = "deleted"

        created_at = post.get("created_at")
        if not isinstance(created_at, str) or not created_at:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "DAPI post record has no created_at timestamp",
            )
        try:
            created_iso = _gelbooru_timestamp(created_at)
        except ValueError as error:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "DAPI post record has an unparseable created_at timestamp",
            ) from error

        score = post.get("score")
        items: list[NormalizedItem] = [
            NormalizedItem(
                "post",
                post_id,
                {
                    "platform": self.instance_key,
                    "canonical_url": (
                        f"{self.instance.base_url}/index.php?page=post&s=view&id={post_id}"
                    ),
                    "created_at": created_iso,
                    "rating": rating if rating else None,
                    "availability": availability,
                    "status": status,
                    "source": post.get("source") or None,
                    # The page writer persists score facts only in mapping form.
                    "score": (
                        {"total": score}
                        if isinstance(score, int) and not isinstance(score, bool)
                        else None
                    ),
                },
            ),
        ]

        # Uploader account and participant
        creator_id = post.get("creator_id")
        owner = post.get("owner")
        if isinstance(creator_id, int) and creator_id > 0 and isinstance(owner, str) and owner:
            uploader_id = str(creator_id)
            items.extend(
                [
                    NormalizedItem(
                        "account",
                        uploader_id,
                        {
                            "platform": self.instance_key,
                            "availability": "available",
                            "handle": owner,
                        },
                    ),
                    NormalizedItem(
                        "post_participant",
                        f"{post_id}:uploader:{uploader_id}",
                        {
                            "platform": self.instance_key,
                            "post_id": post_id,
                            "account_id": uploader_id,
                            "role": "uploader",
                        },
                    ),
                ]
            )

        # Tags (flat space-separated string; no category info → "unknown")
        tags_str = post.get("tags", "")
        if isinstance(tags_str, str) and tags_str:
            for position, spelling in enumerate(tags_str.split()):
                items.append(
                    NormalizedItem(
                        "post_tag",
                        f"{post_id}:unknown:{spelling}",
                        {
                            "platform": self.instance_key,
                            "post_id": post_id,
                            "category": "unknown",
                            "normalized_name": spelling.casefold(),
                            "spelling": spelling,
                            "position": position,
                        },
                    )
                )

        # Media occurrence (original, sample, preview)
        file_url = post.get("file_url")
        preview_url = post.get("preview_url")
        sample_url = post.get("sample_url") if post.get("sample") == 1 else None
        if isinstance(file_url, str) and file_url:
            variants: list[dict[str, str]] = []
            variants.append({"role": "original", "url": file_url})
            if isinstance(sample_url, str) and sample_url:
                variants.append({"role": "sample", "url": sample_url})
            if isinstance(preview_url, str) and preview_url:
                variants.append({"role": "preview", "url": preview_url})

            mime_type = None
            image_name = post.get("image")
            if isinstance(image_name, str) and "." in image_name:
                ext = image_name.rsplit(".", 1)[-1].lower()
                mime_type = mimetypes.guess_type(f"file.{ext}")[0]

            items.append(
                NormalizedItem(
                    "media_occurrence",
                    f"{post_id}:primary",
                    {
                        "platform": self.instance_key,
                        "post_id": post_id,
                        "source_key": "primary",
                        "index": 0,
                        "role": "primary",
                        "remote_url": file_url,
                        "preview_url": preview_url,
                        "mime_type": mime_type,
                        "width": post.get("width"),
                        "height": post.get("height"),
                        "declared_md5": post.get("md5"),
                        "variants": variants,
                        "availability": availability,
                    },
                )
            )

        # External reference (source URL)
        source = post.get("source")
        if isinstance(source, str) and source:
            items.append(
                NormalizedItem(
                    "external_reference",
                    f"{post_id}:source",
                    {
                        "platform": self.instance_key,
                        "post_id": post_id,
                        "reference_kind": "source_url",
                        "value": source,
                        "evidence_only": True,
                    },
                )
            )

        return items

    # ── DAPI tag normalization ─────────────────────────────────────────

    def _normalize_dapi_tag(self, body: object) -> list[NormalizedItem]:
        """Normalize a DAPI tag metadata response into provider-neutral items."""
        if isinstance(body, dict) and body.get("@attributes", {}).get("count", -1) == 0:
            return []

        tags: list[dict[str, Any]] = []
        if isinstance(body, dict) and "tag" in body:
            tag_value = body["tag"]
            if isinstance(tag_value, list):
                tags = [t for t in tag_value if isinstance(t, dict)]
            elif isinstance(tag_value, dict):
                tags = [tag_value]

        items: list[NormalizedItem] = []
        for tag in tags:
            if not isinstance(tag, dict) or not isinstance(tag.get("id"), int):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "DAPI tag record has no stable numeric ID",
                )
            tag_id = str(tag["id"])
            items.append(
                NormalizedItem(
                    "tag",
                    tag_id,
                    {
                        "platform": self.instance_key,
                        "name": tag.get("name"),
                        "native_category_code": tag.get("type"),
                        "post_count": tag.get("count"),
                        "ambiguous": bool(tag.get("ambiguous")),
                    },
                )
            )
        return items

    # ── DAPI listing normalization ─────────────────────────────────────

    def _normalize_dapi_listing(
        self, body: object, response: ResponseEnvelope
    ) -> list[NormalizedItem]:
        """Normalize a DAPI listing page into provider-neutral items."""
        if isinstance(body, dict) and body.get("@attributes", {}).get("count", -1) == 0:
            return []

        posts = self._parse_dapi_post_body(body)
        items: list[NormalizedItem] = []
        for post in posts:
            if not isinstance(post, dict) or not isinstance(post.get("id"), int):
                continue
            items.extend(self._post_items(post))
        return items


def _stable_id(value: str, name: str) -> str:
    """Validate and normalize a positive numeric stable ID."""
    if not isinstance(value, str) or not value.isdecimal() or int(value) < 1:
        raise ValueError(f"{name} must be a positive numeric stable ID")
    return str(int(value))


def _listing_target_text(value: str) -> str:
    """Validate the listing target text that scopes a pid enumeration.

    The target becomes a colon-separated field of the request identity and
    target material, so it must be bounded, non-empty, and colon-free.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Gelbooru listing target must be non-empty text")
    value = value.strip()
    if len(value) > 100 or ":" in value or any(ord(char) < 32 for char in value):
        raise ValueError(
            "Gelbooru listing target must be bounded text without colons or control characters"
        )
    return value
