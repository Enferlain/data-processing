from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from media_catalog.adapters.contracts import (
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    AdapterRequest,
    Continuation,
    LookupContinuation,
    LookupRequest,
    LookupStrategy,
    NormalizedItem,
    NormalizedLookupPage,
    NormalizedLookupResult,
    NormalizedPage,
    ResponseEnvelope,
)
from media_catalog.adapters.danbooru.config import ADAPTER_VERSION, PROVIDER_KEY, DanbooruInstance

ALLOWED_RESPONSE_HEADERS = {"content-type", "retry-after", "x-rate-limit"}
TAG_CATEGORIES = ("artist", "character", "copyright", "general", "meta")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _stable_id(value: str, name: str) -> str:
    if not value.isdecimal() or int(value) < 1:
        raise ValueError(f"{name} must be a positive numeric stable ID")
    return str(int(value))


def _public_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        name: value for name, value in headers.items() if name.lower() in ALLOWED_RESPONSE_HEADERS
    }


@dataclass(frozen=True, slots=True)
class DanbooruCredentials:
    login: str = field(repr=False)
    api_key: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.login or not self.api_key:
            raise ValueError("both Danbooru login and API key are required")

    @classmethod
    def from_environment(
        cls,
        instance: DanbooruInstance,
        environ: Mapping[str, str] | None = None,
    ) -> DanbooruCredentials | None:
        values = os.environ if environ is None else environ
        login = values.get(instance.login_env)
        api_key = values.get(instance.api_key_env)
        if login is None and api_key is None:
            return None
        if not login or not api_key:
            raise ValueError(f"configure both {instance.login_env} and {instance.api_key_env}")
        return cls(login, api_key)


