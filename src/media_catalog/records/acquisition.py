from __future__ import annotations

from dataclasses import dataclass

from media_catalog.records.common import (
    _validate_choice,
    _validate_nonempty,
    _validate_opaque_leaf,
    _validate_positive_id,
    normalize_timestamp,
    validate_hash,
    validate_version,
)

ACQUISITION_PLAN_ELIGIBILITIES = frozenset({"eligible", "already_satisfied", "excluded"})
ACQUISITION_RUN_STATUSES = frozenset({"running", "complete", "partial", "failed", "cancelled"})
ACQUISITION_RUN_OUTCOMES = frozenset(
    {
        "success",
        "partial",
        "failed",
        "cancelled",
        "budget_exhausted",
        "interrupted",
        "quarantined",
        "stale",
    }
)
ACQUISITION_ITEM_STATES = frozenset(
    {
        "pending",
        "running",
        "complete",
        "failed",
        "quarantined",
        "stale",
        "deferred",
        "interrupted",
        "satisfied",
    }
)
ACQUISITION_OUTCOMES = frozenset(
    {
        "downloaded",
        "downloaded_exact_only",
        "existing",
        "already_satisfied",
        "policy_failure",
        "authentication_required",
        "authorization_denied",
        "unavailable",
        "rate_limited",
        "transient_provider",
        "timeout",
        "response_too_large",
        "invalid_content",
        "source_changed",
        "interrupted",
        "storage_failure",
        "hash_mismatch",
        "inspection_failure",
        "storage_integrity_failure",
        "stale_target",
        "budget_exhausted",
        "cancelled",
    }
)
ACQUISITION_ATTEMPT_STATES = frozenset({"running", "complete", "failed", "interrupted"})
ACQUISITION_PARTIAL_STATES = frozenset({"active", "discarded", "quarantined", "consumed"})
ACQUISITION_CLAIM_KINDS = frozenset({"sha256", "md5", "file_size", "mime_type", "width", "height"})
ACQUISITION_COMPARISON_RESULTS = frozenset({"matched", "mismatched", "not_comparable"})
ACQUISITION_QUARANTINE_REASONS = frozenset(
    {
        "hash_mismatch",
        "source_changed",
        "invalid_content",
        "unsafe_partial",
        "storage_integrity_failure",
    }
)
ACQUISITION_QUARANTINE_STATES = frozenset({"retained", "missing"})


def validate_acquisition_plan_eligibility(value: str) -> str:
    return _validate_choice(value, ACQUISITION_PLAN_ELIGIBILITIES, "acquisition eligibility")


def validate_acquisition_run_status(value: str) -> str:
    return _validate_choice(value, ACQUISITION_RUN_STATUSES, "acquisition run status")


def validate_acquisition_run_outcome(value: str) -> str:
    return _validate_choice(value, ACQUISITION_RUN_OUTCOMES, "acquisition run outcome")


def validate_acquisition_item_state(value: str) -> str:
    return _validate_choice(value, ACQUISITION_ITEM_STATES, "acquisition item state")


def validate_acquisition_outcome(value: str) -> str:
    return _validate_choice(value, ACQUISITION_OUTCOMES, "acquisition outcome")


def validate_acquisition_attempt_state(value: str) -> str:
    return _validate_choice(value, ACQUISITION_ATTEMPT_STATES, "acquisition attempt state")


def validate_acquisition_partial_state(value: str) -> str:
    return _validate_choice(value, ACQUISITION_PARTIAL_STATES, "acquisition partial state")


def validate_acquisition_claim_kind(value: str) -> str:
    return _validate_choice(value, ACQUISITION_CLAIM_KINDS, "acquisition claim kind")


def validate_acquisition_comparison_result(value: str) -> str:
    return _validate_choice(value, ACQUISITION_COMPARISON_RESULTS, "comparison result")


def validate_acquisition_quarantine_reason(value: str) -> str:
    return _validate_choice(value, ACQUISITION_QUARANTINE_REASONS, "quarantine reason")


def validate_acquisition_quarantine_state(value: str) -> str:
    return _validate_choice(value, ACQUISITION_QUARANTINE_STATES, "quarantine state")


@dataclass(frozen=True, slots=True)
class AcquisitionPlanRecord:
    plan_version: str
    selection_digest: str
    requested_count: int
    eligible_count: int
    satisfied_count: int
    excluded_count: int
    created_at: str

    def __post_init__(self) -> None:
        validate_version(self.plan_version)
        object.__setattr__(self, "selection_digest", validate_hash(self.selection_digest, 64))
        for name in ("requested_count", "eligible_count", "satisfied_count", "excluded_count"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if self.eligible_count + self.satisfied_count + self.excluded_count != self.requested_count:
            raise ValueError("acquisition plan counts must equal requested count")
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))


