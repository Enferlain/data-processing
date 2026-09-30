from __future__ import annotations

from dataclasses import dataclass

from media_catalog.records.common import (
    _validate_nonempty,
    normalize_timestamp,
    validate_identifier_kind,
    validate_instance,
    validate_native_id,
    validate_object_kind,
    validate_platform,
    validate_tag_category,
)


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
    provider_tag_id: str | None = None
    native_category: str | None = None
    native_category_code: int | None = None
    post_count: int | None = None
    is_locked: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        validate_tag_category(self.category)
        _validate_nonempty(self.normalized_name, "normalized tag", max_length=500)
        _validate_nonempty(self.provider_spelling, "provider tag spelling", max_length=500)
        _validate_nonempty(self.normalization_version, "tag normalization version", max_length=200)
        if self.translated_label is not None:
            _validate_nonempty(self.translated_label, "translated tag label", max_length=500)
        if self.position is not None and self.position < 0:
            raise ValueError("tag position must not be negative")
        if self.provider_tag_id is not None:
            _validate_nonempty(self.provider_tag_id, "provider tag id", max_length=500)
        if self.native_category is not None:
            _validate_nonempty(self.native_category, "native tag category", max_length=200)
        if self.native_category_code is not None and (
            isinstance(self.native_category_code, bool) or self.native_category_code < 0
        ):
            raise ValueError("native tag category code must not be negative")
        if self.post_count is not None and (
            isinstance(self.post_count, bool) or self.post_count < 0
        ):
            raise ValueError("tag post count must not be negative")
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))
        for name in ("created_at", "updated_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, normalize_timestamp(value))


@dataclass(frozen=True, slots=True)
class TagAliasObservationRecord:
    platform: str
    provider_alias_id: str
    antecedent_name: str
    consequent_name: str
    status: str
    observed_at: str
    post_count: int | None = None
    creator_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    reason: str | None = None
    forum_topic_id: int | None = None

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        for name in (
            "provider_alias_id",
            "antecedent_name",
            "consequent_name",
            "status",
        ):
            _validate_nonempty(getattr(self, name), name.replace("_", " "), max_length=500)
        if self.post_count is not None and (
            isinstance(self.post_count, bool) or self.post_count < 0
        ):
            raise ValueError("tag alias post count must not be negative")
        if self.creator_id is not None:
            _validate_nonempty(self.creator_id, "tag alias creator id", max_length=500)
        if self.reason is not None:
            _validate_nonempty(self.reason, "tag alias reason", max_length=1000)
        if self.forum_topic_id is not None and (
            isinstance(self.forum_topic_id, bool) or self.forum_topic_id < 0
        ):
            raise ValueError("tag alias forum topic id must not be negative")
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))
        for name in ("created_at", "updated_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, normalize_timestamp(value))


@dataclass(frozen=True, slots=True)
class PostMetadataObservationRecord:
    observed_at: str
    score_up: int | None = None
    score_down: int | None = None
    score_total: int | None = None
    favorite_count: int | None = None
    comment_count: int | None = None
    flag_deleted: bool | None = None
    flag_pending: bool | None = None
    flag_flagged: bool | None = None

    def __post_init__(self) -> None:
        for name in ("score_up", "score_down", "favorite_count", "comment_count"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or value < 0):
                raise ValueError(f"post {name} must not be negative")
        if self.score_total is not None and isinstance(self.score_total, bool):
            raise ValueError("post score total must be an integer")
        for name in ("flag_deleted", "flag_pending", "flag_flagged"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"post {name} must be boolean")
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))


@dataclass(frozen=True, slots=True)
class PostPoolObservationRecord:
    pool_native_id: str
    observed_at: str

    def __post_init__(self) -> None:
        _validate_nonempty(self.pool_native_id, "pool native id", max_length=500)
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))


@dataclass(frozen=True, slots=True)
class PostFlagObservationRecord:
    flag_name: str
    flag_value: bool
    observed_at: str

    def __post_init__(self) -> None:
        _validate_nonempty(self.flag_name, "post flag name", max_length=200)
        if not isinstance(self.flag_value, bool):
            raise ValueError("post flag value must be boolean")
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
    is_banned: bool | None = None
    is_locked: bool | None = None
    linked_user_id: str | None = None
    domains: tuple[str, ...] = ()
    created_at: str | None = None
    updated_at: str | None = None
    group_name: str | None = None

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        validate_native_id(self.native_id)
        _validate_nonempty(self.adapter_version, "attribution adapter version", max_length=200)
        _validate_nonempty(self.availability, "attribution availability", max_length=200)
        if self.instance_host:
            object.__setattr__(self, "instance_host", validate_instance(self.instance_host))
        if self.primary_name is not None:
            _validate_nonempty(self.primary_name, "attribution name", max_length=500)
        if self.group_name is not None:
            _validate_nonempty(self.group_name, "attribution group name", max_length=500)
        for name in self.other_names:
            _validate_nonempty(name, "attribution alias", max_length=500)
        for url in self.urls:
            _validate_nonempty(url, "attribution URL", max_length=2000)
        for domain in self.domains:
            _validate_nonempty(domain, "attribution domain", max_length=500)
        if self.linked_user_id is not None:
            _validate_nonempty(self.linked_user_id, "linked user id", max_length=500)
        for name in ("is_deleted", "is_banned", "is_locked"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{name} must be boolean")
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))
        for name in ("created_at", "updated_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, normalize_timestamp(value))


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
