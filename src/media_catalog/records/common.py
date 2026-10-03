from __future__ import annotations

import re
from datetime import UTC, datetime

from media_catalog.adapters.contracts import validate_transport_pair as validate_transport_pair

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
REMOTE_OPERATIONS = frozenset(
    {
        "fetch_account",
        "fetch_post",
        "list_account_posts",
        "fetch_attribution",
        "fetch_tag",
        "fetch_tag_alias",
    }
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
TAG_CATEGORIES = frozenset({"general", "artist", "copyright", "character", "meta", "unknown"})
ATTRIBUTION_NAME_KINDS = frozenset({"primary", "alias", "other", "group"})
LIBRARY_ORIGIN_KINDS = frozenset({"library_expansion"})
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


def validate_role(role: str) -> str:
    if role not in PARTICIPANT_ROLES:
        raise ValueError(f"unsupported participant role: {role}")
    return role


def validate_event_type(event_type: str) -> str:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported observation event type: {event_type}")
    return event_type


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


def validate_library_origin_kind(value: str) -> str:
    return _validate_choice(value, LIBRARY_ORIGIN_KINDS, "library origin kind")


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


def _validate_opaque_leaf(value: str, label: str) -> str:
    normalized = _validate_nonempty(value, label, max_length=200)
    if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError(f"{label} must be an opaque path leaf")
    return normalized