@dataclass(frozen=True, slots=True)
class AcquisitionPlanItemRecord:
    acquisition_plan_id: int
    item_key: str
    media_occurrence_id: int
    variant_key: str
    material_digest: str
    request_policy_key: str
    request_policy_version: str
    eligibility: str
    created_at: str
    source_raw_observation_id: int | None = None
    exclusion_reason: str | None = None
    satisfied_asset_id: int | None = None
    declared_sha256: str | None = None
    declared_md5: str | None = None
    declared_file_size: int | None = None
    declared_mime_type: str | None = None
    declared_width: int | None = None
    declared_height: int | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.acquisition_plan_id, "acquisition plan id")
        _validate_positive_id(self.media_occurrence_id, "media occurrence id")
        _validate_nonempty(self.item_key, "acquisition item key", max_length=200)
        _validate_nonempty(self.variant_key, "acquisition variant key", max_length=500)
        object.__setattr__(self, "material_digest", validate_hash(self.material_digest, 64))
        _validate_nonempty(self.request_policy_key, "request policy key", max_length=200)
        validate_version(self.request_policy_version)
        validate_acquisition_plan_eligibility(self.eligibility)
        if self.source_raw_observation_id is not None:
            _validate_positive_id(self.source_raw_observation_id, "source raw observation id")
        if self.eligibility == "excluded":
            _validate_nonempty(self.exclusion_reason or "", "exclusion reason", max_length=500)
        elif self.exclusion_reason is not None:
            raise ValueError("only excluded acquisition items may have an exclusion reason")
        if self.eligibility == "already_satisfied":
            if self.satisfied_asset_id is None:
                raise ValueError("already-satisfied acquisition item requires an asset id")
        elif self.satisfied_asset_id is not None:
            raise ValueError("only already-satisfied acquisition items may have an asset id")
        if self.satisfied_asset_id is not None:
            _validate_positive_id(self.satisfied_asset_id, "satisfied asset id")
        object.__setattr__(self, "declared_sha256", validate_hash(self.declared_sha256, 64))
        object.__setattr__(self, "declared_md5", validate_hash(self.declared_md5, 32))
        for name in ("declared_file_size", "declared_width", "declared_height"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.declared_mime_type is not None:
            _validate_nonempty(self.declared_mime_type, "declared MIME type", max_length=500)
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))


@dataclass(frozen=True, slots=True)
class AcquisitionLimits:
    max_items: int
    max_item_bytes: int
    max_total_bytes: int
    max_attempts_per_item: int
    max_seconds: int
    max_redirects: int
    max_quarantine_bytes: int
    concurrency: int = 1

    def __post_init__(self) -> None:
        for name in (
            "max_items",
            "max_item_bytes",
            "max_total_bytes",
            "max_attempts_per_item",
            "max_seconds",
            "max_redirects",
            "concurrency",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_quarantine_bytes < 0:
            raise ValueError("max_quarantine_bytes must not be negative")


@dataclass(frozen=True, slots=True)
class AcquisitionRunRecord:
    acquisition_plan_id: int
    managed_root_id: int
    limits: AcquisitionLimits
    planned_count: int
    started_at: str
    resumed_from_run_id: int | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.acquisition_plan_id, "acquisition plan id")
        _validate_positive_id(self.managed_root_id, "managed root id")
        if self.resumed_from_run_id is not None:
            _validate_positive_id(self.resumed_from_run_id, "resumed acquisition run id")
        if self.planned_count < 0:
            raise ValueError("planned count must not be negative")
        object.__setattr__(self, "started_at", normalize_timestamp(self.started_at))