class DanbooruAdapter:
    provider_key = PROVIDER_KEY
    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        instance: DanbooruInstance,
        *,
        client: httpx.Client,
        credentials: DanbooruCredentials | None = None,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self.instance = instance
        self.instance_key = instance.platform_key
        self.schema_version = instance.schema_version
        self._client = client
        self._credentials = credentials
        self._clock = clock

    @property
    def lookup_capabilities(self):
        """Immutable capabilities for this configured instance."""

        return self.instance.lookup_capabilities

    @property
    def capabilities(self):
        """Compatibility shorthand exposing the supported strategy set."""

        return self.lookup_capabilities.strategies

    @property
    def enumeration_capabilities(self):
        return self.instance.enumeration_capabilities

    def fetch(self, request: AdapterRequest | LookupRequest) -> ResponseEnvelope:
        if isinstance(request, LookupRequest):
            return self.fetch_lookup(request)
        endpoint, params, identity = self._request_parts(request)
        headers = {"User-Agent": self.instance.user_agent, "Accept": "application/json"}
        if self._credentials is not None:
            raw = f"{self._credentials.login}:{self._credentials.api_key}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        response = self._client.get(
            self.instance.base_url + endpoint,
            params=params,
            headers=headers,
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
        )

    def fetch_lookup(self, request: LookupRequest) -> ResponseEnvelope:
        """Fetch one fixed-endpoint lookup page using injected HTTP transport only."""

        if not self.lookup_capabilities.supports(request.strategy):
            raise ValueError(
                f"{self.instance_key} does not support lookup strategy {request.strategy.value}"
            )
        endpoint, params, identity, cursor = self._lookup_request_parts(request)
        headers = {"User-Agent": self.instance.user_agent, "Accept": "application/json"}
        if self._credentials is not None:
            raw = f"{self._credentials.login}:{self._credentials.api_key}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        response = self._client.get(
            self.instance.base_url + endpoint,
            params=params,
            headers=headers,
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
            lookup_strategy=request.strategy,
            lookup_query_digest=request.material.digest,
            lookup_continuation=cursor,
            lookup_material=request.material,
        )

    def _lookup_request_parts(
        self, request: LookupRequest
    ) -> tuple[str, dict[str, str | int], str, LookupContinuation | None]:
        material = request.material
        cursor = request.continuation
        if cursor is not None:
            if (
                cursor.adapter != self.provider_key
                or cursor.version != self.schema_version
                or cursor.strategy is not request.strategy
                or cursor.query_digest != material.digest
            ):
                raise ValueError("incompatible Danbooru lookup continuation")
            alias_index = cursor.alias_index
            page = cursor.page
        else:
            alias_index = 0
            page = None
        if alias_index >= len(material.values):
            raise ValueError("lookup continuation alias index is out of range")
        value = material.values[alias_index]
        limit = min(request.limit, self.instance.page_size)
        params: dict[str, str | int]
        if request.strategy is LookupStrategy.SOURCE_POST_URL:
            params = {"tags": f"source:{value}", "limit": limit}
            endpoint = "/posts.json"
        elif request.strategy is LookupStrategy.EXTERNAL_POST_ID:
            if material.platform != "pixiv":
                raise ValueError("unsupported external post ID platform")
            params = {"tags": f"pixiv_id:{value}", "limit": limit}
            endpoint = "/posts.json"
        elif request.strategy in {LookupStrategy.DECLARED_MD5, LookupStrategy.VERIFIED_MD5}:
            params = {"tags": f"md5:{value}", "limit": limit}
            endpoint = "/posts.json"
        else:
            search_key = {
                LookupStrategy.ARTIST_EXACT_NAME: "search[name]",
                LookupStrategy.ARTIST_ALIAS: "search[any_name_matches]",
                LookupStrategy.ARTIST_TEXT: "search[any_name_matches]",
            }[request.strategy]
            if request.strategy is LookupStrategy.ARTIST_TEXT:
                value = f"*{value}*"
            params = {search_key: value, "limit": limit}
            endpoint = "/artists.json"
        if page is not None:
            params["page"] = page
        # Identity is intentionally digest-only: rendered URLs and query material never enter it.
        identity_payload = (
            f"{self.provider_key}|{self.instance_key}|{request.strategy.value}|"
            f"{material.digest}|{alias_index}|{page or 'first'}|{limit}"
        )
        identity = "lookup:" + hashlib.sha256(identity_payload.encode("utf-8")).hexdigest()
        return endpoint, params, identity, cursor

    def _request_parts(self, request: AdapterRequest) -> tuple[str, dict[str, str | int], str]:
        if request.operation is AdapterOperation.FETCH_POST:
            target = _stable_id(request.target, "post ID")
            return f"/posts/{target}.json", {}, f"{self.instance_key}:fetch_post:{target}"
        if request.operation is AdapterOperation.FETCH_ATTRIBUTION:
            target = _stable_id(request.target, "artist ID")
            return (
                f"/artists/{target}.json",
                {},
                f"{self.instance_key}:fetch_attribution:{target}",
            )
        if request.operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            params: dict[str, str | int] = {
                "tags": request.target,
                "limit": self.instance.page_size,
            }
            page = "first"
            if request.continuation is not None:
                if (
                    request.continuation.adapter != self.provider_key
                    or request.continuation.version != self.schema_version
                ):
                    raise ValueError("incompatible Danbooru continuation")
                raw_page = request.continuation.value.get("page")
                if not isinstance(raw_page, str) or not raw_page.startswith(("a", "b")):
                    raise ValueError("invalid Danbooru keyset continuation")
                params["page"] = raw_page
                page = raw_page
            identity = f"{self.instance_key}:list_account_posts:{request.target}:{page}"
            return "/posts.json", params, identity
        raise ValueError(f"unsupported Danbooru operation: {request.operation.value}")

    def normalize(self, response: ResponseEnvelope) -> NormalizedPage:
        self._validate_envelope(response)
        self._raise_for_outcome(response)
        try:
            body = json.loads(response.payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "provider returned invalid JSON"
            ) from error
        if response.operation is AdapterOperation.FETCH_POST:
            return NormalizedPage(tuple(self._post_items(body)))
        if response.operation is AdapterOperation.FETCH_ATTRIBUTION:
            return NormalizedPage((self._attribution_item(body),))
        if response.operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            return self._listing_page(body)
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "unsupported response operation")

    def normalize_lookup(
        self, response: ResponseEnvelope, request: LookupRequest | None = None
    ) -> NormalizedLookupPage:
        """Normalize a lookup page while retaining ordered, provider-attributed results."""

        self._validate_envelope(response)
        self._raise_for_outcome(response)
        if response.lookup_strategy is None:
            raise ValueError("response is not a lookup envelope")
        if request is None:
            if response.lookup_material is None:
                raise ValueError("lookup material is required to normalize a lookup response")
            request = LookupRequest(
                response.lookup_strategy,
                response.lookup_material,
                continuation=response.lookup_continuation,
            )
        elif request.strategy is not response.lookup_strategy:
            raise ValueError("lookup request strategy does not match response")
        if response.lookup_query_digest != request.material.digest:
            raise ValueError("lookup request material does not match response")
        try:
            body = json.loads(response.payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "provider returned invalid JSON"
            ) from error
        if isinstance(body, dict):
            body = [body]
        if not isinstance(body, list):
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "lookup response is not a list")
        results: list[NormalizedLookupResult] = []
        for rank, entry in enumerate(body):
            if request.strategy in {
                LookupStrategy.ARTIST_EXACT_NAME,
                LookupStrategy.ARTIST_ALIAS,
                LookupStrategy.ARTIST_TEXT,
            }:
                results.append(self._lookup_artist_result(entry, request, rank))
            else:
                results.append(self._lookup_post_result(entry, request, rank))
        continuation = self._lookup_continuation(request, body)
        return NormalizedLookupPage(tuple(results), continuation, len(results))

    def _lookup_post_result(
        self, entry: object, request: LookupRequest, rank: int
    ) -> NormalizedLookupResult:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), int):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "lookup post has no stable numeric ID"
            )
        # Search responses can be intentionally sparse; existing metadata normalization remains
        # strict, so fill absent tag buckets only for this lookup path.
        normalized_entry = dict(entry)
        for category in TAG_CATEGORIES:
            normalized_entry.setdefault(f"tag_string_{category}", "")
        post_id = str(entry["id"])
        items = tuple(self._post_items(normalized_entry))
        source = entry.get("source")
        declared_md5 = entry.get("md5")
        artist_tags = {
            category: entry.get(f"tag_string_{category}", "") for category in TAG_CATEGORIES
        }
        data = {
            "platform": self.instance_key,
            "post_id": post_id,
            "canonical_url": f"{self.instance.base_url}/posts/{post_id}",
            "query_kind": request.strategy.value,
            "query": request.material.value if len(request.material.values) == 1 else None,
            "source": source,
            "external_ids": {
                key: entry.get(key)
                for key in ("pixiv_id", "twitter_id", "twitter_status_id")
                if entry.get(key) is not None
            },
            "declared_md5": declared_md5,
            "uploader_id": entry.get("uploader_id"),
            "artist_tags": artist_tags,
            "availability": "deleted" if bool(entry.get("is_deleted")) else "available",
        }
        return NormalizedLookupResult("post", post_id, data, rank, items)

    def _lookup_artist_result(
        self, entry: object, request: LookupRequest, rank: int
    ) -> NormalizedLookupResult:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), int):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "lookup artist has no stable numeric ID"
            )
        normalized = dict(entry)
        normalized.setdefault("urls", [])
        normalized.setdefault("other_names", [])
        item = self._attribution_item(normalized)
        data = dict(item.data)
        data.update(
            {
                "query_kind": request.strategy.value,
                "query": request.material.value,
                "rank": rank,
                "replacement_id": entry.get("replacement_id"),
                "is_deprecated": bool(entry.get("is_deprecated", False)),
            }
        )
        return NormalizedLookupResult("attribution", str(entry["id"]), data, rank, (item,))

    def _lookup_continuation(
        self, request: LookupRequest, body: Sequence[object]
    ) -> LookupContinuation | None:
        cursor = request.continuation
        alias_index = cursor.alias_index if cursor is not None else 0
        last_id = body[-1].get("id") if body and isinstance(body[-1], dict) else None
        if isinstance(last_id, int) and len(body) >= min(request.limit, self.instance.page_size):
            return LookupContinuation(
                self.provider_key,
                self.schema_version,
                request.strategy,
                request.material.digest,
                f"b{last_id}",
                alias_index,
            )
        if request.strategy is LookupStrategy.SOURCE_POST_URL and alias_index + 1 < len(
            request.material.values
        ):
            return LookupContinuation(
                self.provider_key,
                self.schema_version,
                request.strategy,
                request.material.digest,
                None,
                alias_index + 1,
            )
        return None

    def _validate_envelope(self, response: ResponseEnvelope) -> None:
        if response.provider != self.provider_key or response.instance != self.instance_key:
            raise ValueError("response belongs to another provider instance")
        if response.schema_version != self.schema_version:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "incompatible provider schema version"
            )

    @staticmethod
    def _raise_for_outcome(response: ResponseEnvelope) -> None:
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
                AdapterOutcome.UNAVAILABLE, "provider record is unavailable", status_code=404
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

    def _post_items(self, body: object) -> list[NormalizedItem]:
        if not isinstance(body, dict) or not isinstance(body.get("id"), int):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "post response has no stable numeric ID"
            )
        post_id = str(body["id"])
        deleted = bool(body.get("is_deleted"))
        items = [
            NormalizedItem(
                "post",
                post_id,
                {
                    "platform": self.instance_key,
                    "canonical_url": f"{self.instance.base_url}/posts/{post_id}",
                    "created_at": body.get("created_at"),
                    "updated_at": body.get("updated_at"),
                    "rating": body.get("rating"),
                    "status": "deleted" if deleted else "available",
                    "availability": "deleted" if deleted else "available",
                },
            )
        ]
        uploader_id = body.get("uploader_id")
        if isinstance(uploader_id, int) and uploader_id > 0:
            uploader = str(uploader_id)
            items.extend(
                (
                    NormalizedItem(
                        "account",
                        uploader,
                        {"platform": self.instance_key, "availability": "available"},
                    ),
                    NormalizedItem(
                        "post_participant",
                        f"{post_id}:uploader:{uploader}",
                        {
                            "platform": self.instance_key,
                            "post_id": post_id,
                            "account_id": uploader,
                            "role": "uploader",
                        },
                    ),
                )
            )
        items.extend(self._tag_items(post_id, body))
        media = self._media_item(post_id, body, deleted=deleted)
        if media is not None:
            items.append(media)
        items.extend(self._reference_items(post_id, body))
        items.extend(self._relation_items(post_id, body))
        return items

    def _tag_items(self, post_id: str, body: Mapping[str, Any]) -> list[NormalizedItem]:
        items: list[NormalizedItem] = []
        for category in TAG_CATEGORIES:
            value = body.get(f"tag_string_{category}")
            if not isinstance(value, str):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    f"post response lacks {category} tag data",
                )
            for position, spelling in enumerate(filter(None, value.split(" "))):
                items.append(
                    NormalizedItem(
                        "post_tag",
                        f"{post_id}:{category}:{spelling}",
                        {
                            "platform": self.instance_key,
                            "post_id": post_id,
                            "category": category,
                            "normalized_name": spelling.casefold(),
                            "spelling": spelling,
                            "position": position,
                        },
                    )
                )
        return items

    def _media_item(
        self, post_id: str, body: Mapping[str, Any], *, deleted: bool
    ) -> NormalizedItem | None:
        original = body.get("file_url")
        sample = body.get("large_file_url")
        preview = body.get("preview_file_url")
        if not any(isinstance(value, str) and value for value in (original, sample, preview)):
            return None
        extension = body.get("file_ext")
        mime_type = (
            mimetypes.guess_type(f"file.{extension}")[0] if isinstance(extension, str) else None
        )
        variants = [
            {"role": role, "url": value}
            for role, value in (("original", original), ("sample", sample), ("preview", preview))
            if isinstance(value, str) and value
        ]
        return NormalizedItem(
            "media_occurrence",
            f"{post_id}:primary",
            {
                "platform": self.instance_key,
                "post_id": post_id,
                "source_key": "primary",
                "index": 0,
                "role": "primary",
                "remote_url": original,
                "preview_url": preview,
                "mime_type": mime_type,
                "declared_file_size": body.get("file_size"),
                "width": body.get("image_width"),
                "height": body.get("image_height"),
                "declared_md5": body.get("md5"),
                "variants": variants,
                "availability": "deleted" if deleted else "available",
            },
        )

    def _reference_items(self, post_id: str, body: Mapping[str, Any]) -> list[NormalizedItem]:
        items: list[NormalizedItem] = []
        source = body.get("source")
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
        pixiv_id = body.get("pixiv_id")
        if isinstance(pixiv_id, int) and pixiv_id > 0:
            items.append(
                NormalizedItem(
                    "external_reference",
                    f"{post_id}:pixiv:{pixiv_id}",
                    {
                        "platform": self.instance_key,
                        "post_id": post_id,
                        "target_platform": "pixiv",
                        "object_kind": "post",
                        "identifier_kind": "stable_id",
                        "native_identifier": str(pixiv_id),
                        "evidence_only": True,
                    },
                )
            )
        return items

    def _relation_items(self, post_id: str, body: Mapping[str, Any]) -> list[NormalizedItem]:
        items: list[NormalizedItem] = []
        parent_id = body.get("parent_id")
        if isinstance(parent_id, int) and parent_id > 0:
            items.append(self._relation(str(parent_id), post_id, "parent_of"))
        children = body.get("children", ())
        if isinstance(children, list):
            for child in children:
                child_id = child.get("id") if isinstance(child, dict) else child
                if isinstance(child_id, int) and child_id > 0:
                    items.append(self._relation(post_id, str(child_id), "parent_of"))
        return items

    def _relation(self, source: str, target: str, relation_type: str) -> NormalizedItem:
        return NormalizedItem(
            "post_relation",
            f"{source}:{relation_type}:{target}",
            {
                "platform": self.instance_key,
                "source_post_id": source,
                "target_post_id": target,
                "relation_type": relation_type,
            },
        )

    def _attribution_item(self, body: object) -> NormalizedItem:
        if not isinstance(body, dict) or not isinstance(body.get("id"), int):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "artist response has no stable numeric ID"
            )
        artist_id = str(body["id"])
        urls = body.get("urls", ())
        if not isinstance(urls, list):
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "artist URLs are malformed")
        public_urls = [
            entry["url"]
            for entry in urls
            if isinstance(entry, dict) and isinstance(entry.get("url"), str)
        ]
        other_names = body.get("other_names", ())
        if not isinstance(other_names, list) or not all(
            isinstance(name, str) for name in other_names
        ):
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "artist aliases are malformed")
        return NormalizedItem(
            "attribution",
            artist_id,
            {
                "platform": self.instance_key,
                "name": body.get("name"),
                "other_names": other_names,
                "urls": public_urls,
                "active": body.get("is_active"),
                "deleted": bool(body.get("is_deleted")),
                "is_deprecated": bool(body.get("is_deprecated", False)),
                "replacement_id": body.get("replacement_id"),
                "account": False,
            },
        )

    def _listing_page(self, body: object) -> NormalizedPage:
        if not isinstance(body, list):
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post listing is not a list")
        items: list[NormalizedItem] = []
        last_id: int | None = None
        for entry in body:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), int):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "post listing contains an invalid record"
                )
            last_id = entry["id"]
            if all(f"tag_string_{category}" in entry for category in TAG_CATEGORIES):
                items.extend(self._post_items(entry))
            else:
                items.append(
                    NormalizedItem(
                        "post",
                        str(last_id),
                        {"platform": self.instance_key, "availability": "available"},
                    )
                )
        continuation = (
            Continuation(self.provider_key, self.schema_version, {"page": f"b{last_id}"})
            if last_id is not None
            else None
        )
        return NormalizedPage(tuple(items), continuation)
