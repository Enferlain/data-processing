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
import hashlib
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
    LookupCapabilities,
    LookupContinuation,
    LookupQueryMaterial,
    LookupRequest,
    LookupStrategy,
    NormalizedItem,
    NormalizedLookupPage,
    NormalizedLookupResult,
    NormalizedPage,
    ResponseEnvelope,
)
from media_catalog.adapters.e621.config import (
    ADAPTER_VERSION,
    CONTINUATION_VERSION,
    PROVIDER_KEY,
    TAG_CATEGORY_ORDER,
    E621Instance,
    e621_category_label,
    neutral_category,
)
from media_catalog.links import recognize_url

ALLOWED_RESPONSE_HEADERS = {"content-type", "retry-after", "x-rate-limit"}
_PAGE_RE = re.compile(r"^b(\d+)$")
_MAX_TARGET_LENGTH = 500
_MAX_LOOKUP_TEXT = 200


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
    provider_key = PROVIDER_KEY
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

    @property
    def lookup_capabilities(self) -> LookupCapabilities:
        """Immutable exact reverse-lookup contract for this configured instance."""

        return self.instance.lookup_capabilities

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

    def fetch_lookup(self, request: LookupRequest) -> ResponseEnvelope:
        """Fetch one fixed-endpoint lookup page using injected HTTP transport only.

        Only the six declared exact strategies are rendered.  ``ARTIST_TEXT`` (and
        any other undeclared strategy) is rejected before any HTTP request.  The
        rendered envelope is lookup-marked and retains private query material
        only on the (non-repr) ``lookup_material`` field; the public request
        identity and digest are secret-free.
        """

        if not self.lookup_capabilities.supports(request.strategy):
            raise ValueError(
                f"{self.instance_key} does not support lookup strategy {request.strategy.value}"
            )
        endpoint, params, identity, cursor = self._lookup_request_parts(request)
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
                raise ValueError("incompatible e621 lookup continuation")
            alias_index = cursor.alias_index
            page = cursor.page
        else:
            alias_index = 0
            page = None
        if alias_index >= len(material.values):
            raise ValueError("lookup continuation alias index is out of range")
        value = material.values[alias_index]
        strategy = request.strategy
        limit = min(request.limit, self.instance.page_size)
        params: dict[str, str | int]
        if strategy is LookupStrategy.SOURCE_POST_URL:
            _exact_source_lookup_text(value)
            params = {"tags": f"source:{value}", "limit": limit}
            endpoint = "/posts.json"
        elif strategy is LookupStrategy.EXTERNAL_POST_ID:
            params = {"tags": f"source:{_external_post_source(material, value)}", "limit": limit}
            endpoint = "/posts.json"
        elif strategy in {LookupStrategy.DECLARED_MD5, LookupStrategy.VERIFIED_MD5}:
            params = {"tags": f"md5:{value}", "limit": limit}
            endpoint = "/posts.json"
        elif strategy is LookupStrategy.ARTIST_EXACT_NAME:
            # Exact artist-category tag metadata lookup -- a bounded, exact
            # ``search[name]`` against the tag record, never unrestricted text.
            _bounded_lookup_text(value, "artist name")
            params = {"search[name]": value, "limit": 1}
            endpoint = "/tags.json"
        elif strategy is LookupStrategy.ARTIST_ALIAS:
            # Alias evidence restricted at request time to approved/active
            # canonicalizable aliases; status interpretation is task 5.3.
            _bounded_lookup_text(value, "artist alias")
            params = {
                "search[antecedent_name]": value,
                "search[status]": "active",
                "limit": 1,
            }
            endpoint = "/tag_aliases.json"
        else:  # pragma: no cover - undeclared strategies are rejected in fetch_lookup
            raise ValueError(f"e621 does not render lookup strategy {strategy.value}")
        if page is not None:
            if strategy in {LookupStrategy.ARTIST_EXACT_NAME, LookupStrategy.ARTIST_ALIAS}:
                raise ValueError("e621 artist metadata lookup does not support pagination")
            match = _PAGE_RE.fullmatch(page)
            if match is None or int(match.group(1)) < 1:
                raise ValueError("e621 lookup continuation page must be an opaque b<ID> boundary")
            params["page"] = page
        # Identity is intentionally digest-only: rendered URLs, query text, and
        # secrets never enter it.
        identity = self._lookup_identity(strategy, material.digest, alias_index, page, limit)
        return endpoint, params, identity, cursor

    def _lookup_identity(
        self,
        strategy: LookupStrategy,
        digest: str,
        alias_index: int,
        page: str | None,
        limit: int,
    ) -> str:
        payload = (
            f"{self.provider_key}|{self.instance_key}|{strategy.value}|"
            f"{digest}|{alias_index}|{page or 'first'}|{limit}"
        )
        return "lookup:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

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

    def normalize_lookup(
        self, response: ResponseEnvelope, request: LookupRequest | None = None
    ) -> NormalizedLookupPage:
        """Normalize one bounded e621 lookup response.

        Lookup endpoints return arrays even when they contain one metadata record.  The
        lookup path therefore stays stricter than ordinary object fetches: malformed
        envelopes and non-array payloads fail closed, while the existing post/tag/alias
        normalizers provide the nested provider facts.  Raw response bytes are retained by
        the lookup service; the safe provenance marker attached here binds each normalized
        item to that retained response without copying query text or secrets.
        """

        self._validate_envelope(response)
        if response.adapter_version != self.adapter_version:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "incompatible provider adapter version"
            )
        self._raise_for_outcome(response)
        strategy = response.lookup_strategy
        if strategy is None:
            raise ValueError("response is not a lookup envelope")
        if request is None:
            if response.lookup_material is None:
                raise ValueError("lookup material is required to normalize a lookup response")
            request = LookupRequest(
                strategy,
                response.lookup_material,
                continuation=response.lookup_continuation,
            )
        elif request.strategy is not strategy:
            raise ValueError("lookup request strategy does not match response")
        if response.lookup_material is not None:
            if response.lookup_material.strategy is not strategy:
                raise ValueError("lookup response material strategy does not match response")
            if response.lookup_material.digest != request.material.digest:
                raise ValueError("lookup response material does not match request")
        if response.lookup_query_digest != request.material.digest:
            raise ValueError("lookup request material does not match response")
        if response.lookup_continuation != request.continuation:
            raise ValueError("lookup request continuation does not match response")
        try:
            body = json.loads(response.payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "provider returned invalid JSON"
            ) from error
        if not isinstance(body, list):
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "lookup response is not a list")

        provenance = {
            "provider": self.provider_key,
            "schema_version": self.schema_version,
            "strategy": strategy.value,
            "query_digest": request.material.digest,
            "request_identity": response.request_identity,
        }
        results: list[NormalizedLookupResult] = []
        for rank, entry in enumerate(body):
            if strategy in {
                LookupStrategy.SOURCE_POST_URL,
                LookupStrategy.EXTERNAL_POST_ID,
                LookupStrategy.DECLARED_MD5,
                LookupStrategy.VERIFIED_MD5,
            }:
                results.append(self._lookup_post_result(entry, request, rank, provenance))
            elif strategy is LookupStrategy.ARTIST_EXACT_NAME:
                result = self._lookup_artist_tag_result(entry, request, rank, provenance)
                if result is not None:
                    results.append(result)
            elif strategy is LookupStrategy.ARTIST_ALIAS:
                result = self._lookup_alias_result(entry, request, rank, provenance)
                if result is not None:
                    results.append(result)
            else:  # pragma: no cover - capabilities reject undeclared strategies first
                raise ValueError(f"e621 does not normalize lookup strategy {strategy.value}")

        self._validate_lookup_boundary(body, request.continuation)
        continuation = self._lookup_continuation(request, body)
        return NormalizedLookupPage(tuple(results), continuation, len(results))

    def _lookup_post_result(
        self,
        entry: object,
        request: LookupRequest,
        rank: int,
        provenance: Mapping[str, Any],
    ) -> NormalizedLookupResult:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("id"), int)
            or isinstance(entry.get("id"), bool)
            or entry["id"] < 1
        ):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "lookup post has no stable numeric ID"
            )
        # e621 /posts.json lookup responses are full post objects.  Reuse the ordinary
        # normalizer so null media, dynamic categories, uploader role, sources, hashes,
        # and relationships keep exactly the same representation as explicit fetches.
        items = self._with_lookup_provenance(tuple(self._post_items(entry)), provenance)
        post_id = str(entry["id"])
        sources = _source_values(entry.get("sources"))
        tags = entry.get("tags")
        if not isinstance(tags, dict):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "lookup post lacks categorized tags"
            )
        artist_tags = tags.get("artist", [])
        if not isinstance(artist_tags, list) or any(
            not isinstance(tag, str) or not tag for tag in artist_tags
        ):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "lookup post has malformed artist tags"
            )
        declared_md5: str | None = None
        file_obj = entry.get("file")
        if isinstance(file_obj, dict):
            value = file_obj.get("md5")
            if value is not None and not isinstance(value, str):
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE, "lookup post has malformed declared MD5"
                )
            declared_md5 = value
        external_ids = _proven_external_ids(sources)
        data = {
            "platform": self.instance_key,
            "post_id": post_id,
            "canonical_url": f"{self.instance.base_url}/posts/{post_id}",
            "query_kind": request.strategy.value,
            "query": request.material.value if len(request.material.values) == 1 else None,
            "source": sources[0] if len(sources) == 1 else None,
            "sources": sources,
            "external_ids": external_ids,
            "declared_md5": declared_md5,
            "uploader_id": entry.get("uploader_id"),
            "uploader_name": entry.get("uploader_name"),
            "artist_tags": list(artist_tags),
            "tag_categories": {
                category: list(values)
                for category, values in tags.items()
                if isinstance(category, str) and isinstance(values, list)
            },
            "availability": "deleted"
            if bool(isinstance(entry.get("flags"), dict) and entry["flags"].get("deleted"))
            else "available",
            "lookup_provenance": dict(provenance),
        }
        return NormalizedLookupResult("post", post_id, data, rank, items)

    def _lookup_artist_tag_result(
        self,
        entry: object,
        request: LookupRequest,
        rank: int,
        provenance: Mapping[str, Any],
    ) -> NormalizedLookupResult | None:
        tag_items = self._tag_record_items(entry if isinstance(entry, list) else [entry])
        if len(tag_items) != 1:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "artist lookup returned an invalid tag record"
            )
        tag = tag_items[0]
        name = tag.data.get("name")
        if not isinstance(name, str) or name.casefold() != request.material.value.casefold():
            return None
        if tag.data.get("native_category") != "artist":
            return None
        tag_id = tag.native_id
        if tag_id is None:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "artist lookup tag has no stable ID"
            )
        tag_data = dict(tag.data)
        tag_data["lookup_provenance"] = dict(provenance)
        tag = NormalizedItem(tag.object_kind, tag_id, tag_data)
        attribution_id = f"tag:{tag_id}"
        attribution = self._lookup_attribution_item(attribution_id, name, "tag", tag_id, provenance)
        data = {
            **tag_data,
            "attribution_native_id": attribution_id,
            "query_kind": request.strategy.value,
            "query": request.material.value,
            "rank": rank,
            "attribution_kind": "artist_tag",
            "target_kind": "tag",
            "provider_tag_id": tag_id,
            "urls": [],
            "lookup_provenance": dict(provenance),
        }
        return NormalizedLookupResult("attribution", tag_id, data, rank, (tag, attribution))

    def _lookup_alias_result(
        self,
        entry: object,
        request: LookupRequest,
        rank: int,
        provenance: Mapping[str, Any],
    ) -> NormalizedLookupResult | None:
        alias_items = self._alias_items(entry if isinstance(entry, list) else [entry])
        if len(alias_items) != 1:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "artist alias lookup returned an invalid record"
            )
        alias = alias_items[0]
        antecedent = alias.data.get("antecedent")
        consequent = alias.data.get("consequent")
        status = alias.data.get("status")
        post_count = alias.data.get("post_count")
        if post_count is not None and (
            not isinstance(post_count, int) or isinstance(post_count, bool) or post_count < 0
        ):
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "artist alias post count is malformed"
            )
        if (
            not isinstance(antecedent, str)
            or antecedent.casefold() != request.material.value.casefold()
            or not isinstance(consequent, str)
            or not consequent
            or not isinstance(status, str)
            or status.casefold() not in {"active", "approved"}
        ):
            return None
        try:
            _bounded_lookup_text(consequent, "canonical artist alias")
        except ValueError as error:
            raise AdapterFailure(
                AdapterOutcome.MALFORMED_RESPONSE, "artist alias consequent is malformed"
            ) from error
        alias_id = alias.native_id
        if alias_id is None:
            raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "artist alias has no stable ID")
        alias_data = dict(alias.data)
        alias_data["active"] = True
        alias_data["lookup_provenance"] = dict(provenance)
        alias = NormalizedItem(alias.object_kind, alias_id, alias_data)
        attribution_id = f"alias:{alias_id}"
        attribution = self._lookup_attribution_item(
            attribution_id, consequent, "alias", alias_id, provenance
        )
        data = {
            **alias_data,
            "attribution_native_id": attribution_id,
            "name": consequent,
            "normalized_name": consequent.casefold(),
            "query_kind": request.strategy.value,
            "query": request.material.value,
            "rank": rank,
            "attribution_kind": "approved_artist_alias",
            "target_kind": "tag",
            "canonical_consequent": consequent,
            "urls": [],
            "lookup_provenance": dict(provenance),
        }
        return NormalizedLookupResult("attribution", alias_id, data, rank, (alias, attribution))

    def _lookup_attribution_item(
        self,
        native_id: str,
        name: str,
        evidence_kind: str,
        evidence_id: str,
        provenance: Mapping[str, Any],
    ) -> NormalizedItem:
        return NormalizedItem(
            "attribution",
            native_id,
            {
                "platform": self.instance_key,
                "name": name,
                "other_names": [],
                "urls": [],
                "domains": [],
                "linked_user_id": None,
                "account": False,
                "attribution_kind": evidence_kind,
                "provider_evidence_id": evidence_id,
                "lookup_provenance": dict(provenance),
            },
        )

    @staticmethod
    def _with_lookup_provenance(
        items: tuple[NormalizedItem, ...], provenance: Mapping[str, Any]
    ) -> tuple[NormalizedItem, ...]:
        return tuple(
            NormalizedItem(
                item.object_kind,
                item.native_id,
                {**item.data, "lookup_provenance": dict(provenance)},
            )
            for item in items
        )

    def _validate_lookup_boundary(
        self, body: list[object], continuation: LookupContinuation | None
    ) -> None:
        if continuation is None or continuation.page is None:
            return
        match = _PAGE_RE.fullmatch(continuation.page)
        if match is None:
            raise ValueError("e621 lookup continuation page must be an opaque b<ID> boundary")
        boundary = int(match.group(1))
        for entry in body:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), int):
                continue
            if entry["id"] >= boundary:
                raise AdapterFailure(
                    AdapterOutcome.MALFORMED_RESPONSE,
                    "lookup response crossed or repeated its keyset boundary",
                )

    def _lookup_continuation(
        self, request: LookupRequest, body: list[object]
    ) -> LookupContinuation | None:
        if request.strategy in {
            LookupStrategy.ARTIST_EXACT_NAME,
            LookupStrategy.ARTIST_ALIAS,
        }:
            return None
        cursor = request.continuation
        alias_index = cursor.alias_index if cursor is not None else 0
        last_id = body[-1].get("id") if body and isinstance(body[-1], dict) else None
        page_size = min(request.limit, self.instance.page_size)
        if isinstance(last_id, int) and not isinstance(last_id, bool) and len(body) >= page_size:
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


