from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

PLATFORM_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
INSTANCE_PATTERN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))+$"
)
VERSION_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*-v[1-9][0-9]*$")
HEX_PATTERN = re.compile(r"^[0-9a-f]+$")
PARTICIPANT_ROLES = frozenset(
    {"author", "uploader", "artist", "creator", "reposter", "commissioner", "source_attributor"}
)
EVENT_TYPES = frozenset({"liked", "bookmarked", "foldered", "imported", "discovered", "crawled"})
SOURCE_CONTEXTS = frozenset(
    {
        "account.website",
        "account.profile",
        "account.bio",
        "post.canonical",
        "post.text",
        "post.entity",
        "post.card",
        "post.quote",
        "post.source",
    }
)
OBJECT_KINDS = frozenset({"account", "post", "artist", "media_asset"})
ACCOUNT_RELATIONS = frozenset({"same_identity", "officially_linked"})
POST_RELATIONS = frozenset(
    {"sourced_from", "same_work", "repost_of", "variant_of", "derived_from", "unresolved"}
)
EVIDENCE_STANCES = frozenset({"supports", "contradicts", "neutral"})
EVIDENCE_STRENGTHS = frozenset({"weak", "moderate", "strong", "exact"})
REVIEW_STATES = frozenset({"pending", "confirmed", "rejected"})
EVIDENCE_DIRECTIONS = frozenset({"subject_to_target", "symmetric", "none"})


def validate_platform(value: str) -> str:
    if not PLATFORM_PATTERN.fullmatch(value):
        raise ValueError(f"invalid platform key: {value!r}")
    return value


def validate_native_id(value: str) -> str:
    if not value or value.strip() != value:
        raise ValueError("native identifier must be non-empty and have no surrounding whitespace")
    return value


def _validate_choice(value: str, choices: frozenset[str], label: str) -> str:
    if value not in choices:
        raise ValueError(f"unsupported {label}: {value}")
    return value


def validate_source_context(value: str) -> str:
    return _validate_choice(value, SOURCE_CONTEXTS, "source context")


def validate_instance(value: str) -> str:
    normalized = value.lower().rstrip(".")
    if not INSTANCE_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid platform instance hostname: {value!r}")
    return normalized


def validate_object_kind(value: str) -> str:
    return _validate_choice(value, OBJECT_KINDS, "object kind")


def validate_relation(value: str, *, candidate_kind: str) -> str:
    choices = ACCOUNT_RELATIONS if candidate_kind == "account" else POST_RELATIONS
    return _validate_choice(value, choices, f"{candidate_kind} relation")


def validate_evidence_stance(value: str) -> str:
    return _validate_choice(value, EVIDENCE_STANCES, "evidence stance")


def validate_evidence_strength(value: str) -> str:
    return _validate_choice(value, EVIDENCE_STRENGTHS, "evidence strength")


def validate_evidence_direction(value: str) -> str:
    return _validate_choice(value, EVIDENCE_DIRECTIONS, "evidence direction")


def validate_review_state(value: str) -> str:
    return _validate_choice(value, REVIEW_STATES, "review state")


def validate_version(value: str) -> str:
    if not VERSION_PATTERN.fullmatch(value):
        raise ValueError(f"invalid algorithm version: {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class LinkOccurrence:
    subject_kind: str
    subject_id: int
    source_context: str
    original_url: str
    observed_at: str
    account_snapshot_id: int | None = None
    raw_observation_id: int | None = None
    json_path: str | None = None

    def __post_init__(self) -> None:
        if self.subject_kind not in {"account", "post"}:
            raise ValueError(f"unsupported link subject kind: {self.subject_kind}")
        if self.subject_id <= 0:
            raise ValueError("link subject id must be positive")
        validate_source_context(self.source_context)
        if not self.original_url:
            raise ValueError("link URL must not be empty")
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))


@dataclass(frozen=True, slots=True)
class PlatformReferenceRecord:
    platform: str
    instance_host: str
    object_kind: str
    native_id: str
    canonical_url: str
    recognizer: str
    recognizer_version: str

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        if self.instance_host:
            object.__setattr__(self, "instance_host", validate_instance(self.instance_host))
        validate_object_kind(self.object_kind)
        validate_native_id(self.native_id)
        validate_version(self.recognizer_version)


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    candidate_kind: str
    relation_kind: str
    review_state: str
    score: int
    scoring_version: str

    def __post_init__(self) -> None:
        if self.candidate_kind not in {"account", "post"}:
            raise ValueError(f"unsupported candidate kind: {self.candidate_kind}")
        validate_relation(self.relation_kind, candidate_kind=self.candidate_kind)
        validate_review_state(self.review_state)
        validate_version(self.scoring_version)


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    stance: str
    strength: str
    direction: str
    detector: str
    detector_version: str
    explanation: str

    def __post_init__(self) -> None:
        validate_evidence_stance(self.stance)
        validate_evidence_strength(self.strength)
        validate_evidence_direction(self.direction)
        validate_version(self.detector_version)
        if not self.detector or not self.explanation:
            raise ValueError("evidence detector and explanation must not be empty")


@dataclass(frozen=True, slots=True)
class ReviewDecisionRecord:
    state: str
    evidence_generation: int
    decided_at: str
    note: str | None = None

    def __post_init__(self) -> None:
        validate_review_state(self.state)
        if self.evidence_generation < 0:
            raise ValueError("evidence generation must not be negative")
        object.__setattr__(self, "decided_at", normalize_timestamp(self.decided_at))


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
