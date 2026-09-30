from __future__ import annotations

import json
from dataclasses import dataclass

from media_catalog.records.common import (
    _validate_nonempty,
    _validate_positive_id,
    normalize_timestamp,
    validate_hash,
    validate_instance,
    validate_library_authority_mode,
    validate_library_estimate_source,
    validate_library_estimate_state,
    validate_library_execution_kind,
    validate_library_probe_outcome,
    validate_library_target_kind,
    validate_platform,
    validate_secret_free_identity,
)


@dataclass(frozen=True, slots=True)
class LibraryExpansionPlanRecord:
    platform: str
    instance_host: str
    target_kind: str
    target_account_id: int | None
    target_attribution_id: int | None
    seed_account_id: int | None
    seed_post_id: int | None
    seed_revision: str
    authority_mode: str
    authority_reference: str | None
    selection_note: str | None
    capability_key: str
    capability_version: str
    target_native_id: str
    target_revision: str
    adapter_version: str
    schema_version: str
    source_revision: str
    request_limit: int
    page_limit: int
    record_limit: int
    time_limit_seconds: int
    estimate_state: str
    estimate_count: int | None
    estimate_observed_at: str | None
    estimate_source: str | None
    exclusions_json: str
    plan_digest: str
    material_digest: str
    created_at: str

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        if self.instance_host:
            object.__setattr__(self, "instance_host", validate_instance(self.instance_host))
        validate_library_target_kind(self.target_kind)
        for value, label in (
            (self.target_account_id, "target account id"),
            (self.target_attribution_id, "target attribution id"),
            (self.seed_account_id, "seed account id"),
            (self.seed_post_id, "seed post id"),
        ):
            if value is not None:
                _validate_positive_id(value, label)
        if not (
            (
                self.target_kind == "account"
                and self.target_account_id is not None
                and self.target_attribution_id is None
            )
            or (
                self.target_kind == "attribution"
                and self.target_attribution_id is not None
                and self.target_account_id is None
            )
        ):
            raise ValueError("library plan requires exactly one typed target matching its kind")
        if (self.seed_account_id is None) == (self.seed_post_id is None):
            raise ValueError("library plan requires exactly one seed")
        _validate_nonempty(self.seed_revision, "seed revision", max_length=200)
        validate_library_authority_mode(self.authority_mode)
        if self.authority_mode == "confirmed":
            if self.authority_reference is None:
                raise ValueError("confirmed library plan requires an authority reference")
            _validate_nonempty(self.authority_reference, "authority reference", max_length=500)
        elif self.authority_reference is not None:
            raise ValueError("explicit library plan must not carry an authority reference")
        if self.selection_note is not None:
            _validate_nonempty(self.selection_note, "selection note", max_length=1000)
        for value, label, max_length in (
            (self.capability_key, "capability key", 200),
            (self.capability_version, "capability version", 200),
            (self.target_native_id, "target native id", 500),
            (self.target_revision, "target revision", 200),
            (self.adapter_version, "adapter version", 200),
            (self.schema_version, "schema version", 200),
            (self.source_revision, "source revision", 200),
        ):
            _validate_nonempty(value, label, max_length=max_length)
        for value, label in (
            (self.request_limit, "request limit"),
            (self.page_limit, "page limit"),
            (self.record_limit, "record limit"),
            (self.time_limit_seconds, "time limit"),
        ):
            _validate_positive_id(value, label)
        validate_library_estimate_state(self.estimate_state)
        if self.estimate_state == "count":
            if (
                self.estimate_count is None
                or self.estimate_observed_at is None
                or self.estimate_source is None
            ):
                raise ValueError("count estimate requires a value, observation time, and source")
            if self.estimate_count < 0:
                raise ValueError("estimate count must not be negative")
            validate_library_estimate_source(self.estimate_source)
            object.__setattr__(
                self,
                "estimate_observed_at",
                normalize_timestamp(self.estimate_observed_at),
            )
        elif (
            self.estimate_count is not None
            or self.estimate_observed_at is not None
            or self.estimate_source is not None
        ):
            raise ValueError("unknown estimate must omit value, observation time, and source")
        if not isinstance(json.loads(self.exclusions_json), list):
            raise ValueError("library plan exclusions must be a JSON array")
        object.__setattr__(self, "plan_digest", validate_hash(self.plan_digest, 64))
        object.__setattr__(self, "material_digest", validate_hash(self.material_digest, 64))
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))