@dataclass(frozen=True, slots=True)
class AcquisitionRunItemRecord:
    acquisition_run_id: int
    acquisition_plan_item_id: int
    state: str
    created_at: str
    updated_at: str
    outcome: str | None = None
    retryable: bool = False
    attempt_count: int = 0
    received_bytes: int = 0
    asset_id: int | None = None
    sha256: str | None = None
    md5: str | None = None
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.acquisition_run_id, "acquisition run id")
        _validate_positive_id(self.acquisition_plan_item_id, "acquisition plan item id")
        validate_acquisition_item_state(self.state)
        if self.outcome is not None:
            validate_acquisition_outcome(self.outcome)
        if (self.state in {"pending", "running"}) != (self.outcome is None):
            raise ValueError("active acquisition item state and outcome are inconsistent")
        for name in ("attempt_count", "received_bytes"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if self.asset_id is not None:
            _validate_positive_id(self.asset_id, "asset id")
            if self.state not in {"complete", "satisfied"}:
                raise ValueError("only complete acquisition items may reference an asset")
        object.__setattr__(self, "sha256", validate_hash(self.sha256, 64))
        object.__setattr__(self, "md5", validate_hash(self.md5, 32))
        if self.diagnostic is not None:
            _validate_nonempty(self.diagnostic, "acquisition diagnostic", max_length=1000)
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
        object.__setattr__(self, "updated_at", normalize_timestamp(self.updated_at))


@dataclass(frozen=True, slots=True)
class AcquisitionAttemptRecord:
    acquisition_run_item_id: int
    attempt_number: int
    state: str
    request_identity: str
    request_policy_key: str
    request_policy_version: str
    started_at: str
    outcome: str | None = None
    retryable: bool = False
    status_code: int | None = None
    redirect_count: int = 0
    response_etag: str | None = None
    received_bytes: int = 0
    response_size: int | None = None
    retry_after: str | None = None
    diagnostic: str | None = None
    finished_at: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.acquisition_run_item_id, "acquisition run item id")
        if self.attempt_number <= 0:
            raise ValueError("acquisition attempt number must be positive")
        validate_acquisition_attempt_state(self.state)
        if self.outcome is not None:
            validate_acquisition_outcome(self.outcome)
        if self.state == "running":
            if self.outcome is not None or self.finished_at is not None:
                raise ValueError("running acquisition attempt cannot have a terminal outcome")
        elif self.outcome is None or self.finished_at is None:
            raise ValueError("terminal acquisition attempt requires an outcome and finish time")
        object.__setattr__(self, "request_identity", validate_hash(self.request_identity, 64))
        _validate_nonempty(self.request_policy_key, "request policy key", max_length=200)
        validate_version(self.request_policy_version)
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ValueError("HTTP status code must be between 100 and 599")
        for name in ("redirect_count", "received_bytes"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if self.response_size is not None and self.response_size < 0:
            raise ValueError("response size must not be negative")
        if self.response_etag is not None:
            _validate_nonempty(self.response_etag, "response ETag", max_length=1000)
        if self.diagnostic is not None:
            _validate_nonempty(self.diagnostic, "acquisition diagnostic", max_length=1000)
        object.__setattr__(self, "started_at", normalize_timestamp(self.started_at))
        if self.finished_at is not None:
            object.__setattr__(self, "finished_at", normalize_timestamp(self.finished_at))
        if self.retry_after is not None:
            object.__setattr__(self, "retry_after", normalize_timestamp(self.retry_after))


@dataclass(frozen=True, slots=True)
class AcquisitionPartialRecord:
    acquisition_run_item_id: int
    managed_root_id: int
    staging_name: str
    request_identity: str
    byte_count: int
    prefix_sha256: str
    prefix_md5: str
    state: str
    created_at: str
    updated_at: str
    managed_root_identity: str
    staging_device: int
    staging_inode: int
    strong_etag: str | None = None
    acquisition_partial_id: int | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.acquisition_run_item_id, "acquisition run item id")
        _validate_positive_id(self.managed_root_id, "managed root id")
        _validate_nonempty(self.managed_root_identity, "managed root identity", max_length=200)
        if self.staging_device < 0 or self.staging_inode <= 0:
            raise ValueError("partial staging identity is invalid")
        _validate_opaque_leaf(self.staging_name, "staging name")
        object.__setattr__(self, "request_identity", validate_hash(self.request_identity, 64))
        if self.byte_count < 0:
            raise ValueError("partial byte count must not be negative")
        object.__setattr__(self, "prefix_sha256", validate_hash(self.prefix_sha256, 64))
        object.__setattr__(self, "prefix_md5", validate_hash(self.prefix_md5, 32))
        validate_acquisition_partial_state(self.state)
        if self.strong_etag is not None:
            _validate_nonempty(self.strong_etag, "strong ETag", max_length=1000)
            if self.strong_etag.startswith("W/"):
                raise ValueError("partial resume requires a strong ETag")
        if self.acquisition_partial_id is not None:
            _validate_positive_id(self.acquisition_partial_id, "acquisition partial id")
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
        object.__setattr__(self, "updated_at", normalize_timestamp(self.updated_at))


@dataclass(frozen=True, slots=True)
class AcquisitionVerificationRecord:
    acquisition_run_item_id: int
    claim_kind: str
    declared_value: str
    verified_value: str
    comparison_result: str
    created_at: str
    source_raw_observation_id: int | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.acquisition_run_item_id, "acquisition run item id")
        validate_acquisition_claim_kind(self.claim_kind)
        _validate_nonempty(self.declared_value, "declared value", max_length=2000)
        _validate_nonempty(self.verified_value, "verified value", max_length=2000)
        validate_acquisition_comparison_result(self.comparison_result)
        if self.source_raw_observation_id is not None:
            _validate_positive_id(self.source_raw_observation_id, "source raw observation id")
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))


@dataclass(frozen=True, slots=True)
class AcquisitionQuarantineRecord:
    acquisition_run_item_id: int
    managed_root_id: int
    quarantine_name: str
    reason: str
    byte_size: int
    created_at: str
    acquisition_attempt_id: int | None = None
    sha256: str | None = None
    md5: str | None = None
    state: str = "retained"

    def __post_init__(self) -> None:
        _validate_positive_id(self.acquisition_run_item_id, "acquisition run item id")
        _validate_positive_id(self.managed_root_id, "managed root id")
        if self.acquisition_attempt_id is not None:
            _validate_positive_id(self.acquisition_attempt_id, "acquisition attempt id")
        _validate_opaque_leaf(self.quarantine_name, "quarantine name")
        validate_acquisition_quarantine_reason(self.reason)
        if self.byte_size < 0:
            raise ValueError("quarantine byte size must not be negative")
        object.__setattr__(self, "sha256", validate_hash(self.sha256, 64))
        object.__setattr__(self, "md5", validate_hash(self.md5, 32))
        validate_acquisition_quarantine_state(self.state)
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
