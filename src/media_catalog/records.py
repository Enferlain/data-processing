from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

PLATFORM_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
HEX_PATTERN = re.compile(r"^[0-9a-f]+$")
PARTICIPANT_ROLES = frozenset(
    {"author", "uploader", "artist", "creator", "reposter", "commissioner", "source_attributor"}
)
EVENT_TYPES = frozenset({"liked", "bookmarked", "foldered", "imported", "discovered", "crawled"})


def validate_platform(value: str) -> str:
    if not PLATFORM_PATTERN.fullmatch(value):
        raise ValueError(f"invalid platform key: {value!r}")
    return value


def validate_native_id(value: str) -> str:
    if not value or value.strip() != value:
        raise ValueError("native identifier must be non-empty and have no surrounding whitespace")
    return value


def normalize_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid ISO-8601 timestamp: {value!r}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a UTC offset: {value!r}")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def validate_hash(value: str | None, length: int) -> str | None:
    if value is None:
        return None
    normalized = value.lower()
    if len(normalized) != length or not HEX_PATTERN.fullmatch(normalized):
        raise ValueError(f"expected a {length}-character hexadecimal hash")
    return normalized


@dataclass(frozen=True, slots=True)
class RawRecord:
    payload: bytes
    media_type: str
    object_kind: str
    native_id: str | None
    observed_at: str
    source_schema: str | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if not self.payload:
            raise ValueError("raw payload must not be empty")
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

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        validate_native_id(self.native_id)
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))
        if self.created_at is not None:
            object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))


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

    def __post_init__(self) -> None:
        if not self.source_key:
            raise ValueError("media source key must not be empty")
        if self.index < 0:
            raise ValueError("media index must not be negative")
        for name in ("width", "height", "duration_ms"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"media {name} must not be negative")
        object.__setattr__(self, "declared_md5", validate_hash(self.declared_md5, 32))
        object.__setattr__(self, "declared_sha256", validate_hash(self.declared_sha256, 64))
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", validate_hash(self.sha256, 64))
        object.__setattr__(self, "md5", validate_hash(self.md5, 32))
        if self.byte_size is not None and self.byte_size < 0:
            raise ValueError("asset byte size must not be negative")
        if self.verified_at is not None:
            object.__setattr__(self, "verified_at", normalize_timestamp(self.verified_at))


def validate_role(role: str) -> str:
    if role not in PARTICIPANT_ROLES:
        raise ValueError(f"unsupported participant role: {role}")
    return role


def validate_event_type(event_type: str) -> str:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported observation event type: {event_type}")
    return event_type
