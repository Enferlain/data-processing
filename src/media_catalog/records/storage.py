from __future__ import annotations

from dataclasses import dataclass

from media_catalog.records.common import (
    _validate_nonempty,
    _validate_positive_id,
    normalize_timestamp,
    validate_adoption_outcome,
    validate_adoption_state,
    validate_fingerprint_kind,
    validate_fingerprint_status,
    validate_hash,
    validate_location_kind,
    validate_root_kind,
    validate_source_kind,
    validate_storage_kind,
    validate_version,
)


@dataclass(frozen=True, slots=True)
class AssetRecord:
    sha256: str
    md5: str | None
    phash: str | None
    byte_size: int | None
    storage_kind: str
    storage_path: str | None
    verified_at: str | None
    verification_method: str
    detected_mime_type: str | None = None
    detected_width: int | None = None
    detected_height: int | None = None
    detected_frame_count: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", validate_hash(self.sha256, 64))
        object.__setattr__(self, "md5", validate_hash(self.md5, 32))
        validate_storage_kind(self.storage_kind)
        if self.byte_size is not None and self.byte_size < 0:
            raise ValueError("asset byte size must not be negative")
        for name in ("detected_width", "detected_height", "detected_frame_count"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"asset {name} must not be negative")
        if self.verified_at is not None:
            object.__setattr__(self, "verified_at", normalize_timestamp(self.verified_at))


@dataclass(frozen=True, slots=True)
class ManagedRootRecord:
    root_kind: str
    root_identity: str
    display_label: str
    private_path: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        validate_root_kind(self.root_kind)
        _validate_nonempty(self.root_identity, "root identity", max_length=200)
        _validate_nonempty(self.display_label, "root display label", max_length=200)
        if self.private_path is not None:
            _validate_nonempty(self.private_path, "root private path")
        if self.created_at is not None:
            object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))


@dataclass(frozen=True, slots=True)
class AssetLocationRecord:
    asset_id: int
    managed_root_id: int
    relative_path: str
    location_kind: str = "managed"
    byte_size: int | None = None
    recorded_sha256: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.asset_id, "asset id")
        _validate_positive_id(self.managed_root_id, "managed root id")
        _validate_nonempty(self.relative_path, "asset relative path")
        validate_location_kind(self.location_kind)
        if self.byte_size is not None and self.byte_size < 0:
            raise ValueError("asset location byte size must not be negative")
        object.__setattr__(self, "recorded_sha256", validate_hash(self.recorded_sha256, 64))
        if self.created_at is not None:
            object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))


@dataclass(frozen=True, slots=True)
class OccurrenceSourceRecord:
    media_occurrence_id: int
    source_kind: str
    relative_path: str
    recorded_at: str
    managed_root_id: int | None = None
    source_identity: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.media_occurrence_id, "media occurrence id")
        validate_source_kind(self.source_kind)
        _validate_nonempty(self.relative_path, "occurrence source path")
        if self.managed_root_id is not None:
            _validate_positive_id(self.managed_root_id, "managed root id")
        if self.source_identity is not None:
            _validate_nonempty(self.source_identity, "source identity")
        object.__setattr__(self, "recorded_at", normalize_timestamp(self.recorded_at))


@dataclass(frozen=True, slots=True)
class AssetFingerprintRecord:
    asset_id: int
    fingerprint_kind: str
    fingerprint_value: str
    algorithm: str
    algorithm_version: str
    source: str
    verification_status: str
    observed_at: str

    def __post_init__(self) -> None:
        _validate_positive_id(self.asset_id, "asset id")
        validate_fingerprint_kind(self.fingerprint_kind)
        _validate_nonempty(self.fingerprint_value, "fingerprint value")
        _validate_nonempty(self.algorithm, "fingerprint algorithm")
        validate_version(self.algorithm_version)
        _validate_nonempty(self.source, "fingerprint source", max_length=200)
        validate_fingerprint_status(self.verification_status)
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))


