from __future__ import annotations

import json
from dataclasses import dataclass

from media_catalog.records.common import (
    _validate_nonempty,
    _validate_positive_id,
    normalize_timestamp,
    validate_hash,
    validate_instance,
    validate_library_origin_kind,
    validate_native_id,
    validate_platform,
    validate_remote_operation,
    validate_remote_outcome,
    validate_secret_free_identity,
    validate_transport_pair,
)


@dataclass(frozen=True, slots=True)
class RemoteRunRecord:
    platform: str
    operation: str
    target: str
    adapter_version: str
    schema_version: str
    request_budget: int
    page_budget: int
    record_budget: int
    time_budget_seconds: int
    started_at: str
    instance_host: str = ""
    resumed_from_run_id: int | None = None
    origin_kind: str | None = None
    origin_reference: str | None = None
    transport_key: str | None = None
    transport_version: str | None = None

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        validate_remote_operation(self.operation)
        validate_native_id(self.target)
        _validate_nonempty(self.adapter_version, "remote adapter version", max_length=200)
        _validate_nonempty(self.schema_version, "remote schema version", max_length=200)
        if self.instance_host:
            object.__setattr__(self, "instance_host", validate_instance(self.instance_host))
        for name in (
            "request_budget",
            "page_budget",
            "record_budget",
            "time_budget_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.resumed_from_run_id is not None:
            _validate_positive_id(self.resumed_from_run_id, "resumed run id")
        if (self.origin_kind is None) != (self.origin_reference is None):
            raise ValueError("remote run origin kind and reference must be supplied together")
        if self.origin_kind is not None:
            validate_library_origin_kind(self.origin_kind)
        if self.origin_reference is not None:
            object.__setattr__(self, "origin_reference", validate_hash(self.origin_reference, 64))
        transport_key, transport_version = validate_transport_pair(
            self.transport_key, self.transport_version
        )
        object.__setattr__(self, "transport_key", transport_key)
        object.__setattr__(self, "transport_version", transport_version)
        object.__setattr__(self, "started_at", normalize_timestamp(self.started_at))


@dataclass(frozen=True, slots=True)
class RemoteRequestRecord:
    remote_run_id: int
    attempt_number: int
    request_identity: str
    operation: str
    target: str
    outcome: str
    request_started_at: str
    status_code: int | None = None
    retry_after: str | None = None
    rate_limit_state: str | None = None
    response_adapter_version: str | None = None
    response_schema_version: str | None = None
    object_kind: str | None = None
    native_id: str | None = None
    media_type: str | None = None
    response_size: int | None = None
    response_observed_at: str | None = None
    request_finished_at: str | None = None
    transport_key: str | None = None
    transport_version: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.remote_run_id, "remote run id")
        _validate_positive_id(self.attempt_number, "remote request attempt")
        validate_secret_free_identity(self.request_identity)
        validate_remote_operation(self.operation)
        validate_native_id(self.target)
        validate_remote_outcome(self.outcome)
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ValueError("remote response status must be a valid HTTP status")
        if self.response_size is not None and self.response_size < 0:
            raise ValueError("remote response size must not be negative")
        for name in (
            "response_adapter_version",
            "response_schema_version",
            "object_kind",
            "native_id",
            "media_type",
        ):
            value = getattr(self, name)
            if value is not None:
                _validate_nonempty(value, name.replace("_", " "), max_length=500)
        transport_key, transport_version = validate_transport_pair(
            self.transport_key, self.transport_version
        )
        object.__setattr__(self, "transport_key", transport_key)
        object.__setattr__(self, "transport_version", transport_version)
        object.__setattr__(self, "request_started_at", normalize_timestamp(self.request_started_at))
        for name in ("retry_after", "response_observed_at", "request_finished_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, normalize_timestamp(value))


@dataclass(frozen=True, slots=True)
class RemoteCheckpointRecord:
    remote_run_id: int
    operation: str
    target: str
    continuation_adapter: str
    continuation_version: str
    continuation_json: str
    committed_at: str
    last_page_identity: str | None = None
    page_count: int = 0
    transport_key: str | None = None
    transport_version: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.remote_run_id, "remote run id")
        validate_remote_operation(self.operation)
        validate_native_id(self.target)
        _validate_nonempty(self.continuation_adapter, "continuation adapter", max_length=200)
        _validate_nonempty(self.continuation_version, "continuation version", max_length=200)
        parsed = json.loads(self.continuation_json)
        if not isinstance(parsed, dict):
            raise ValueError("continuation JSON must contain an object")
        if self.last_page_identity is not None:
            validate_secret_free_identity(self.last_page_identity)
        if self.page_count < 0:
            raise ValueError("checkpoint page count must not be negative")
        transport_key, transport_version = validate_transport_pair(
            self.transport_key, self.transport_version
        )
        object.__setattr__(self, "transport_key", transport_key)
        object.__setattr__(self, "transport_version", transport_version)
        object.__setattr__(self, "committed_at", normalize_timestamp(self.committed_at))