@dataclass(frozen=True, slots=True)
class LibraryExpansionProbeRecord:
    library_expansion_plan_id: int
    capability_key: str
    capability_version: str
    adapter_version: str
    schema_version: str
    request_limit: int
    time_limit_seconds: int
    outcome: str
    requested_at: str
    observed_at: str
    status_code: int | None = None
    count_value: int | None = None
    retry_after: str | None = None
    request_identity: str | None = None
    raw_observation_id: int | None = None
    diagnostic_summary: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.library_expansion_plan_id, "library plan id")
        for value, label in (
            (self.capability_key, "capability key"),
            (self.capability_version, "capability version"),
            (self.adapter_version, "adapter version"),
            (self.schema_version, "schema version"),
        ):
            _validate_nonempty(value, label, max_length=200)
        for value, label in (
            (self.request_limit, "request limit"),
            (self.time_limit_seconds, "time limit"),
        ):
            _validate_positive_id(value, label)
        validate_library_probe_outcome(self.outcome)
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ValueError("probe status code must be a valid HTTP status")
        if self.count_value is not None and self.count_value < 0:
            raise ValueError("probe count must not be negative")
        if (self.outcome == "success") != (self.count_value is not None):
            raise ValueError("a successful probe retains a count and only a successful probe does")
        if self.outcome == "unsupported":
            if (
                self.request_identity is not None
                or self.status_code is not None
                or self.raw_observation_id is not None
            ):
                raise ValueError("unsupported probe makes no request and retains nothing")
        elif self.request_identity is None:
            raise ValueError("a probe request identity is required for a non-unsupported outcome")
        if self.request_identity is not None:
            object.__setattr__(
                self, "request_identity", validate_secret_free_identity(self.request_identity)
            )
        if self.raw_observation_id is not None:
            _validate_positive_id(self.raw_observation_id, "raw observation id")
        if self.retry_after is not None and self.outcome != "rate_limited":
            raise ValueError("retry guidance is only meaningful for a rate-limited probe")
        if self.diagnostic_summary is not None:
            _validate_nonempty(self.diagnostic_summary, "probe diagnostic", max_length=1000)
        object.__setattr__(self, "requested_at", normalize_timestamp(self.requested_at))
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))
        if self.retry_after is not None:
            object.__setattr__(self, "retry_after", normalize_timestamp(self.retry_after))


@dataclass(frozen=True, slots=True)
class LibraryExpansionExecutionRecord:
    library_expansion_plan_id: int
    remote_run_id: int
    execution_kind: str
    created_at: str
    predecessor_execution_id: int | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.library_expansion_plan_id, "library plan id")
        _validate_positive_id(self.remote_run_id, "remote run id")
        validate_library_execution_kind(self.execution_kind)
        if self.predecessor_execution_id is not None:
            _validate_positive_id(self.predecessor_execution_id, "predecessor execution id")
        if (self.execution_kind == "initial") != (self.predecessor_execution_id is None):
            raise ValueError("an initial execution has no predecessor and a resume continues one")
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))


@dataclass(frozen=True, slots=True)
class LibraryExpansionPostRecord:
    library_expansion_execution_id: int
    post_id: int
    observed_at: str
    raw_observation_id: int | None = None
    details_required: bool = False

    def __post_init__(self) -> None:
        _validate_positive_id(self.library_expansion_execution_id, "library execution id")
        _validate_positive_id(self.post_id, "post id")
        if self.raw_observation_id is not None:
            _validate_positive_id(self.raw_observation_id, "raw observation id")
        if not isinstance(self.details_required, bool):
            raise ValueError("library post details flag must be a boolean")
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))
