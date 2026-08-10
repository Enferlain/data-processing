"""Stable value types shared by remote metadata adapters.

The contracts deliberately know nothing about HTTP clients or catalog persistence.  A provider
transport returns a :class:`ResponseEnvelope`; normalization turns the retained response into a
page of provider-neutral items.  The synchronization service owns both side effects.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable


class AdapterOperation(StrEnum):
    FETCH_ACCOUNT = "fetch_account"
    FETCH_POST = "fetch_post"
    LIST_ACCOUNT_POSTS = "list_account_posts"
    FETCH_ATTRIBUTION = "fetch_attribution"


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
        return sum(
            item.object_kind in TOP_LEVEL_OBJECT_KINDS for item in self.items
        )


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
