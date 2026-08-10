from __future__ import annotations

import json
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
IDENTIFIER_KINDS = frozenset({"stable_id", "handle", "slug", "hash", "opaque"})
ACCOUNT_RELATIONS = frozenset({"same_identity", "officially_linked"})
POST_RELATIONS = frozenset(
    {
        "sourced_from",
        "same_work",
        "repost_of",
        "variant_of",
        "derived_from",
        "parent_of",
        "quote",
        "reply",
        "unresolved",
    }
)
EVIDENCE_STANCES = frozenset({"supports", "contradicts", "neutral"})
EVIDENCE_STRENGTHS = frozenset({"weak", "moderate", "strong", "exact"})
REVIEW_STATES = frozenset({"pending", "confirmed", "rejected"})
EVIDENCE_DIRECTIONS = frozenset({"subject_to_target", "symmetric", "none"})
STORAGE_KINDS = frozenset({"managed", "legacy_reference", "external", "unknown"})
ROOT_KINDS = frozenset({"source", "managed"})
LOCATION_KINDS = frozenset({"managed", "external", "legacy"})
SOURCE_KINDS = frozenset({"legacy_local", "managed", "external"})
FINGERPRINT_KINDS = frozenset({"sha256", "md5", "phash"})
FINGERPRINT_STATUSES = frozenset({"legacy", "calculated", "verified", "mismatch", "unavailable"})
ADOPTION_STATES = frozenset({"running", "complete", "partial", "failed", "cancelled"})
ADOPTION_OUTCOMES = frozenset(
    {
        "adopted",
        "adopted_exact_only",
        "existing",
        "missing",
        "unsafe_path",
        "unreadable",
        "source_changed",
        "limit_exceeded",
        "hash_mismatch",
        "inspection_failed",
        "storage_integrity_failed",
    }
)
REMOTE_OPERATIONS = frozenset(
    {"fetch_account", "fetch_post", "list_account_posts", "fetch_attribution"}
)
REMOTE_RUN_STATUSES = frozenset({"running", "complete", "paused", "failed"})
REMOTE_OUTCOMES = frozenset(
    {
        "success",
        "unavailable",
        "deleted",
        "authentication_required",
        "authorization_denied",
        "rate_limited",
        "transient_provider",
        "malformed_response",
        "budget_exhausted",
        "local_persistence",
    }
)
BUDGET_BOUNDARIES = frozenset({"request", "page", "record", "time"})
TAG_CATEGORIES = frozenset(
    {"general", "artist", "copyright", "character", "meta", "unknown"}
)
ATTRIBUTION_NAME_KINDS = frozenset({"primary", "alias", "other", "group"})
_SECRET_IDENTITY_MARKERS = (
    "access_token=",
    "refresh_token=",
    "api_key=",
    "apikey=",
    "authorization=",
    "cookie=",
)


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


def validate_identifier_kind(value: str) -> str:
    return _validate_choice(value, IDENTIFIER_KINDS, "identifier kind")


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
    identifier_kind: str = "stable_id"

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        if self.instance_host:
            object.__setattr__(self, "instance_host", validate_instance(self.instance_host))
        validate_object_kind(self.object_kind)
        validate_identifier_kind(self.identifier_kind)
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
    platform: str | None = None
    adapter_version: str | None = None
    schema_version: str | None = None

    def __post_init__(self) -> None:
        if not self.payload:
            raise ValueError("raw payload must not be empty")
        if self.platform is not None:
            validate_platform(self.platform)
        if self.adapter_version is not None:
            _validate_nonempty(self.adapter_version, "raw adapter version", max_length=200)
        if self.schema_version is not None:
            _validate_nonempty(self.schema_version, "raw schema version", max_length=200)
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
            _validate_nonempty(
                self.provider_post_type, "provider post type", max_length=200
            )


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
        object.__setattr__(
            self, "request_started_at", normalize_timestamp(self.request_started_at)
        )
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

    def __post_init__(self) -> None:
        _validate_positive_id(self.remote_run_id, "remote run id")
        validate_remote_operation(self.operation)
        validate_native_id(self.target)
        _validate_nonempty(
            self.continuation_adapter, "continuation adapter", max_length=200
        )
        _validate_nonempty(
            self.continuation_version, "continuation version", max_length=200
        )
        parsed = json.loads(self.continuation_json)
        if not isinstance(parsed, dict):
            raise ValueError("continuation JSON must contain an object")
        if self.last_page_identity is not None:
            validate_secret_free_identity(self.last_page_identity)
        if self.page_count < 0:
            raise ValueError("checkpoint page count must not be negative")
        object.__setattr__(self, "committed_at", normalize_timestamp(self.committed_at))


@dataclass(frozen=True, slots=True)
class TagObservationRecord:
    platform: str
    category: str
    normalized_name: str
    provider_spelling: str
    observed_at: str
    normalization_version: str
    translated_label: str | None = None
    position: int | None = None

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        validate_tag_category(self.category)
        _validate_nonempty(self.normalized_name, "normalized tag", max_length=500)
        _validate_nonempty(self.provider_spelling, "provider tag spelling", max_length=500)
        _validate_nonempty(
            self.normalization_version, "tag normalization version", max_length=200
        )
        if self.translated_label is not None:
            _validate_nonempty(self.translated_label, "translated tag label", max_length=500)
        if self.position is not None and self.position < 0:
            raise ValueError("tag position must not be negative")
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))


