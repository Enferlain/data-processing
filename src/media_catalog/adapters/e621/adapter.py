"""Native e621 metadata adapter.

The adapter implements the provider-neutral :class:`Adapter` protocol against
e621's documented JSON API: explicit post fetch, artist/tag/tag-alias metadata
fetch, and bounded older-ID post listing.  It owns request rendering (exact
host/path/parameter admission, descriptive User-Agent, optional ephemeral Basic
authentication), typed status outcomes, and strict normalization that preserves
native provider facts and raw provenance without inferring review conclusions.

The adapter never makes media requests: returned media URLs are retained as
occurrence/variant metadata only.  Null media URLs are modeled as unavailable
representations and are never reconstructed from MD5.  MD5-based static-URL
derivation is explicitly forbidden.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

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
from media_catalog.adapters.e621.config import (
    ADAPTER_VERSION,
    CONTINUATION_VERSION,
    TAG_CATEGORY_ORDER,
    E621Instance,
    e621_category_label,
    neutral_category,
)

ALLOWED_RESPONSE_HEADERS = {"content-type", "retry-after", "x-rate-limit"}
_PAGE_RE = re.compile(r"^b(\d+)$")
_MAX_TARGET_LENGTH = 500


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
class E621Credentials:
    """Externally resolved e621 Basic-auth material; never persisted or logged."""

    username: str = field(repr=False)
    api_key: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.username or not self.api_key:
            raise ValueError("both e621 username and API key are required")

    @classmethod
    def from_environment(
        cls,
        instance: E621Instance,
        environ: Mapping[str, str] | None = None,
    ) -> E621Credentials | None:
        values = os.environ if environ is None else environ
        username = values.get(instance.username_env)
        api_key = values.get(instance.api_key_env)
        if username is None and api_key is None:
            return None
        if not username or not api_key:
            raise ValueError(f"configure both {instance.username_env} and {instance.api_key_env}")
        return cls(username, api_key)


class E621Adapter:
    provider_key = "e621"
    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        instance: E621Instance,
        *,
        client: httpx.Client,
        credentials: E621Credentials | None = None,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self.instance = instance
        self.instance_key = instance.instance_key
        self.schema_version = instance.schema_version
        self._client = client
        self._credentials = credentials
        self._clock = clock

    @property
    def minimum_interval_seconds(self) -> float:
        """The authoritative provider pacing floor exposed for the request gate."""

        return self.instance.minimum_interval_seconds

    @property
    def enumeration_capabilities(self):
        """Versioned capabilities exposed without enabling expansion in this slice."""

        return self.instance.enumeration_capabilities

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        endpoint, params, identity = self._request_parts(request)
        headers = {"User-Agent": self.instance.user_agent, "Accept": "application/json"}
        if self._credentials is not None:
            raw = f"{self._credentials.username}:{self._credentials.api_key}".encode()
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
            request_target=self._canonical_request_target(request),
        )

    def _canonical_request_target(self, request: AdapterRequest) -> str:
        if request.operation is AdapterOperation.FETCH_POST:
            return _stable_id(request.target, "post ID")
        if request.operation is AdapterOperation.FETCH_ATTRIBUTION:
            return _stable_id(request.target, "artist ID")
        if request.operation is AdapterOperation.FETCH_TAG:
            return _nonempty_target(request.target, "tag name")
        if request.operation is AdapterOperation.FETCH_TAG_ALIAS:
            return _nonempty_target(request.target, "alias antecedent")
        if request.operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            return _nonempty_target(request.target, "listing tag query")
        raise ValueError(f"unsupported e621 operation: {request.operation.value}")

    def _request_parts(self, request: AdapterRequest) -> tuple[str, dict[str, str | int], str]:
        operation = request.operation
        if operation is AdapterOperation.FETCH_POST:
            target = _stable_id(request.target, "post ID")
            return f"/posts/{target}.json", {}, f"{self.instance_key}:fetch_post:{target}"
        if operation is AdapterOperation.FETCH_ATTRIBUTION:
            target = _stable_id(request.target, "artist ID")
            return (
                f"/artists/{target}.json",
                {},
                f"{self.instance_key}:fetch_attribution:{target}",
            )
        if operation is AdapterOperation.FETCH_TAG:
            target = _nonempty_target(request.target, "tag name")
            return (
                "/tags.json",
                {"search[name]": target, "limit": 1},
                f"{self.instance_key}:fetch_tag:{target}",
            )
        if operation is AdapterOperation.FETCH_TAG_ALIAS:
            target = _nonempty_target(request.target, "alias antecedent")
            return (
                "/tag_aliases.json",
                {"search[antecedent_name]": target, "limit": 1},
                f"{self.instance_key}:fetch_tag_alias:{target}",
            )
        if operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            return self._listing_request_parts(request)
        raise ValueError(f"unsupported e621 operation: {operation.value}")

    def _listing_request_parts(
        self, request: AdapterRequest
    ) -> tuple[str, dict[str, str | int], str]:
        target = _nonempty_target(request.target, "listing tag query")
        page = "first"
        params: dict[str, str | int] = {"tags": target, "limit": self.instance.page_size}
        if request.continuation is not None:
            page = self._validate_listing_continuation(request.continuation, target=target)
            params["page"] = page
        identity = f"{self.instance_key}:list_account_posts:{target}:{page}"
        return "/posts.json", params, identity

    def _validate_listing_continuation(self, continuation: Continuation, *, target: str) -> str:
        if (
            continuation.adapter != self.provider_key
            or continuation.version != CONTINUATION_VERSION
        ):
            raise ValueError("incompatible e621 continuation adapter or version")
        value = continuation.value
        if value.get("direction") != "older":
            raise ValueError("e621 listing continuation must target older IDs")
        raw_page = value.get("page")
        if not isinstance(raw_page, str) or not _PAGE_RE.fullmatch(raw_page):
            raise ValueError("e621 continuation page must be an opaque b<ID> boundary")
        if value.get("operation") != AdapterOperation.LIST_ACCOUNT_POSTS.value:
            raise ValueError("e621 listing continuation operation is incompatible")
        if value.get("target") != target:
            raise ValueError("e621 listing continuation target is incompatible")
        if value.get("continuation_version") != CONTINUATION_VERSION:
            raise ValueError("e621 listing continuation version is incompatible")
        if value.get("adapter_version") != self.adapter_version:
            raise ValueError("e621 listing continuation adapter version is incompatible")
        if value.get("schema_version") != self.schema_version:
            raise ValueError("e621 listing continuation schema version is incompatible")
        boundary = int(raw_page[1:])
        if boundary < 1 or value.get("last_id") != boundary:
            raise ValueError("e621 continuation boundary is inconsistent")
        return raw_page

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
        if operation is AdapterOperation.FETCH_POST:
            return NormalizedPage(tuple(self._post_items(body)))
        if operation is AdapterOperation.FETCH_ATTRIBUTION:
            return NormalizedPage((self._attribution_item(body),))
        if operation is AdapterOperation.FETCH_TAG:
            return NormalizedPage(tuple(self._tag_record_items(body)))
        if operation is AdapterOperation.FETCH_TAG_ALIAS:
            return NormalizedPage(tuple(self._alias_items(body)))
        if operation is AdapterOperation.LIST_ACCOUNT_POSTS:
            return self._listing_page(
                body,
                target=response.request_target,
                request_identity=response.request_identity,
            )
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "unsupported response operation")

    def _validate_envelope(self, response: ResponseEnvelope) -> None:
        if response.provider != self.provider_key or response.instance != self.instance_key:
            raise ValueError("response belongs to another provider instance")
        if response.schema_version != self.schema_version:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "incompatible provider schema version"
            )

    @staticmethod
    def _retry_after_seconds(response: ResponseEnvelope) -> float | None:
        value = response.headers.get("retry-after")
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if not isfinite(parsed) or parsed < 0 or parsed > 86_400:
            return None
        return parsed

    @staticmethod
    def _retry_at(response: ResponseEnvelope, seconds: float | None) -> str | None:
        if seconds is None:
            return None
        observed_at = datetime.fromisoformat(response.observed_at.replace("Z", "+00:00"))
        return (
            (observed_at + timedelta(seconds=seconds))
            .astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z")
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
                AdapterOutcome.RATE_LIMITED,
                "provider rate limit reached",
                status_code=429,
                retry_at=self._retry_at(response, self._retry_after_seconds(response)),
                retry_after_seconds=self._retry_after_seconds(response),
            )
        if status == 503:
            # 503 is rate-limited only when the provider supplies retry evidence;
            # otherwise it is a transient provider condition.
            retry_after = self._retry_after_seconds(response)
            if retry_after is not None or response.headers.get("x-rate-limit") is not None:
                raise AdapterFailure(
                    AdapterOutcome.RATE_LIMITED,
                    "provider rate limit reached",
                    status_code=503,
                    retry_at=self._retry_at(response, retry_after),
                    retry_after_seconds=retry_after,
                )
            raise AdapterFailure(
                AdapterOutcome.TRANSIENT_PROVIDER,
                "provider is temporarily unavailable",
                status_code=503,
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

    def _post_items(self, body: object) -> list[NormalizedItem]:
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("id"), int)
            or isinstance(body.get("id"), bool)
        ):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "post response has no stable numeric ID"
            )
        _validate_post_shapes(body)
        post_id = str(body["id"])
        flags = body.get("flags")
        deleted = bool(isinstance(flags, dict) and flags.get("deleted"))
        canonical = f"{self.instance.base_url}/posts/{post_id}"
        score = body.get("score")
        items = [
            NormalizedItem(
                "post",
                post_id,
                {
                    "platform": self.instance_key,
                    "canonical_url": canonical,
                    "created_at": body.get("created_at"),
                    "updated_at": body.get("updated_at"),
                    "rating": body.get("rating"),
                    "status": "deleted" if deleted else "available",
                    "availability": "deleted" if deleted else "available",
                    "description_present": bool(body.get("description")),
                    "score": dict(score) if isinstance(score, dict) else None,
                    "fav_count": body.get("fav_count"),
                    "comment_count": body.get("comment_count"),
                    "uploader_id": body.get("uploader_id"),
                    "uploader_name": body.get("uploader_name"),
                    "pools": list(body["pools"]) if isinstance(body.get("pools"), list) else [],
                    "flags": dict(flags) if isinstance(flags, dict) else {},
                },
            )
        ]
        uploader_id = body.get("uploader_id")
        if isinstance(uploader_id, int) and not isinstance(uploader_id, bool) and uploader_id > 0:
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
        raw_tags = body.get("tags")
        if not isinstance(raw_tags, dict):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "post response lacks categorized tags"
            )
        if any(not isinstance(value, list) for value in raw_tags.values()):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "post response has malformed tag categories"
            )
        items: list[NormalizedItem] = []
        ordered = [
            category for category in TAG_CATEGORY_ORDER if isinstance(raw_tags.get(category), list)
        ]
        extras = sorted(
            category
            for category, value in raw_tags.items()
            if isinstance(value, list) and category not in TAG_CATEGORY_ORDER
        )
        for native_category_label in [*ordered, *extras]:
            spellings = raw_tags[native_category_label]
            for position, spelling in enumerate(spellings):
                if not isinstance(spelling, str) or not spelling:
                    raise AdapterFailure(
                        AdapterOutcome.MALFORMED_RESPONSE, "post response has malformed tag name"
                    )
                items.append(
                    NormalizedItem(
                        "post_tag",
                        f"{post_id}:{native_category_label}:{spelling}",
                        {
                            "platform": self.instance_key,
                            "post_id": post_id,
                            "category": neutral_category(native_category_label),
                            "native_category": native_category_label,
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
        file_obj = body.get("file")
        sample_obj = body.get("sample")
        preview_obj = body.get("preview")
        if not isinstance(file_obj, dict):
            return None
        _validate_media_shape(file_obj, "original")
        if isinstance(sample_obj, dict):
            _validate_media_shape(sample_obj, "sample")
        if isinstance(preview_obj, dict):
            _validate_media_shape(preview_obj, "preview")
        original_url = _opt_str(file_obj.get("url"))
        sample_url = _opt_str(sample_obj.get("url")) if isinstance(sample_obj, dict) else None
        preview_url = _opt_str(preview_obj.get("url")) if isinstance(preview_obj, dict) else None

        variants: list[dict[str, Any]] = []
        # Original representation owns the declared file facts.
        variants.append(
            {
                "role": "original",
                "url": original_url,
                "ext": file_obj.get("ext"),
                "mime_type": _mime_type(file_obj.get("ext")),
                "width": file_obj.get("width"),
                "height": file_obj.get("height"),
                "availability": _variant_availability(original_url, deleted),
            }
        )
        if isinstance(sample_obj, dict):
            variants.append(
                {
                    "role": "sample",
                    "url": sample_url,
                    "ext": sample_obj.get("ext"),
                    "mime_type": _mime_type(sample_obj.get("ext")),
                    "width": sample_obj.get("width"),
                    "height": sample_obj.get("height"),
                    "availability": _variant_availability(sample_url, deleted),
                }
            )
        if isinstance(preview_obj, dict):
            variants.append(
                {
                    "role": "preview",
                    "url": preview_url,
                    "ext": preview_obj.get("ext"),
                    "mime_type": _mime_type(preview_obj.get("ext")),
                    "width": preview_obj.get("width"),
                    "height": preview_obj.get("height"),
                    "availability": _variant_availability(preview_url, deleted),
                }
            )

        extension = file_obj.get("ext")
        mime_type = _mime_type(extension)
        any_url = bool(original_url or sample_url or preview_url)
        if deleted:
            availability = "deleted"
        elif any_url:
            availability = "available"
        else:
            availability = "unavailable"
        return NormalizedItem(
            "media_occurrence",
            f"{post_id}:primary",
            {
                "platform": self.instance_key,
                "post_id": post_id,
                "source_key": "primary",
                "index": 0,
                "role": "primary",
                "remote_url": original_url,
                "preview_url": preview_url,
                "mime_type": mime_type,
                "extension": extension if isinstance(extension, str) else None,
                "declared_md5": file_obj.get("md5"),
                "declared_file_size": file_obj.get("size"),
                "width": file_obj.get("width"),
                "height": file_obj.get("height"),
                "variants": variants,
                "availability": availability,
            },
        )

    def _reference_items(self, post_id: str, body: Mapping[str, Any]) -> list[NormalizedItem]:
        items: list[NormalizedItem] = []
        sources = body.get("sources")
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, str) and source:
                    items.append(
                        NormalizedItem(
                            "external_reference",
                            f"{post_id}:source:{source}",
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

    def _relation_items(self, post_id: str, body: Mapping[str, Any]) -> list[NormalizedItem]:
        items: list[NormalizedItem] = []
        relationships = body.get("relationships")
        if isinstance(relationships, dict):
            parent_id = relationships.get("parent_id")
            if isinstance(parent_id, int) and not isinstance(parent_id, bool) and parent_id > 0:
                items.append(self._relation(str(parent_id), post_id, "parent_of"))
            children = relationships.get("children")
            if isinstance(children, list):
                for child_id in children:
                    if (
                        isinstance(child_id, int)
                        and not isinstance(child_id, bool)
                        and child_id > 0
                    ):
                        items.append(self._relation(post_id, str(child_id), "parent_of"))
        # A has_children flag is not a child identity.  No pool/note or media
        # fan-out is synthesized from flags, MD5, or pool ids.
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
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("id"), int)
            or isinstance(body.get("id"), bool)
            or body["id"] < 1
        ):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "artist response has no stable numeric ID"
            )
        artist_id = str(body["id"])
        name = body.get("name")
        if not isinstance(name, str) or not name:
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "artist name is malformed")
        urls = body.get("urls")
        public_urls: list[str] = []
        if isinstance(urls, list):
            for entry in urls:
                if isinstance(entry, str) and entry:
                    public_urls.append(entry)
                elif isinstance(entry, dict) and isinstance(entry.get("url"), str) and entry["url"]:
                    public_urls.append(entry["url"])
                else:
                    raise AdapterFailure(
                        AdapterOutcome.MALFORMED_RESPONSE, "artist URL entry is malformed"
                    )
        else:
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "artist URLs are malformed")
        other_names = body.get("other_names")
        if not isinstance(other_names, list) or not all(
            isinstance(name, str) for name in other_names
        ):
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "artist aliases are malformed")
        return NormalizedItem(
            "attribution",
            artist_id,
            {
                "platform": self.instance_key,
                "canonical_url": f"{self.instance.base_url}/artists/{artist_id}",
                "name": name,
                "other_names": other_names,
                "group_name": body.get("group_name"),
                "urls": public_urls,
                "domains": _string_list(body.get("domains")),
                "created_at": body.get("created_at"),
                "updated_at": body.get("updated_at"),
                "deleted": bool(body.get("is_deleted")),
                "is_banned": bool(body.get("is_banned")),
                "is_locked": bool(body.get("is_locked")),
                "linked_user_id": body.get("linked_user_id"),
                "account": False,
            },
        )

    def _tag_record_items(self, body: object) -> list[NormalizedItem]:
        if not isinstance(body, (list, dict)):
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "tag response is malformed")
        entries = body if isinstance(body, list) else [body]
        items: list[NormalizedItem] = []
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("id"), int)
                or isinstance(entry.get("id"), bool)
                or entry["id"] < 1
            ):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "tag response has no stable numeric ID"
                )
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "tag name is malformed")
            code = entry.get("category")
            if not isinstance(code, int) or isinstance(code, bool) or code < 0:
                raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "tag category is malformed")
            label = e621_category_label(code)
            post_count = entry.get("post_count")
            if post_count is not None and (
                not isinstance(post_count, int) or isinstance(post_count, bool) or post_count < 0
            ):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "tag post count is malformed"
                )
            locked = entry.get("is_locked")
            if locked is not None and not isinstance(locked, bool):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "tag lock state is malformed"
                )
            items.append(
                NormalizedItem(
                    "tag",
                    str(entry["id"]),
                    {
                        "platform": self.instance_key,
                        "tag_id": str(entry["id"]),
                        "name": name,
                        "normalized_name": name.casefold(),
                        "category": neutral_category(label) if label is not None else "unknown",
                        "native_category_code": code if isinstance(code, int) else None,
                        "native_category": label,
                        "post_count": post_count,
                        "is_locked": locked,
                        "created_at": entry.get("created_at"),
                        "updated_at": entry.get("updated_at"),
                    },
                )
            )
        return items

    def _alias_items(self, body: object) -> list[NormalizedItem]:
        if not isinstance(body, (list, dict)):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "tag alias response is malformed"
            )
        entries = body if isinstance(body, list) else [body]
        items: list[NormalizedItem] = []
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("id"), int)
                or isinstance(entry.get("id"), bool)
                or entry["id"] < 1
            ):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "alias response has no stable numeric ID"
                )
            antecedent = entry.get("antecedent_name")
            consequent = entry.get("consequent_name")
            status = entry.get("status")
            if (
                not isinstance(antecedent, str)
                or not antecedent
                or not isinstance(consequent, str)
                or not consequent
                or not isinstance(status, str)
                or not status
            ):
                raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "tag alias is malformed")
            items.append(
                NormalizedItem(
                    "tag_alias",
                    str(entry["id"]),
                    {
                        "platform": self.instance_key,
                        "alias_id": str(entry["id"]),
                        "antecedent": antecedent,
                        "consequent": consequent,
                        "status": status,
                        "active": status == "active",
                        "post_count": entry.get("post_count"),
                        "created_at": entry.get("created_at"),
                        "updated_at": entry.get("updated_at"),
                        "creator_id": entry.get("creator_id"),
                        "reason": entry.get("reason"),
                        "forum_topic_id": entry.get("forum_topic_id"),
                    },
                )
            )
        return items

    def _listing_page(
        self,
        body: object,
        *,
        target: str | None,
        request_identity: str,
    ) -> NormalizedPage:
        if not isinstance(body, list):
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post listing is not a list")
        if target is None:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE,
                "post listing response has no request target",
            )
        items: list[NormalizedItem] = []
        last_id: int | None = None
        request_page = request_identity.rsplit(":", 1)[-1]
        boundary: int | None = None
        if request_page != "first":
            if not _PAGE_RE.fullmatch(request_page):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "post listing request identity has an invalid boundary",
                )
            boundary = int(request_page[1:])
        for entry in body:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("id"), int)
                or isinstance(entry.get("id"), bool)
                or entry["id"] < 1
            ):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "post listing contains an invalid record"
                )
            post_id = entry["id"]
            if boundary is not None and post_id >= boundary:
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "post listing crossed or repeated its keyset boundary",
                )
            last_id = post_id
            items.extend(self._post_items(entry))
        continuation = self._listing_continuation(target, last_id)
        return NormalizedPage(tuple(items), continuation)

    def _listing_continuation(self, target: str, last_id: int | None) -> Continuation | None:
        if last_id is None:
            return None
        return Continuation(
            self.provider_key,
            CONTINUATION_VERSION,
            {
                "operation": AdapterOperation.LIST_ACCOUNT_POSTS.value,
                "target": target,
                "page": f"b{last_id}",
                "direction": "older",
                "last_id": last_id,
                "continuation_version": CONTINUATION_VERSION,
                "adapter_version": self.adapter_version,
                "schema_version": self.schema_version,
            },
        )


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, str) and entry]


def _nonempty_target(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"e621 {name} must be non-empty text")
    value = value.strip()
    if len(value) > _MAX_TARGET_LENGTH or any(ord(char) < 32 for char in value):
        raise ValueError(f"e621 {name} must be bounded text without control characters")
    return value


def _mime_type(extension: object) -> str | None:
    if not isinstance(extension, str) or not extension:
        return None
    return mimetypes.guess_type(f"file.{extension}")[0]


def _variant_availability(url: str | None, deleted: bool) -> str:
    if deleted:
        return "deleted"
    return "available" if url is not None else "unavailable"


def _validate_post_shapes(body: Mapping[str, Any]) -> None:
    for name in ("fav_count", "comment_count"):
        value = body.get(name)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, f"post {name} is malformed")
    score = body.get("score")
    if score is not None:
        if not isinstance(score, dict):
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post score is malformed")
        for name in ("up", "down", "total"):
            value = score.get(name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post score is malformed")
            if name in {"up", "down"} and value is not None and value < 0:
                raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post score is malformed")
    flags = body.get("flags")
    if flags is not None and (
        not isinstance(flags, dict)
        or any(
            not isinstance(name, str) or not isinstance(value, bool)
            for name, value in flags.items()
        )
    ):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post flags are malformed")
    pools = body.get("pools")
    if pools is not None and (
        not isinstance(pools, list)
        or any(not isinstance(pool, int) or isinstance(pool, bool) or pool < 1 for pool in pools)
    ):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post pools are malformed")
    sources = body.get("sources")
    if sources is not None and (
        not isinstance(sources, list)
        or any(not isinstance(source, str) or not source for source in sources)
    ):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post sources are malformed")
    uploader_id = body.get("uploader_id")
    if uploader_id is not None and (
        not isinstance(uploader_id, int) or isinstance(uploader_id, bool) or uploader_id < 1
    ):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post uploader ID is malformed")
    uploader_name = body.get("uploader_name")
    if uploader_name is not None and (not isinstance(uploader_name, str) or not uploader_name):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "post uploader name is malformed")


def _validate_media_shape(value: Mapping[str, Any], role: str) -> None:
    for name in ("width", "height", "size"):
        field = value.get(name)
        if field is not None and (
            not isinstance(field, int) or isinstance(field, bool) or field < 0
        ):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, f"{role} media {name} is malformed"
            )
    extension = value.get("ext")
    if extension is not None and (not isinstance(extension, str) or not extension):
        raise AdapterFailure(
            AdapterOutcome.MALFORMED_RESPONSE, f"{role} media extension is malformed"
        )
    digest = value.get("md5")
    if digest is not None and (
        not isinstance(digest, str)
        or len(digest) != 32
        or any(char not in "0123456789abcdefABCDEF" for char in digest)
    ):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, f"{role} media MD5 is malformed")
