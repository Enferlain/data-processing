"""Stable value types shared by remote metadata adapters.

The contracts deliberately know nothing about HTTP clients or catalog persistence.  A provider
transport returns a :class:`ResponseEnvelope`; normalization turns the retained response into a
page of provider-neutral items.  The synchronization service owns both side effects.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable


class AdapterOperation(StrEnum):
    FETCH_ACCOUNT = "fetch_account"
    FETCH_POST = "fetch_post"
    LIST_ACCOUNT_POSTS = "list_account_posts"
    FETCH_ATTRIBUTION = "fetch_attribution"


class LookupStrategy(StrEnum):
    """Closed, versioned vocabulary for reverse metadata lookups."""

    SOURCE_POST_URL = "source_post_url"
    EXTERNAL_POST_ID = "external_post_id"
    DECLARED_MD5 = "declared_md5"
    VERIFIED_MD5 = "verified_md5"
    ARTIST_EXACT_NAME = "artist_exact_name"
    ARTIST_ALIAS = "artist_alias"
    ARTIST_TEXT = "artist_text"


LOOKUP_STRATEGY_VERSION = "lookup-v1"
_MD5_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_MAX_LOOKUP_TEXT = 200


def _lookup_values(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    else:
        if not isinstance(value, Iterable):
            raise TypeError(f"{name} must be text or a sequence of text")
        values = tuple(value)
    if not values or not all(isinstance(item, str) and item.strip() for item in values):
        raise ValueError(f"{name} must contain non-empty text")
    return tuple(item.strip() for item in values)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class LookupQueryMaterial:
    """Private query material retained by an adapter, represented publicly by its digest."""

    strategy: LookupStrategy
    values: tuple[str, ...]
    platform: str | None
    provenance_kind: str | None
    provenance_id: str | None

    def __init__(
        self,
        strategy: LookupStrategy | str | None = None,
        value: str | tuple[str, ...] | list[str] | None = None,
        provenance_kind: str | None = None,
        provenance_id: str | None = None,
        *,
        values: tuple[str, ...] | list[str] | None = None,
        platform: str | None = None,
        kind: LookupStrategy | str | None = None,
    ) -> None:
        if strategy is None:
            strategy = kind
        elif kind is not None and LookupStrategy(strategy) is not LookupStrategy(kind):
            raise ValueError("lookup query material strategy and kind do not match")
        if strategy is None:
            raise TypeError("lookup query material requires a strategy or kind")
        strategy = LookupStrategy(strategy)
        if value is not None and values is not None:
            raise TypeError("provide value or values, not both")
        raw = value if value is not None else values
        if raw is None:
            raise TypeError("lookup query material requires a value")
        normalized = _lookup_values(raw, "lookup query material")
        if strategy is not LookupStrategy.SOURCE_POST_URL and len(normalized) != 1:
            raise ValueError(f"{strategy.value} accepts exactly one query value")
        if strategy in {LookupStrategy.DECLARED_MD5, LookupStrategy.VERIFIED_MD5}:
            if not _MD5_RE.fullmatch(normalized[0]):
                raise ValueError("lookup MD5 must be exactly 32 hexadecimal characters")
            normalized = (normalized[0].lower(),)
        for item in normalized:
            if any(ord(char) < 32 for char in item):
                raise ValueError("lookup query material contains control characters")
            if len(item) > _MAX_LOOKUP_TEXT:
                raise ValueError(f"lookup query material exceeds {_MAX_LOOKUP_TEXT} characters")
        if platform is not None:
            platform = _nonempty(platform, "lookup external platform")
        if provenance_kind is not None:
            provenance_kind = _nonempty(provenance_kind, "lookup provenance kind")
        if provenance_id is not None:
            provenance_id = _nonempty(provenance_id, "lookup provenance id")
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(self, "values", normalized)
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "provenance_kind", provenance_kind)
        object.__setattr__(self, "provenance_id", provenance_id)

    @property
    def kind(self) -> str:
        return self.strategy.value

    @property
    def value(self) -> str:
        """Return the sole value for scalar strategies."""

        if len(self.values) != 1:
            raise ValueError("this lookup material contains aliases; use values")
        return self.values[0]

    @property
    def digest(self) -> str:
        payload = {
            "platform": self.platform,
            "provenance_id": self.provenance_id,
            "provenance_kind": self.provenance_kind,
            "strategy": self.strategy.value,
            "values": self.values,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        """Serialize private material for internal persistence and resume."""

        return json.dumps(
            {
                "platform": self.platform,
                "provenance_id": self.provenance_id,
                "provenance_kind": self.provenance_kind,
                "strategy": self.strategy.value,
                "values": self.values,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, value: str) -> LookupQueryMaterial:
        payload = json.loads(value)
        if not isinstance(payload, dict) or not isinstance(payload.get("values"), list):
            raise ValueError("invalid lookup query material")
        return cls(
            LookupStrategy(payload.get("strategy", "")),
            values=payload["values"],
            platform=payload.get("platform"),
            provenance_kind=payload.get("provenance_kind"),
            provenance_id=payload.get("provenance_id"),
        )

    @property
    def material_digest(self) -> str:
        return self.digest

    def as_dict(self, *, include_values: bool = False) -> dict[str, Any]:
        """Return a public-safe description unless private values are explicitly requested."""

        result: dict[str, Any] = {
            "kind": self.kind,
            "material_digest": self.digest,
            "platform": self.platform,
            "provenance_kind": self.provenance_kind,
            "provenance_id": self.provenance_id,
        }
        if include_values:
            result["values"] = list(self.values)
        return result

    def __repr__(self) -> str:
        return (
            "LookupQueryMaterial("
            f"strategy={self.strategy.value!r}, digest={self.digest!r}, "
            f"value_count={len(self.values)})"
        )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class LookupContinuation:
    """Opaque, versioned cursor for one lookup material and provider instance."""

    adapter: str
    version: str
    strategy: LookupStrategy
    query_digest: str
    page: str | None = None
    alias_index: int = 0

    def __init__(
        self,
        adapter: str,
        version: str,
        strategy: LookupStrategy | str | Mapping[str, Any],
        query_digest: str | None = None,
        page: str | None = None,
        alias_index: int = 0,
    ) -> None:
        if isinstance(strategy, Mapping):
            value = dict(strategy)
            raw_strategy = value.get("strategy", LookupStrategy.SOURCE_POST_URL.value)
            raw_digest = value.get("query_digest")
            if query_digest is None:
                query_digest = str(raw_digest) if raw_digest is not None else None
            if page is None:
                page = value.get("page")
            alias_index = int(value.get("alias_index", alias_index))
            strategy = raw_strategy
        if query_digest is None:
            query_digest = hashlib.sha256(
                json.dumps(
                    {"page": page, "strategy": str(strategy), "alias_index": alias_index},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        object.__setattr__(self, "adapter", adapter)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "strategy", LookupStrategy(strategy))
        object.__setattr__(self, "query_digest", query_digest)
        object.__setattr__(self, "page", page)
        object.__setattr__(self, "alias_index", alias_index)
        self.__post_init__()

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter", _nonempty(self.adapter, "lookup continuation adapter"))
        object.__setattr__(self, "version", _nonempty(self.version, "lookup continuation version"))
        object.__setattr__(self, "strategy", LookupStrategy(self.strategy))
        if not re.fullmatch(r"[0-9a-f]{64}", self.query_digest):
            raise ValueError("lookup continuation query digest must be a SHA-256 hex digest")
        if self.page is not None:
            object.__setattr__(self, "page", _nonempty(self.page, "lookup continuation page"))
        if self.alias_index < 0:
            raise ValueError("lookup continuation alias index must not be negative")

    def to_json(self) -> str:
        return json.dumps(
            {
                "adapter": self.adapter,
                "alias_index": self.alias_index,
                "page": self.page,
                "query_digest": self.query_digest,
                "strategy": self.strategy.value,
                "version": self.version,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def value(self) -> Mapping[str, Any]:
        return {
            "alias_index": self.alias_index,
            "page": self.page,
            "query_digest": self.query_digest,
            "strategy": self.strategy.value,
        }

    @classmethod
    def from_json(cls, value: str) -> LookupContinuation:
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise ValueError("invalid lookup continuation payload")
        return cls(
            str(payload.get("adapter", "")),
            str(payload.get("version", "")),
            LookupStrategy(payload.get("strategy", "")),
            str(payload.get("query_digest", "")),
            payload.get("page"),
            int(payload.get("alias_index", 0)),
        )

    def __repr__(self) -> str:
        return (
            "LookupContinuation("
            f"adapter={self.adapter!r}, version={self.version!r}, "
            f"strategy={self.strategy.value!r}, query_digest={self.query_digest!r}, "
            f"page={self.page!r}, alias_index={self.alias_index})"
        )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class LookupRequest:
    """A typed lookup request; callers cannot provide endpoints or arbitrary parameters."""

    strategy: LookupStrategy
    material: LookupQueryMaterial
    continuation: LookupContinuation | None
    limit: int

    def __init__(
        self,
        strategy: LookupStrategy | str,
        material: LookupQueryMaterial | str | tuple[str, ...] | list[str] | None = None,
        continuation: LookupContinuation | None = None,
        limit: int = 200,
        *,
        query_material: LookupQueryMaterial | None = None,
        platform: str | None = None,
    ) -> None:
        strategy = LookupStrategy(strategy)
        if query_material is not None:
            if material not in (None, ""):
                raise TypeError("query_material cannot be combined with material")
            material = query_material
        if material is None:
            raise TypeError("lookup request requires query material")
        if isinstance(material, LookupQueryMaterial):
            if material.strategy is not strategy:
                raise ValueError("lookup request strategy does not match query material")
            query = material
        else:
            query = LookupQueryMaterial(strategy, material, platform=platform)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 0 < limit <= 200:
            raise ValueError("lookup request limit must be between 1 and 200")
        if continuation is not None and not isinstance(continuation, LookupContinuation):
            raise TypeError("lookup request continuation must be a LookupContinuation")
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(self, "material", query)
        object.__setattr__(self, "continuation", continuation)
        object.__setattr__(self, "limit", limit)

    @property
    def query_material(self) -> LookupQueryMaterial:
        return self.material

    @property
    def query(self) -> LookupQueryMaterial:
        return self.material

    @property
    def operation(self) -> AdapterOperation:
        if self.strategy in {
            LookupStrategy.ARTIST_EXACT_NAME,
            LookupStrategy.ARTIST_ALIAS,
            LookupStrategy.ARTIST_TEXT,
        }:
            return AdapterOperation.FETCH_ATTRIBUTION
        return AdapterOperation.FETCH_POST

    def __repr__(self) -> str:
        return (
            "LookupRequest("
            f"strategy={self.strategy.value!r}, query_digest={self.material.digest!r}, "
            f"continuation={self.continuation!r}, limit={self.limit})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class LookupCapability:
    strategy: LookupStrategy
    result_kind: str
    pagination: str = "keyset"
    max_page_size: int = 200

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy", LookupStrategy(self.strategy))
        object.__setattr__(self, "result_kind", _nonempty(self.result_kind, "lookup result kind"))
        object.__setattr__(self, "pagination", _nonempty(self.pagination, "lookup pagination"))
        if not isinstance(self.max_page_size, int) or not 0 < self.max_page_size <= 200:
            raise ValueError("lookup capability page size must be between 1 and 200")

    def __repr__(self) -> str:
        return (
            "LookupCapability("
            f"strategy={self.strategy.value!r}, result_kind={self.result_kind!r}, "
            f"pagination={self.pagination!r}, max_page_size={self.max_page_size})"
        )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class LookupCapabilities:
    declarations: tuple[LookupCapability, ...]

    def __init__(
        self,
        declarations: tuple[LookupCapability, ...] | frozenset[LookupStrategy] | None = None,
        *,
        strategies: tuple[LookupStrategy, ...] | frozenset[LookupStrategy] | None = None,
    ) -> None:
        if declarations is not None and strategies is not None:
            raise TypeError("provide declarations or strategies, not both")
        raw = declarations if declarations is not None else strategies or ()
        normalized: list[LookupCapability] = []
        for item in raw:
            if isinstance(item, LookupCapability):
                normalized.append(item)
                continue
            strategy = LookupStrategy(item)
            normalized.append(
                LookupCapability(
                    strategy,
                    "attribution" if strategy.value.startswith("artist_") else "post",
                )
            )
        object.__setattr__(self, "declarations", tuple(normalized))
        self.__post_init__()

    def __post_init__(self) -> None:
        declarations = tuple(self.declarations)
        if len({item.strategy for item in declarations}) != len(declarations):
            raise ValueError("lookup capability strategies must be unique")
        object.__setattr__(self, "declarations", declarations)

    @property
    def strategies(self) -> frozenset[LookupStrategy]:
        return frozenset(item.strategy for item in self.declarations)

    def supports(self, strategy: LookupStrategy | str) -> bool:
        return LookupStrategy(strategy) in self.strategies

    def __contains__(self, strategy: object) -> bool:
        if not isinstance(strategy, (LookupStrategy, str)):
            return False
        try:
            return self.supports(strategy)
        except (TypeError, ValueError):
            return False

    def __iter__(self) -> Iterator[LookupStrategy]:
        return iter(sorted(self.strategies, key=str))

    def as_dict(self) -> dict[str, dict[str, object]]:
        return {
            declaration.strategy.value: {
                "max_page_size": declaration.max_page_size,
                "pagination": declaration.pagination,
                "result_kind": declaration.result_kind,
            }
            for declaration in sorted(self.declarations, key=lambda item: item.strategy.value)
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))

    def __repr__(self) -> str:
        return f"LookupCapabilities(strategies={sorted(item.value for item in self.strategies)!r})"


@dataclass(frozen=True, slots=True)
class EnumerationCapability:
    """A provider's closed declaration for enumerating one stable target kind."""

    target_kind: str
    operation: AdapterOperation
    version: str
    count_probe_key: str | None = None

    def __post_init__(self) -> None:
        if self.target_kind not in {"account", "attribution"}:
            raise ValueError("enumeration target kind must be account or attribution")
        if self.operation is not AdapterOperation.LIST_ACCOUNT_POSTS:
            raise ValueError("enumeration capability must use the bounded listing operation")
        object.__setattr__(self, "version", _nonempty(self.version, "capability version"))
        if self.count_probe_key is not None:
            object.__setattr__(
                self,
                "count_probe_key",
                _nonempty(self.count_probe_key, "count probe key"),
            )