def _source_values(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise AdapterFailure(AdapterOutcome.MALFORMED_RESPONSE, "lookup post sources are malformed")
    return list(value)


def _proven_external_ids(sources: list[str]) -> dict[str, str]:
    """Extract only stable external IDs explicitly proven by returned source URLs."""

    pixiv_ids: set[str] = set()
    for source in sources:
        reference = recognize_url(source).reference
        if (
            reference is not None
            and reference.platform == "pixiv"
            and reference.object_kind == "post"
            and reference.identifier_kind == "stable_id"
            and reference.native_id.isdecimal()
        ):
            pixiv_ids.add(reference.native_id)
    return {"pixiv_id": next(iter(pixiv_ids))} if len(pixiv_ids) == 1 else {}


def _bounded_lookup_text(value: str, name: str) -> None:
    """Defensive check that lookup query text is bounded and non-control.

    ``LookupQueryMaterial`` already enforces a length ceiling and rejects control
    characters; this guards the render path independently so a future caller that
    constructs material differently still fails closed before transport.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"e621 {name} must be non-empty text")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"e621 {name} must not contain control characters")
    if len(value) > _MAX_LOOKUP_TEXT:
        raise ValueError(f"e621 {name} exceeds {_MAX_LOOKUP_TEXT} characters")


def _exact_source_lookup_text(value: str) -> None:
    _bounded_lookup_text(value, "source post URL")
    if "*" in value or any(char.isspace() for char in value):
        raise ValueError("e621 source post URL must be one exact source token")


def _external_post_source(material: LookupQueryMaterial, value: str) -> str:
    """Render the e621 exact source query for an external post-id material.

    e621 exposes no per-platform external-id metatag; its only exact match for a
    foreign post is the ``source:`` metatag against the canonical source URL.
    Only the stable, documented pixiv artwork URL is constructed; any other
    platform (or a non-numeric id) fails closed before any request.
    """

    platform = material.platform
    if platform == "pixiv":
        if not value.isdecimal() or int(value) < 1:
            raise ValueError("external pixiv post id must be a positive numeric id")
        return f"https://www.pixiv.net/artworks/{int(value)}"
    raise ValueError(f"e621 lookup does not support external platform {platform!r}")


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