@dataclass(frozen=True, slots=True)
class AdoptionLimits:
    max_bytes: int | None = None
    max_pixels: int | None = None
    max_frames: int | None = None

    def __post_init__(self) -> None:
        for name in ("max_bytes", "max_pixels", "max_frames"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class AdoptionRunRecord:
    managed_root_id: int
    managed_root_identity: str
    algorithm_version: str
    started_at: str
    source_root_id: int | None = None
    source_root_identity: str | None = None
    fingerprint_algorithm: str | None = None
    limits: AdoptionLimits = AdoptionLimits()
    status: str = "running"
    planned_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    finished_at: str | None = None
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.managed_root_id, "managed root id")
        _validate_nonempty(self.managed_root_identity, "managed root identity")
        if self.source_root_id is not None:
            _validate_positive_id(self.source_root_id, "source root id")
        if self.source_root_identity is not None:
            _validate_nonempty(self.source_root_identity, "source root identity")
        validate_version(self.algorithm_version)
        if self.fingerprint_algorithm is not None:
            _validate_nonempty(self.fingerprint_algorithm, "fingerprint algorithm")
        validate_adoption_state(self.status)
        for name in ("planned_count", "completed_count", "failed_count"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        object.__setattr__(self, "started_at", normalize_timestamp(self.started_at))
        if self.finished_at is not None:
            object.__setattr__(self, "finished_at", normalize_timestamp(self.finished_at))
        if self.diagnostic is not None:
            _validate_nonempty(self.diagnostic, "adoption diagnostic", max_length=1000)


@dataclass(frozen=True, slots=True)
class AdoptionItemRecord:
    adoption_run_id: int
    item_key: str
    outcome: str
    media_occurrence_id: int | None = None
    occurrence_source_id: int | None = None
    asset_id: int | None = None
    sha256: str | None = None
    md5: str | None = None
    byte_size: int | None = None
    detected_mime_type: str | None = None
    detected_width: int | None = None
    detected_height: int | None = None
    detected_frame_count: int | None = None
    diagnostic: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.adoption_run_id, "adoption run id")
        _validate_nonempty(self.item_key, "adoption item key", max_length=200)
        validate_adoption_outcome(self.outcome)
        for name in ("media_occurrence_id", "occurrence_source_id", "asset_id"):
            value = getattr(self, name)
            if value is not None:
                _validate_positive_id(value, name.replace("_", " "))
        object.__setattr__(self, "sha256", validate_hash(self.sha256, 64))
        object.__setattr__(self, "md5", validate_hash(self.md5, 32))
        for name in ("byte_size", "detected_width", "detected_height", "detected_frame_count"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.diagnostic is not None:
            _validate_nonempty(self.diagnostic, "adoption diagnostic", max_length=1000)
        for name in ("created_at", "updated_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, normalize_timestamp(value))


@dataclass(frozen=True, slots=True)
class AdoptionAttemptRecord:
    adoption_item_id: int
    attempt_number: int
    outcome: str
    started_at: str
    finished_at: str | None = None
    sha256: str | None = None
    md5: str | None = None
    byte_size: int | None = None
    detected_mime_type: str | None = None
    detected_width: int | None = None
    detected_height: int | None = None
    detected_frame_count: int | None = None
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.adoption_item_id, "adoption item id")
        if self.attempt_number <= 0:
            raise ValueError("adoption attempt number must be positive")
        validate_adoption_outcome(self.outcome)
        object.__setattr__(self, "sha256", validate_hash(self.sha256, 64))
        object.__setattr__(self, "md5", validate_hash(self.md5, 32))
        for name in ("byte_size", "detected_width", "detected_height", "detected_frame_count"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")
        object.__setattr__(self, "started_at", normalize_timestamp(self.started_at))
        if self.finished_at is not None:
            object.__setattr__(self, "finished_at", normalize_timestamp(self.finished_at))
        if self.diagnostic is not None:
            _validate_nonempty(self.diagnostic, "adoption diagnostic", max_length=1000)