@dataclass(frozen=True, slots=True)
class EnumerationCapabilities:
    declarations: tuple[EnumerationCapability, ...] = ()

    def __post_init__(self) -> None:
        if len({item.target_kind for item in self.declarations}) != len(self.declarations):
            raise ValueError("enumeration target kinds must be unique")

    def for_target(self, target_kind: str) -> EnumerationCapability | None:
        return next(
            (item for item in self.declarations if item.target_kind == target_kind),
            None,
        )

    def supports(self, target_kind: str) -> bool:
        return self.for_target(target_kind) is not None


@dataclass(frozen=True, slots=True, repr=False)
class LookupPlanItem:
    """Redacted, stable plan item; private material is deliberately excluded from repr/JSON."""

    provider: str
    instance: str
    strategy: LookupStrategy
    query_digest: str
    limits: Mapping[str, int]
    seed_kind: str = ""
    seed_id: str = ""
    strategy_version: str = LOOKUP_STRATEGY_VERSION
    adapter_version: str = ""
    schema_version: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _nonempty(self.provider, "lookup plan provider"))
        object.__setattr__(self, "instance", _nonempty(self.instance, "lookup plan instance"))
        object.__setattr__(self, "strategy", LookupStrategy(self.strategy))
        if not re.fullmatch(r"[0-9a-f]{64}", self.query_digest):
            raise ValueError("lookup plan query digest must be a SHA-256 hex digest")
        copied = dict(self.limits)
        if not copied or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in copied.values()
        ):
            raise ValueError("lookup plan limits must be positive integers")
        object.__setattr__(self, "limits", MappingProxyType(copied))
        for name in (
            "seed_kind",
            "seed_id",
            "strategy_version",
            "adapter_version",
            "schema_version",
        ):
            value = getattr(self, name)
            if value:
                object.__setattr__(self, name, _nonempty(value, name))

    @property
    def digest(self) -> str:
        payload = {
            "adapter_version": self.adapter_version,
            "instance": self.instance,
            "limits": dict(self.limits),
            "provider": self.provider,
            "query_digest": self.query_digest,
            "schema_version": self.schema_version,
            "seed_id": self.seed_id,
            "seed_kind": self.seed_kind,
            "strategy": self.strategy.value,
            "strategy_version": self.strategy_version,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        return json.dumps(
            {
                "adapter_version": self.adapter_version,
                "digest": self.digest,
                "instance": self.instance,
                "limits": dict(self.limits),
                "provider": self.provider,
                "query_digest": self.query_digest,
                "schema_version": self.schema_version,
                "seed_id": self.seed_id,
                "seed_kind": self.seed_kind,
                "strategy": self.strategy.value,
                "strategy_version": self.strategy_version,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def __repr__(self) -> str:
        return (
            "LookupPlanItem("
            f"provider={self.provider!r}, instance={self.instance!r}, "
            f"strategy={self.strategy.value!r}, query_digest={self.query_digest!r}, "
            f"digest={self.digest!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class NormalizedLookupResult:
    result_kind: str
    native_id: str | None
    data: Mapping[str, Any]
    rank: int = 0
    items: tuple[NormalizedItem, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_kind", _nonempty(self.result_kind, "lookup result kind"))
        if self.native_id is not None:
            object.__setattr__(
                self, "native_id", _nonempty(self.native_id, "lookup result native id")
            )
        if self.result_kind not in {"post", "attribution", "lead"}:
            raise ValueError("lookup result kind must be post, attribution, or lead")
        if self.rank < 0:
            raise ValueError("lookup result rank must not be negative")
        copied = dict(self.data)
        json.dumps(copied, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        object.__setattr__(self, "data", MappingProxyType(copied))
        object.__setattr__(self, "items", tuple(self.items))

    @property
    def provider_id(self) -> str | None:
        return self.native_id

    @property
    def order(self) -> int:
        return self.rank

    def __repr__(self) -> str:
        return (
            "NormalizedLookupResult("
            f"result_kind={self.result_kind!r}, native_id={self.native_id!r}, rank={self.rank})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class NormalizedLookupPage:
    results: tuple[NormalizedLookupResult, ...]
    continuation: LookupContinuation | None = None
    record_count: int | None = None

    def __post_init__(self) -> None:
        results = tuple(self.results)
        object.__setattr__(self, "results", results)
        if self.record_count is None:
            object.__setattr__(self, "record_count", len(results))
        elif self.record_count < 0:
            raise ValueError("lookup page record count must not be negative")

    @property
    def items(self) -> tuple[NormalizedItem, ...]:
        return tuple(item for result in self.results for item in result.items)

    def __repr__(self) -> str:
        return (
            "NormalizedLookupPage("
            f"results={len(self.results)}, continuation={self.continuation!r}, "
            f"record_count={self.record_count})"
        )


class AdapterOutcome(StrEnum):
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    DELETED = "deleted"
    AUTHENTICATION_REQUIRED = "authentication_required"
    AUTHORIZATION_DENIED = "authorization_denied"
    RATE_LIMITED = "rate_limited"
    TRANSIENT_PROVIDER = "transient_provider"
    MALFORMED_RESPONSE = "malformed_response"
    BUDGET_EXHAUSTED = "budget_exhausted"
    LOCAL_PERSISTENCE = "local_persistence"


TOP_LEVEL_OBJECT_KINDS = frozenset({"account", "post", "attribution"})


def _nonempty(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _public_headers(headers: Mapping[str, str]) -> Mapping[str, str]:
    result: dict[str, str] = {}
    for name, value in headers.items():
        lowered = name.strip().lower()
        if lowered in {"authorization", "cookie", "proxy-authorization", "set-cookie"}:
            raise ValueError(f"secret-bearing header is not allowed in an envelope: {lowered}")
        result[lowered] = str(value)
    return MappingProxyType(result)


def _secret_free_identity(value: str) -> str:
    value = _nonempty(value, "request identity")
    lowered = value.lower()
    forbidden = (
        "access_token=",
        "refresh_token=",
        "api_key=",
        "apikey=",
        "authorization=",
        "cookie=",
    )
    if any(marker in lowered for marker in forbidden):
        raise ValueError("request identity contains a secret-bearing parameter")
    return value


@dataclass(frozen=True, slots=True)
class Continuation:
    adapter: str
    version: str
    value: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter", _nonempty(self.adapter, "continuation adapter"))
        object.__setattr__(self, "version", _nonempty(self.version, "continuation version"))
        copied = dict(self.value)
        json.dumps(copied, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        object.__setattr__(self, "value", MappingProxyType(copied))

    def to_json(self) -> str:
        return json.dumps(
            {"adapter": self.adapter, "version": self.version, "value": dict(self.value)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, value: str) -> Continuation:
        payload = json.loads(value)
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), dict):
            raise ValueError("invalid continuation payload")
        return cls(
            str(payload.get("adapter", "")),
            str(payload.get("version", "")),
            payload["value"],
        )


@dataclass(frozen=True, slots=True)
class AdapterRequest:
    operation: AdapterOperation
    target: str
    continuation: Continuation | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", _nonempty(self.target, "adapter target"))


@dataclass(frozen=True, slots=True)
class ResponseEnvelope:
    provider: str
    instance: str
    operation: AdapterOperation
    request_identity: str
    status_code: int
    headers: Mapping[str, str]
    payload: bytes
    observed_at: str
    adapter_version: str
    schema_version: str
    lookup_strategy: LookupStrategy | None = None
    lookup_query_digest: str | None = None
    lookup_continuation: LookupContinuation | None = field(default=None, repr=False)
    lookup_material: LookupQueryMaterial | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _nonempty(self.provider, "provider"))
        object.__setattr__(self, "instance", _nonempty(self.instance, "instance"))
        object.__setattr__(self, "request_identity", _secret_free_identity(self.request_identity))
        if not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be a valid HTTP status")
        object.__setattr__(self, "headers", _public_headers(self.headers))
        if not self.payload:
            raise ValueError("response payload must not be empty")
        object.__setattr__(self, "observed_at", _timestamp(self.observed_at))
        object.__setattr__(
            self, "adapter_version", _nonempty(self.adapter_version, "adapter version")
        )
        object.__setattr__(self, "schema_version", _nonempty(self.schema_version, "schema version"))
        if self.lookup_strategy is not None:
            object.__setattr__(self, "lookup_strategy", LookupStrategy(self.lookup_strategy))
            if not isinstance(self.lookup_query_digest, str) or not re.fullmatch(
                r"[0-9a-f]{64}", self.lookup_query_digest
            ):
                raise ValueError("lookup response query digest must be a SHA-256 hex digest")
            if (
                self.lookup_material is not None
                and self.lookup_material.strategy is not self.lookup_strategy
            ):
                raise ValueError("lookup response material does not match its strategy")
        elif any(
            value is not None
            for value in (self.lookup_query_digest, self.lookup_continuation, self.lookup_material)
        ):
            raise ValueError("lookup response metadata requires a lookup strategy")


@dataclass(frozen=True, slots=True)
class NormalizedItem:
    object_kind: str
    native_id: str | None
    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "object_kind", _nonempty(self.object_kind, "object kind"))
        if self.native_id is not None:
            object.__setattr__(self, "native_id", _nonempty(self.native_id, "native id"))
        copied = dict(self.data)
        json.dumps(copied, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        object.__setattr__(self, "data", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class NormalizedPage:
    items: tuple[NormalizedItem, ...]
    continuation: Continuation | None = None

    @property
    def record_count(self) -> int:
        return sum(item.object_kind in TOP_LEVEL_OBJECT_KINDS for item in self.items)


class AdapterFailure(Exception):
    """A provider failure with a bounded, public diagnostic."""

    def __init__(
        self,
        outcome: AdapterOutcome,
        message: str,
        *,
        status_code: int | None = None,
        retry_at: str | None = None,
    ) -> None:
        self.outcome = outcome
        self.public_message = _nonempty(message, "failure message")[:1000]
        self.status_code = status_code
        self.retry_at = _timestamp(retry_at) if retry_at is not None else None
        super().__init__(self.public_message)


@runtime_checkable
class Adapter(Protocol):
    provider_key: str
    instance_key: str
    adapter_version: str
    schema_version: str

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope: ...

    def normalize(self, response: ResponseEnvelope) -> NormalizedPage: ...


@runtime_checkable
class LookupAdapter(Protocol):
    """Protocol implemented by adapters that expose bounded reverse lookup."""

    provider_key: str
    instance_key: str
    adapter_version: str
    schema_version: str

    @property
    def lookup_capabilities(self) -> LookupCapabilities: ...

    instance: Any

    def fetch_lookup(self, request: LookupRequest) -> ResponseEnvelope: ...

    def normalize_lookup(
        self, response: ResponseEnvelope, request: LookupRequest | None = None
    ) -> NormalizedLookupPage: ...
