from __future__ import annotations

from dataclasses import dataclass

from media_catalog.records.common import (
    _validate_nonempty,
    normalize_timestamp,
    validate_hash,
    validate_native_id,
    validate_platform,
    validate_transport_pair,
)


@dataclass(frozen=True, slots=True)
class RawRecord:
    payload: bytes
    media_type: str
    object_kind: str
    native_id: str | None
    observed_at: str
    source_schema: str | None = None
    status: str | None = None
    platform: str | None = None
    adapter_version: str | None = None
    schema_version: str | None = None
    transport_key: str | None = None
    transport_version: str | None = None

    def __post_init__(self) -> None:
        if not self.payload:
            raise ValueError("raw payload must not be empty")
        if self.platform is not None:
            validate_platform(self.platform)
        if self.adapter_version is not None:
            _validate_nonempty(self.adapter_version, "raw adapter version", max_length=200)
        if self.schema_version is not None:
            _validate_nonempty(self.schema_version, "raw schema version", max_length=200)
        transport_key, transport_version = validate_transport_pair(
            self.transport_key, self.transport_version
        )
        object.__setattr__(self, "transport_key", transport_key)
        object.__setattr__(self, "transport_version", transport_version)
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))


@dataclass(frozen=True, slots=True)
class AccountRecord:
    platform: str
    native_id: str
    observed_at: str
    canonical_url: str | None = None
    availability: str = "available"
    handle: str | None = None
    display_name: str | None = None
    bio: str | None = None
    location: str | None = None
    website_url: str | None = None
    profile_url: str | None = None
    avatar_url: str | None = None
    banner_url: str | None = None
    followers: int | None = None
    following: int | None = None
    verified: bool | None = None
    verification_type: str | None = None

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        validate_native_id(self.native_id)
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))
        for name in ("followers", "following"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class PostRecord:
    platform: str
    native_id: str
    observed_at: str
    canonical_url: str | None = None
    text: str | None = None
    language: str | None = None
    created_at: str | None = None
    availability: str = "available"
    status: str | None = None
    title: str | None = None
    updated_at: str | None = None
    rating: str | None = None
    provider_post_type: str | None = None

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        validate_native_id(self.native_id)
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))
        if self.created_at is not None:
            object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
        if self.updated_at is not None:
            object.__setattr__(self, "updated_at", normalize_timestamp(self.updated_at))
        if self.provider_post_type is not None:
            _validate_nonempty(self.provider_post_type, "provider post type", max_length=200)


@dataclass(frozen=True, slots=True)
class MediaOccurrenceRecord:
    source_key: str
    index: int
    media_type: str
    remote_url: str | None = None
    preview_url: str | None = None
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None
    availability: str = "available"
    declared_md5: str | None = None
    declared_sha256: str | None = None
    duration_ms: int | None = None
    variants_json: str | None = None
    observed_at: str | None = None
    local_path: str | None = None
    role: str | None = None
    mime_type: str | None = None
    declared_file_size: int | None = None

    def __post_init__(self) -> None:
        if not self.source_key:
            raise ValueError("media source key must not be empty")
        if self.index < 0:
            raise ValueError("media index must not be negative")
        for name in ("width", "height", "duration_ms", "declared_file_size"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"media {name} must not be negative")
        object.__setattr__(self, "declared_md5", validate_hash(self.declared_md5, 32))
        object.__setattr__(self, "declared_sha256", validate_hash(self.declared_sha256, 64))
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))
        if self.local_path is not None:
            _validate_nonempty(self.local_path, "media local path")
        for name in ("role", "mime_type"):
            value = getattr(self, name)
            if value is not None:
                _validate_nonempty(value, "media " + name, max_length=200)
