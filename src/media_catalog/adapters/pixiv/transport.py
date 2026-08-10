"""Pixiv metadata transport and normalization.

The Pixiv app endpoints are an authenticated, private API rather than a stable public API.  This
module therefore keeps the HTTP boundary deliberately small: a request is converted into a
provider-neutral :class:`ResponseEnvelope`, and normalization is performed only from retained
bytes.  In particular, URLs returned by Pixiv are values in metadata; this adapter never follows
them.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

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

PIXIV_PROVIDER = "pixiv"
PIXIV_INSTANCE = "pixiv"
PIXIV_ADAPTER_VERSION = "pixiv-adapter-v1"
PIXIV_SCHEMA_VERSION = "pixiv-app-v1"
DEFAULT_BASE_URL = "https://app-api.pixiv.net"
DEFAULT_OAUTH_URL = "https://oauth.secure.pixiv.net/auth/token"
CONTINUATION_VERSION = "pixiv-list-v1"

_NUMERIC_ID = re.compile(r"^[1-9][0-9]*$")
_PUBLIC_HEADER_NAMES = frozenset(
    {
        "content-type",
        "etag",
        "last-modified",
        "retry-after",
        "x-rate-limit-remaining",
        "x-rate-limit-reset",
    }
)


Clock = Callable[[], datetime | str]


def _now(clock: Clock | None) -> str:
    value = clock() if clock is not None else datetime.now(UTC)
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Pixiv clock must return a timezone-aware timestamp")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _numeric_id(value: object, name: str = "Pixiv identifier") -> str:
    """Return the canonical decimal representation of a Pixiv native id."""

    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive numeric identifier")
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str) or not _NUMERIC_ID.fullmatch(value):
        raise ValueError(f"{name} must be a positive numeric identifier")
    return str(int(value))


def _response_id(value: object, name: str = "Pixiv identifier") -> str:
    try:
        return _numeric_id(value, name)
    except ValueError as error:
        raise AdapterFailure(
            AdapterOutcome.MALFORMED_RESPONSE,
            f"Pixiv response contains an invalid {name.lower()}",
        ) from error


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return result if result is not None and result >= 0 else None


def _url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _json_body(payload: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdapterFailure(
            AdapterOutcome.MALFORMED_RESPONSE, "Pixiv returned malformed JSON"
        ) from error
    if not isinstance(value, Mapping):
        raise AdapterFailure(
            AdapterOutcome.MALFORMED_RESPONSE, "Pixiv response must be a JSON object"
        )
    return value


def _retry_at(headers: Mapping[str, str], observed_at: str) -> str | None:
    retry_after = headers.get("retry-after")
    if retry_after:
        try:
            seconds = float(retry_after)
            if seconds >= 0:
                base = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
                return (
                    (base + timedelta(seconds=seconds))
                    .astimezone(UTC)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
        except (TypeError, ValueError):
            try:
                parsed = parsedate_to_datetime(retry_after)
            except (TypeError, ValueError, OverflowError):
                parsed = None
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    reset = headers.get("x-rate-limit-reset")
    if reset:
        try:
            return datetime.fromtimestamp(float(reset), UTC).isoformat().replace("+00:00", "Z")
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    return None


def _status_failure(response: ResponseEnvelope) -> AdapterFailure | None:
    status = response.status_code
    if status in {401, 407}:
        return AdapterFailure(
            AdapterOutcome.AUTHENTICATION_REQUIRED,
            "Pixiv authentication is required",
            status_code=status,
        )
    if status == 403:
        return AdapterFailure(
            AdapterOutcome.AUTHORIZATION_DENIED,
            "Pixiv denied access to this metadata",
            status_code=status,
        )
    if status == 429:
        return AdapterFailure(
            AdapterOutcome.RATE_LIMITED,
            "Pixiv rate limit reached",
            status_code=status,
            retry_at=_retry_at(response.headers, response.observed_at),
        )
    if 500 <= status <= 599:
        return AdapterFailure(
            AdapterOutcome.TRANSIENT_PROVIDER,
            "Pixiv provider request failed temporarily",
            status_code=status,
            retry_at=_retry_at(response.headers, response.observed_at),
        )
    if status in {400, 422}:
        return AdapterFailure(
            AdapterOutcome.MALFORMED_RESPONSE,
            "Pixiv rejected the metadata request",
            status_code=status,
        )
    return None


class PixivAuthenticator:
    """Isolated refresh-token exchange.

    The token response is intentionally not represented by ``ResponseEnvelope`` and the token is
    only held in a private field.  This prevents a token exchange from becoming raw provider data
    or appearing in request identities, diagnostics, or object representations.
    """

    def __init__(
        self,
        client: httpx.Client,
        refresh_token: str,
        *,
        oauth_url: str = DEFAULT_OAUTH_URL,
        client_id: str,
        client_secret: str,
    ) -> None:
        if not isinstance(refresh_token, str) or not refresh_token:
            raise ValueError("Pixiv refresh token must be non-empty")
        self._client = client
        self._refresh_token = refresh_token
        self._oauth_url = oauth_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: str | None = None

    def __repr__(self) -> str:
        return "PixivAuthenticator(<redacted>)"

    def access_token(self) -> str:
        if self._access_token:
            return self._access_token
        try:
            response = self._client.post(
                self._oauth_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
            )
        except httpx.RequestError:
            raise AdapterFailure(
                AdapterOutcome.TRANSIENT_PROVIDER,
                "Pixiv authentication transport failed",
            ) from None
        except Exception:
            raise AdapterFailure(
                AdapterOutcome.TRANSIENT_PROVIDER,
                "Pixiv authentication transport failed",
            ) from None
        if response.status_code >= 400:
            raise AdapterFailure(
                AdapterOutcome.AUTHENTICATION_REQUIRED,
                "Pixiv refresh-token authentication was rejected",
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError) as error:
            raise AdapterFailure(
                AdapterOutcome.AUTHENTICATION_REQUIRED,
                "Pixiv authentication response was invalid",
            ) from error
        token = body.get("access_token") if isinstance(body, Mapping) else None
        if not isinstance(token, str) or not token:
            nested = body.get("response") if isinstance(body, Mapping) else None
            token = nested.get("access_token") if isinstance(nested, Mapping) else None
        if not isinstance(token, str) or not token:
            raise AdapterFailure(
                AdapterOutcome.AUTHENTICATION_REQUIRED,
                "Pixiv authentication response did not contain an access token",
            )
        self._access_token = token
        return token


class PixivAuthTransport(PixivAuthenticator):
    """Compatibility name for callers that refer to the token exchange as a transport."""


class PixivAdapter:
    """Metadata-only Pixiv adapter implementing the provider-neutral adapter protocol."""

    provider_key = PIXIV_PROVIDER
    instance_key = PIXIV_INSTANCE
    adapter_version = PIXIV_ADAPTER_VERSION
    schema_version = PIXIV_SCHEMA_VERSION

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        http_client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        base_url: str = DEFAULT_BASE_URL,
        oauth_url: str = DEFAULT_OAUTH_URL,
        refresh_token: str | None = None,
        refresh_token_env: str | None = "PIXIV_REFRESH_TOKEN",
        client_id: str | None = None,
        client_id_env: str | None = "PIXIV_CLIENT_ID",
        client_secret: str | None = None,
        client_secret_env: str | None = "PIXIV_CLIENT_SECRET",
        access_token: str | None = None,
        authenticator: PixivAuthenticator | None = None,
        require_auth: bool = False,
        clock: Clock | None = None,
    ) -> None:
        if client is not None and http_client is not None:
            raise ValueError("provide either client or http_client, not both")
        client = client or http_client
        if client is not None and transport is not None:
            raise ValueError("provide either an httpx client or transport, not both")
        self.base_url = base_url.rstrip("/")
        self._clock = clock
        self._require_auth = require_auth
        self._owns_client = client is None
        self.client = client or httpx.Client(transport=transport, base_url=self.base_url)
        self._access_token = access_token
        self._auth_configuration_incomplete = False
        if authenticator is not None and refresh_token is not None:
            raise ValueError("provide either authenticator or refresh_token, not both")
        if authenticator is None:
            resolved_refresh_token = refresh_token
            if resolved_refresh_token is None and refresh_token_env:
                resolved_refresh_token = os.getenv(refresh_token_env)
            if resolved_refresh_token:
                resolved_client_id = client_id
                resolved_client_secret = client_secret
                if resolved_client_id is None and client_id_env:
                    resolved_client_id = os.getenv(client_id_env)
                if resolved_client_secret is None and client_secret_env:
                    resolved_client_secret = os.getenv(client_secret_env)
                if not resolved_client_id or not resolved_client_secret:
                    self._auth_configuration_incomplete = True
                else:
                    authenticator = PixivAuthenticator(
                        self.client,
                        resolved_refresh_token,
                        oauth_url=oauth_url,
                        client_id=resolved_client_id,
                        client_secret=resolved_client_secret,
                    )
        self._authenticator = authenticator

    def __repr__(self) -> str:
        auth = "configured" if self._authenticator is not None or self._access_token else "none"
        return f"PixivAdapter(base_url={self.base_url!r}, auth={auth})"

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> PixivAdapter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_account(self, stable_id: str | int) -> NormalizedPage:
        return self.normalize(
            self.fetch(AdapterRequest(AdapterOperation.FETCH_ACCOUNT, _numeric_id(stable_id)))
        )

    fetch_user = fetch_account

    def fetch_post(self, stable_id: str | int) -> NormalizedPage:
        return self.normalize(
            self.fetch(AdapterRequest(AdapterOperation.FETCH_POST, _numeric_id(stable_id)))
        )

    fetch_artwork = fetch_post

    def fetch_ugoira(self, stable_id: str | int) -> NormalizedPage:
        native_id = _numeric_id(stable_id)
        response = self._request(
            AdapterOperation.FETCH_POST,
            native_id,
            "/v1/ugoira/metadata",
            {"illust_id": native_id},
            identity=f"pixiv:fetch_post:{native_id}:ugoira",
        )
        return self._normalize_ugoira(response, native_id)

    def list_account_posts(
        self,
        stable_id: str | int,
        continuation: Continuation | None = None,
    ) -> NormalizedPage:
        native_id = _numeric_id(stable_id)
        request = AdapterRequest(AdapterOperation.LIST_ACCOUNT_POSTS, native_id, continuation)
        return self.normalize(self.fetch(request))

    list_user_artworks = list_account_posts

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        target = _numeric_id(request.target)
        if request.operation is AdapterOperation.FETCH_ACCOUNT:
            return self._request(
                request.operation,
                target,
                "/v1/user/detail",
                {"user_id": target},
                identity=f"pixiv:fetch_account:{target}",
            )
        if request.operation is AdapterOperation.FETCH_POST:
            return self._request(
                request.operation,
                target,
                "/v1/illust/detail",
                {"illust_id": target},
                identity=f"pixiv:fetch_post:{target}",
            )
        if request.operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            continuation = request.continuation
            if continuation is not None and (
                continuation.adapter != self.provider_key
                or continuation.version != CONTINUATION_VERSION
            ):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "Pixiv continuation is incompatible with this adapter",
                )
            offset = None
            next_url: str | None = None
            if continuation is not None:
                serialized = json.dumps(dict(continuation.value), sort_keys=True).lower()
                if any(
                    marker in serialized
                    for marker in (
                        "access_token",
                        "refresh_token",
                        "api_key",
                        "authorization",
                        "cookie",
                    )
                ):
                    raise AdapterFailure(
                        AdapterOutcome.MALFORMED_RESPONSE,
                        "Pixiv continuation contains a secret-bearing value",
                    )
                raw_offset = continuation.value.get("offset")
                if raw_offset is not None:
                    try:
                        offset = int(raw_offset)
                    except (TypeError, ValueError) as error:
                        raise AdapterFailure(
                            AdapterOutcome.MALFORMED_RESPONSE,
                            "Pixiv continuation offset is invalid",
                        ) from error
                    if offset < 0:
                        raise AdapterFailure(
                            AdapterOutcome.MALFORMED_RESPONSE,
                            "Pixiv continuation offset is invalid",
                        )
                raw_next_url = continuation.value.get("next_url")
                if raw_next_url is not None:
                    if not isinstance(raw_next_url, str) or not raw_next_url.strip():
                        raise AdapterFailure(
                            AdapterOutcome.MALFORMED_RESPONSE,
                            "Pixiv continuation URL is invalid",
                        )
                    parsed = urlsplit(raw_next_url)
                    if parsed.hostname != urlsplit(self.base_url).hostname:
                        raise AdapterFailure(
                            AdapterOutcome.MALFORMED_RESPONSE,
                            "Pixiv continuation URL is outside the metadata endpoint",
                        )
                    next_url = raw_next_url
            identity_suffix = "first" if offset is None else f"offset={offset}"
            params: dict[str, str] = {"user_id": target}
            if offset is not None:
                params["offset"] = str(offset)
            return self._request(
                request.operation,
                target,
                "/v1/user/illusts",
                {} if next_url is not None else params,
                identity=f"pixiv:list_account_posts:{target}:{identity_suffix}",
                request_url=next_url,
            )
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "Pixiv operation is unsupported")

    def normalize(self, response: ResponseEnvelope) -> NormalizedPage:
        self._validate_envelope(response)
        failure = _status_failure(response)
        if failure is not None:
            raise failure
        body = _json_body(response.payload)
        if response.operation is AdapterOperation.FETCH_ACCOUNT:
            return self._normalize_account(body, response)
        if response.operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            return self._normalize_listing(body, response)
        if response.operation is AdapterOperation.FETCH_POST:
            identity = response.request_identity
            if identity.endswith(":ugoira") or "ugoira_metadata" in body:
                target = self._id_from_identity(identity)
                return self._normalize_ugoira(response, _numeric_id(target))
            return self._normalize_post(body, response)
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "Pixiv operation is unsupported")

    def _validate_envelope(self, response: ResponseEnvelope) -> None:
        if response.provider != self.provider_key or response.instance != self.instance_key:
            raise ValueError("response belongs to another Pixiv provider instance")
        if response.schema_version != self.schema_version:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "incompatible Pixiv response schema version",
            )

    def _auth_headers(self) -> Mapping[str, str]:
        if self._auth_configuration_incomplete:
            raise AdapterFailure(
                AdapterOutcome.AUTHENTICATION_REQUIRED,
                "Pixiv credential references are incomplete",
            )
        token = self._access_token
        if token is None and self._authenticator is not None:
            token = self._authenticator.access_token()
        if token is None:
            if self._require_auth:
                raise AdapterFailure(
                    AdapterOutcome.AUTHENTICATION_REQUIRED,
                    "Pixiv credential reference is not configured",
                )
            return MappingProxyType({})
        return MappingProxyType({"Authorization": f"Bearer {token}"})

    def _request(
        self,
        operation: AdapterOperation,
        target: str,
        path: str,
        params: Mapping[str, str],
        *,
        identity: str,
        request_url: str | None = None,
    ) -> ResponseEnvelope:
        try:
            response = self.client.get(
                request_url or f"{self.base_url}{path}",
                params=dict(params),
                headers=dict(self._auth_headers()),
            )
        except AdapterFailure:
            raise
        except httpx.RequestError:
            raise AdapterFailure(
                AdapterOutcome.TRANSIENT_PROVIDER,
                "Pixiv metadata transport failed",
            ) from None
        except Exception:
            raise AdapterFailure(
                AdapterOutcome.TRANSIENT_PROVIDER,
                "Pixiv metadata transport failed",
            ) from None
        headers = {
            name.lower(): value
            for name, value in response.headers.items()
            if name.lower() in _PUBLIC_HEADER_NAMES
        }
        return ResponseEnvelope(
            provider=self.provider_key,
            instance=self.instance_key,
            operation=operation,
            request_identity=identity,
            status_code=response.status_code,
            headers=headers,
            payload=response.content,
            observed_at=_now(self._clock),
            adapter_version=self.adapter_version,
            schema_version=self.schema_version,
        )

    def _normalize_account(
        self, body: Mapping[str, Any], response: ResponseEnvelope
    ) -> NormalizedPage:
        user = _mapping(body.get("user"))
        if not user:
            if response.status_code in {404, 410}:
                target = self._id_from_identity(response.request_identity)
                outcome = "deleted" if response.status_code == 410 else "unavailable"
                return NormalizedPage(
                    (
                        NormalizedItem(
                            "account",
                            target,
                            {
                                "outcome": outcome,
                                "availability": outcome,
                                "platform": self.provider_key,
                                "adapter_version": self.adapter_version,
                                "schema_version": self.schema_version,
                                "native_id": target,
                                "canonical_url": f"https://www.pixiv.net/users/{target}",
                                "observation_time": response.observed_at,
                                "external_links": [],
                            },
                        ),
                    )
                )
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Pixiv profile has no user object"
            )
        native_id = _response_id(user.get("id"), "Pixiv user id")
        expected_id = self._id_from_identity(response.request_identity)
        if native_id != expected_id:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "Pixiv profile identifier does not match its request",
            )
        profile = _mapping(body.get("profile"))
        publicity = _mapping(body.get("profile_publicity"))
        links: list[dict[str, str]] = []
        link_fields = (
            ("webpage", "account.website"),
            ("twitter_url", "account.social"),
            ("facebook_url", "account.social"),
            ("instagram_url", "account.social"),
        )
        for field, context in link_fields:
            value = _url(profile.get(field) or user.get(field))
            if value is not None and not any(item["url"] == value for item in links):
                links.append({"url": value, "source_context": context})
        social = _mapping(profile.get("social"))
        for name, value in social.items():
            link = _url(value)
            if link is not None and not any(item["url"] == link for item in links):
                links.append({"url": link, "source_context": "account.social", "kind": str(name)})
        avatar = _url(_mapping(user.get("profile_image_urls")).get("medium"))
        background = _url(
            profile.get("background_image_url") or user.get("profile_background_image_url")
        )
        followers = _positive_int(profile.get("total_follow_users"))
        following = _positive_int(profile.get("total_following"))
        availability = "available"
        if user.get("is_valid") is False or profile.get("is_valid") is False:
            availability = "unavailable"
        data: dict[str, Any] = {
            "outcome": "success" if availability == "available" else "unavailable",
            "availability": availability,
            "platform": self.provider_key,
            "adapter_version": self.adapter_version,
            "schema_version": self.schema_version,
            "native_id": native_id,
            "canonical_url": f"https://www.pixiv.net/users/{native_id}",
            "handle": _text(user.get("account")),
            "display_name": _text(user.get("name")),
            "bio": _text(profile.get("comment") or user.get("comment")),
            "avatar_url": avatar,
            "banner_url": background,
            "followers": followers,
            "following": following,
            "artwork_count": _positive_int(profile.get("total_illusts")),
            "observation_time": response.observed_at,
            "account_state": _text(user.get("account_status") or profile.get("account_status")),
            "external_links": links,
            "links": links,
            # A compact provider-shaped snapshot is useful to persistence callers that need to
            # distinguish absent fields from an explicit null.
            "profile_publicity": dict(publicity),
        }
        return NormalizedPage((NormalizedItem("account", native_id, data),))

    def _normalize_listing(
        self, body: Mapping[str, Any], response: ResponseEnvelope
    ) -> NormalizedPage:
        raw_items = body.get("illusts")
        if not isinstance(raw_items, list):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Pixiv listing has no illusts array"
            )
        items: list[NormalizedItem] = []
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "Pixiv listing item is invalid"
                )
            native_id = _response_id(raw.get("id"), "Pixiv artwork id")
            summary = {
                "outcome": "success",
                "availability": "available",
                "platform": self.provider_key,
                "adapter_version": self.adapter_version,
                "schema_version": self.schema_version,
                "native_id": native_id,
                "canonical_url": f"https://www.pixiv.net/artworks/{native_id}",
                "title": _text(raw.get("title")),
                "type": _text(raw.get("type")),
                "observation_time": response.observed_at,
                "metadata_only": True,
            }
            items.append(NormalizedItem("post", native_id, summary))
        continuation = self._next_continuation(body.get("next_url"))
        return NormalizedPage(tuple(items), continuation)

    def _normalize_post(
        self, body: Mapping[str, Any], response: ResponseEnvelope
    ) -> NormalizedPage:
        illust = _mapping(body.get("illust"))
        if not illust:
            if response.status_code in {404, 410}:
                return self._unavailable_post(response)
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Pixiv artwork has no illust object"
            )
        native_id = _response_id(illust.get("id"), "Pixiv artwork id")
        expected_id = self._id_from_identity(response.request_identity)
        if native_id != expected_id:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "Pixiv artwork identifier does not match its request",
            )
        author_raw = _mapping(illust.get("user"))
        author_id = _response_id(author_raw.get("id"), "Pixiv user id") if author_raw else None
        tags: list[dict[str, Any]] = []
        raw_tags = illust.get("tags")
        if raw_tags is not None and not isinstance(raw_tags, list):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Pixiv artwork tags are invalid"
            )
        for index, raw_tag in enumerate(raw_tags or ()):
            if not isinstance(raw_tag, Mapping):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "Pixiv artwork tag is invalid"
                )
            original = _text(raw_tag.get("name"))
            if not original:
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "Pixiv artwork tag has no name"
                )
            translated = _text(raw_tag.get("translated_name") or raw_tag.get("translation"))
            tags.append(
                {
                    "name": original,
                    "translated_name": translated,
                    "provider_name": original,
                    "provider_translation": translated,
                    "position": index,
                }
            )
        visible = illust.get("visible")
        availability = "available" if visible is not False else "restricted"
        x_restrict = _positive_int(illust.get("x_restrict"))
        if x_restrict and availability == "available":
            availability = "restricted"
        status = _text(illust.get("status"))
        if status and status.lower() in {"deleted", "removed"}:
            availability = "deleted"
        occurrences = self._page_occurrences(illust, native_id)
        author = None
        if author_id is not None:
            author = {
                "platform": self.provider_key,
                "native_id": author_id,
                "handle": _text(author_raw.get("account")),
                "display_name": _text(author_raw.get("name")),
                "canonical_url": f"https://www.pixiv.net/users/{author_id}",
                "role": "author",
            }
        data: dict[str, Any] = {
            "outcome": "success",
            "availability": availability,
            "platform": self.provider_key,
            "adapter_version": self.adapter_version,
            "schema_version": self.schema_version,
            "native_id": native_id,
            "canonical_url": f"https://www.pixiv.net/artworks/{native_id}",
            "title": _text(illust.get("title")),
            "caption": _text(illust.get("caption")),
            "text": _text(illust.get("caption")),
            "type": _text(illust.get("type")),
            "provider_type": _text(illust.get("type")),
            "created_at": _text(illust.get("create_date")),
            "updated_at": _text(illust.get("update_date")),
            "page_count": _positive_int(illust.get("page_count")),
            "width": _positive_int(illust.get("width")),
            "height": _positive_int(illust.get("height")),
            "rating": x_restrict,
            "restriction": x_restrict,
            "visible": visible,
            "visibility": "public" if visible is not False else "restricted",
            "status": status,
            "observation_time": response.observed_at,
            "account_id": author_id,
            "author_account_id": author_id,
            "author": author,
            "participants": ([{"role": "author", "account_id": author_id}] if author_id else []),
            "tags": tags,
            "tag_observations": tags,
            "media_occurrences": occurrences,
            "pages": occurrences,
            "metadata_only": True,
        }
        post_item = NormalizedItem("post", native_id, data)
        items: list[NormalizedItem] = [post_item]
        if author is None:
            items.extend(self._tag_items(native_id, tags))
            items.extend(self._media_items(native_id, occurrences))
            return NormalizedPage(tuple(items))
        account_data = {
            "outcome": "success",
            "availability": "available",
            "platform": self.provider_key,
            "adapter_version": self.adapter_version,
            "schema_version": self.schema_version,
            "native_id": author_id,
            "canonical_url": author["canonical_url"],
            "handle": author["handle"],
            "display_name": author["display_name"],
            "observation_time": response.observed_at,
        }
        items.extend(
            (
                NormalizedItem("account", author_id, account_data),
                NormalizedItem(
                    "post_participant",
                    f"{native_id}:author:{author_id}",
                    {
                        "platform": self.provider_key,
                        "post_id": native_id,
                        "account_id": author_id,
                        "role": "author",
                    },
                ),
            )
        )
        items.extend(self._tag_items(native_id, tags))
        items.extend(self._media_items(native_id, occurrences))
        return NormalizedPage(tuple(items))

    def _tag_items(self, post_id: str, tags: list[dict[str, Any]]) -> list[NormalizedItem]:
        return [
            NormalizedItem(
                "post_tag",
                f"{post_id}:{tag['name']}",
                {
                    "platform": self.provider_key,
                    "post_id": post_id,
                    "name": tag["name"],
                    "normalized_name": str(tag["name"]).casefold(),
                    "spelling": tag["name"],
                    "translated_name": tag["translated_name"],
                    "provider_name": tag["provider_name"],
                    "provider_translation": tag["provider_translation"],
                    "position": tag["position"],
                },
            )
            for tag in tags
        ]

    def _media_items(self, post_id: str, occurrences: list[dict[str, Any]]) -> list[NormalizedItem]:
        return [
            NormalizedItem(
                "media_occurrence",
                occurrence["source_key"],
                {"platform": self.provider_key, "post_id": post_id, **occurrence},
            )
            for occurrence in occurrences
        ]

    def _page_occurrences(self, illust: Mapping[str, Any], native_id: str) -> list[dict[str, Any]]:
        page_data = illust.get("meta_pages")
        if page_data is None:
            page_data = [illust]
        if not isinstance(page_data, list):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Pixiv artwork pages are invalid"
            )
        occurrences: list[dict[str, Any]] = []
        for index, page in enumerate(page_data):
            if not isinstance(page, Mapping):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "Pixiv artwork page is invalid"
                )
            image_urls = _mapping(page.get("image_urls"))
            if not image_urls:
                image_urls = _mapping(illust.get("image_urls")) if index == 0 else {}
            single = _mapping(page.get("meta_single_page")) or _mapping(
                illust.get("meta_single_page")
            )
            original = _url(image_urls.get("original") or single.get("original_image_url"))
            preview = _url(
                image_urls.get("large")
                or image_urls.get("medium")
                or image_urls.get("square_medium")
            )
            sample = _url(image_urls.get("medium") or image_urls.get("square_medium"))
            variants: list[dict[str, Any]] = []
            if original:
                variants.append({"role": "original", "url": original})
            if preview and preview != original:
                variants.append({"role": "preview", "url": preview})
            if sample and sample not in {original, preview}:
                variants.append({"role": "sample", "url": sample})
            occurrence = {
                "source_key": f"{native_id}:p{index}",
                "schema_version": "pixiv-variants-v1",
                "index": index,
                "role": "page",
                "media_type": self._mime_from_url(original or preview),
                "mime_type": self._mime_from_url(original or preview),
                "remote_url": original,
                "preview_url": preview,
                "sample_url": sample,
                "width": _positive_int(page.get("width") or illust.get("width")),
                "height": _positive_int(page.get("height") or illust.get("height")),
                "variants": variants,
                "variants_json": json.dumps(
                    {"version": "pixiv-variants-v1", "variants": variants},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "metadata_only": True,
            }
            occurrences.append(occurrence)
        return occurrences

    def _normalize_ugoira(self, response: ResponseEnvelope, native_id: str) -> NormalizedPage:
        body = _json_body(response.payload)
        metadata = _mapping(body.get("ugoira_metadata"))
        if not metadata:
            if response.status_code in {404, 410}:
                return self._unavailable_post(response, native_id=native_id)
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Pixiv Ugoira response has no metadata"
            )
        zip_urls = _mapping(metadata.get("zip_urls"))
        archive_url = _url(
            zip_urls.get("original") or zip_urls.get("medium") or zip_urls.get("large")
        )
        if archive_url is None:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Pixiv Ugoira metadata has no archive URL"
            )
        raw_frames = metadata.get("frames")
        if not isinstance(raw_frames, list):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "Pixiv Ugoira frames are invalid"
            )
        frames: list[dict[str, Any]] = []
        for index, raw_frame in enumerate(raw_frames):
            if not isinstance(raw_frame, Mapping) or not isinstance(raw_frame.get("file"), str):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "Pixiv Ugoira frame is invalid"
                )
            delay = _positive_int(raw_frame.get("delay"))
            if delay is None:
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "Pixiv Ugoira frame delay is invalid"
                )
            frame = dict(raw_frame)
            frame.update({"index": index, "delay_ms": delay})
            frames.append(frame)
        occurrence = {
            "source_key": f"{native_id}:ugoira",
            "schema_version": "pixiv-ugoira-v1",
            "index": 0,
            "role": "archive",
            "media_type": "application/zip",
            "mime_type": "application/zip",
            "remote_url": archive_url,
            "archive_url": archive_url,
            "archive": {"url": archive_url, "mime_type": "application/zip"},
            "frames": frames,
            "frame_delays_ms": [frame["delay_ms"] for frame in frames],
            "frame_delays": [frame["delay_ms"] for frame in frames],
            "width": _positive_int(metadata.get("width")),
            "height": _positive_int(metadata.get("height")),
            "variants": [{"role": "archive", "url": archive_url}],
            "variants_json": json.dumps(
                {
                    "version": "pixiv-ugoira-v1",
                    "archive": {"url": archive_url},
                    "frames": frames,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "metadata_only": True,
        }
        data = {
            "outcome": "success",
            "availability": "available",
            "platform": self.provider_key,
            "adapter_version": self.adapter_version,
            "schema_version": self.schema_version,
            "native_id": native_id,
            "canonical_url": f"https://www.pixiv.net/artworks/{native_id}",
            "type": "ugoira",
            "provider_type": "ugoira",
            "observation_time": response.observed_at,
            "media_occurrences": [occurrence],
            "metadata_only": True,
        }
        post_item = NormalizedItem("post", native_id, data)
        return NormalizedPage((post_item, *self._media_items(native_id, [occurrence])))

    def _unavailable_post(
        self, response: ResponseEnvelope, *, native_id: str | None = None
    ) -> NormalizedPage:
        target = native_id or self._id_from_identity(response.request_identity)
        message = ""
        try:
            body = _json_body(response.payload)
            message = _text(_mapping(body.get("error")).get("message")) or ""
        except AdapterFailure:
            pass
        outcome = (
            "deleted"
            if response.status_code == 410 or "deleted" in message.lower()
            else "unavailable"
        )
        data = {
            "outcome": outcome,
            "availability": outcome,
            "platform": self.provider_key,
            "adapter_version": self.adapter_version,
            "schema_version": self.schema_version,
            "native_id": target,
            "canonical_url": f"https://www.pixiv.net/artworks/{target}",
            "status": message or None,
            "observation_time": response.observed_at,
            "media_occurrences": [],
            "tags": [],
        }
        return NormalizedPage((NormalizedItem("post", target, data),))

    @staticmethod
    def _mime_from_url(value: str | None) -> str | None:
        if not value:
            return None
        suffix = value.lower().split("?", 1)[0].rsplit(".", 1)[-1]
        return {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
        }.get(suffix)

    @staticmethod
    def _id_from_identity(identity: str) -> str:
        parts = identity.split(":")
        if len(parts) >= 3:
            return _response_id(parts[2])
        raise AdapterFailure(
            AdapterOutcome.MALFORMED_RESPONSE, "Pixiv request identity has no target"
        )

    @staticmethod
    def _next_continuation(next_url: object) -> Continuation | None:
        if not isinstance(next_url, str) or not next_url.strip():
            return None
        parsed = urlsplit(next_url)
        values = parse_qs(parsed.query)
        raw_offset = values.get("offset", [None])[0]
        if raw_offset is not None and raw_offset.isdigit():
            return Continuation(PIXIV_PROVIDER, CONTINUATION_VERSION, {"offset": int(raw_offset)})
        # Keep an unknown provider cursor opaque.  It is never interpreted by the generic service.
        # Remove the known credential query keys before making the cursor durable.
        query = []
        for key, value in parse_qs(parsed.query, keep_blank_values=True).items():
            if key.lower() in {
                "access_token",
                "refresh_token",
                "api_key",
                "apikey",
                "authorization",
                "cookie",
            }:
                continue
            query.extend((key, item) for item in value)
        safe_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
        return Continuation(PIXIV_PROVIDER, CONTINUATION_VERSION, {"next_url": safe_url})


PixivMetadataAdapter = PixivAdapter
PixivClient = PixivAdapter
PixivTransport = PixivAdapter