@dataclass(frozen=True, slots=True)
class AttributionRecord:
    platform: str
    native_id: str
    adapter_version: str
    observed_at: str
    availability: str = "available"
    instance_host: str = ""
    primary_name: str | None = None
    other_names: tuple[str, ...] = ()
    urls: tuple[str, ...] = ()
    is_deleted: bool | None = None

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        validate_native_id(self.native_id)
        _validate_nonempty(self.adapter_version, "attribution adapter version", max_length=200)
        _validate_nonempty(self.availability, "attribution availability", max_length=200)
        if self.instance_host:
            object.__setattr__(self, "instance_host", validate_instance(self.instance_host))
        if self.primary_name is not None:
            _validate_nonempty(self.primary_name, "attribution name", max_length=500)
        for name in self.other_names:
            _validate_nonempty(name, "attribution alias", max_length=500)
        for url in self.urls:
            _validate_nonempty(url, "attribution URL", max_length=2000)
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))


@dataclass(frozen=True, slots=True)
class PostExternalReferenceRecord:
    reference_kind: str
    observed_at: str
    url: str | None = None
    target_platform: str | None = None
    target_object_kind: str | None = None
    target_identifier_kind: str | None = None
    target_native_id: str | None = None

    def __post_init__(self) -> None:
        if self.reference_kind not in {"source_url", "provider_id"}:
            raise ValueError("unsupported post external reference kind")
        if self.url is None and self.target_native_id is None:
            raise ValueError("post external reference needs a URL or typed target")
        if self.url is not None:
            _validate_nonempty(self.url, "external reference URL", max_length=2000)
        typed = (
            self.target_platform,
            self.target_object_kind,
            self.target_identifier_kind,
            self.target_native_id,
        )
        if any(value is not None for value in typed) and not all(
            value is not None for value in typed
        ):
            raise ValueError("typed external reference fields must be supplied together")
        if self.target_platform is not None:
            validate_platform(self.target_platform)
            validate_object_kind(self.target_object_kind or "")
            validate_identifier_kind(self.target_identifier_kind or "")
            validate_native_id(self.target_native_id or "")
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


def validate_role(role: str) -> str:
    if role not in PARTICIPANT_ROLES:
        raise ValueError(f"unsupported participant role: {role}")
    return role


def validate_event_type(event_type: str) -> str:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported observation event type: {event_type}")
    return event_type


def validate_storage_kind(value: str) -> str:
    return _validate_choice(value, STORAGE_KINDS, "storage kind")


def validate_root_kind(value: str) -> str:
    return _validate_choice(value, ROOT_KINDS, "root kind")


def validate_location_kind(value: str) -> str:
    return _validate_choice(value, LOCATION_KINDS, "location kind")


def validate_source_kind(value: str) -> str:
    return _validate_choice(value, SOURCE_KINDS, "source kind")


def validate_fingerprint_kind(value: str) -> str:
    return _validate_choice(value, FINGERPRINT_KINDS, "fingerprint kind")


def validate_fingerprint_status(value: str) -> str:
    return _validate_choice(value, FINGERPRINT_STATUSES, "fingerprint status")


def validate_adoption_state(value: str) -> str:
    return _validate_choice(value, ADOPTION_STATES, "adoption state")


def validate_adoption_outcome(value: str) -> str:
    return _validate_choice(value, ADOPTION_OUTCOMES, "adoption outcome")


def validate_remote_operation(value: str) -> str:
    return _validate_choice(value, REMOTE_OPERATIONS, "remote operation")


def validate_remote_run_status(value: str) -> str:
    return _validate_choice(value, REMOTE_RUN_STATUSES, "remote run status")


def validate_remote_outcome(value: str) -> str:
    return _validate_choice(value, REMOTE_OUTCOMES, "remote outcome")


def validate_budget_boundary(value: str) -> str:
    return _validate_choice(value, BUDGET_BOUNDARIES, "budget boundary")


def validate_tag_category(value: str) -> str:
    return _validate_choice(value, TAG_CATEGORIES, "tag category")


def validate_attribution_name_kind(value: str) -> str:
    return _validate_choice(value, ATTRIBUTION_NAME_KINDS, "attribution name kind")


def validate_secret_free_identity(value: str) -> str:
    """Accept a canonical provider request identity and reject secret parameters."""

    normalized = _validate_nonempty(value, "request identity", max_length=1000)
    lowered = normalized.lower()
    if any(marker in lowered for marker in _SECRET_IDENTITY_MARKERS):
        raise ValueError("request identity must not contain a secret-bearing parameter")
    return normalized


def _validate_positive_id(value: int, label: str) -> None:
    if value <= 0:
        raise ValueError(f"{label} must be positive")


def _validate_nonempty(value: str, label: str, *, max_length: int | None = None) -> str:
    if not value or not value.strip() or "\x00" in value:
        raise ValueError(f"{label} must not be empty")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"{label} must not exceed {max_length} characters")
    return value
