from __future__ import annotations

import json
from dataclasses import dataclass

from media_catalog.records.common import (
    INSTANCE_PATTERN,
    _validate_choice,
    _validate_nonempty,
    _validate_positive_id,
    normalize_timestamp,
    validate_hash,
    validate_platform,
    validate_secret_free_identity,
)

LOOKUP_STRATEGIES = frozenset(
    {
        "source_post_url",
        "external_post_id",
        "declared_md5",
        "verified_md5",
        "artist_exact_name",
        "artist_alias",
        "artist_text",
    }
)
LOOKUP_RUN_STATUSES = frozenset({"running", "complete", "paused", "failed"})
LOOKUP_REQUEST_STATES = frozenset({"running", "complete", "failed"})
LOOKUP_OUTCOMES = frozenset(
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
LOOKUP_BUDGET_BOUNDARIES = frozenset({"request", "page", "result", "time"})
LOOKUP_RESULT_KINDS = frozenset(
    {"post_match", "account_match", "attribution", "weak_lead", "inconclusive"}
)
LOOKUP_MATCH_MODES = frozenset({"exact", "alias", "handle", "display_name", "text"})


def validate_lookup_strategy(value: str) -> str:
    return _validate_choice(value, LOOKUP_STRATEGIES, "lookup strategy")


def validate_lookup_run_status(value: str) -> str:
    return _validate_choice(value, LOOKUP_RUN_STATUSES, "lookup run status")


def validate_lookup_request_state(value: str) -> str:
    return _validate_choice(value, LOOKUP_REQUEST_STATES, "lookup request state")


def validate_lookup_outcome(value: str) -> str:
    return _validate_choice(value, LOOKUP_OUTCOMES, "lookup outcome")


def validate_lookup_budget_boundary(value: str) -> str:
    return _validate_choice(value, LOOKUP_BUDGET_BOUNDARIES, "lookup budget boundary")


def validate_lookup_result_kind(value: str) -> str:
    return _validate_choice(value, LOOKUP_RESULT_KINDS, "lookup result kind")


def validate_lookup_match_mode(value: str) -> str:
    return _validate_choice(value, LOOKUP_MATCH_MODES, "lookup match mode")


@dataclass(frozen=True, slots=True)
class CandidateLookupRunRecord:
    platform: str
    instance_host: str
    strategy: str
    strategy_version: str
    adapter_version: str
    schema_version: str
    seed_revision: str
    plan_digest: str
    query_kind: str
    material_digest: str
    private_query_json: str
    request_limit: int
    page_limit: int
    result_limit: int
    time_limit_seconds: int
    started_at: str
    seed_account_id: int | None = None
    seed_post_id: int | None = None
    predecessor_run_id: int | None = None

    def __post_init__(self) -> None:
        validate_platform(self.platform)
        if self.instance_host and not INSTANCE_PATTERN.fullmatch(self.instance_host):
            raise ValueError("lookup instance host is invalid")
        validate_lookup_strategy(self.strategy)
        for value in (self.strategy_version, self.adapter_version, self.schema_version):
            _validate_nonempty(value, "lookup version", max_length=200)
        if (self.seed_account_id is None) == (self.seed_post_id is None):
            raise ValueError("lookup run requires exactly one seed")
        for value, label in (
            (self.seed_account_id, "seed account id"),
            (self.seed_post_id, "seed post id"),
            (self.predecessor_run_id, "predecessor run id"),
        ):
            if value is not None:
                _validate_positive_id(value, label)
        _validate_nonempty(self.seed_revision, "seed revision", max_length=200)
        object.__setattr__(self, "plan_digest", validate_hash(self.plan_digest, 64))
        _validate_nonempty(self.query_kind, "query kind", max_length=200)
        object.__setattr__(self, "material_digest", validate_hash(self.material_digest, 64))
        parsed = json.loads(self.private_query_json)
        if not isinstance(parsed, dict):
            raise ValueError("private lookup query must be a JSON object")
        for value, label in (
            (self.request_limit, "request limit"),
            (self.page_limit, "page limit"),
            (self.result_limit, "result limit"),
            (self.time_limit_seconds, "time limit"),
        ):
            _validate_positive_id(value, label)
        object.__setattr__(self, "started_at", normalize_timestamp(self.started_at))


@dataclass(frozen=True, slots=True)
class CandidateLookupRequestRecord:
    candidate_lookup_run_id: int
    attempt_number: int
    request_identity: str
    state: str
    started_at: str
    outcome: str | None = None
    status_code: int | None = None
    retry_after: str | None = None
    response_size: int | None = None
    raw_observation_id: int | None = None
    candidate_lookup_checkpoint_id: int | None = None
    observed_at: str | None = None
    finished_at: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.candidate_lookup_run_id, "lookup run id")
        _validate_positive_id(self.attempt_number, "lookup attempt number")
        validate_secret_free_identity(self.request_identity)
        validate_lookup_request_state(self.state)
        if self.outcome is not None:
            validate_lookup_outcome(self.outcome)
        if self.state == "running":
            if self.outcome is not None or self.finished_at is not None:
                raise ValueError("running lookup request cannot be terminal")
        elif self.outcome is None or self.finished_at is None:
            raise ValueError("terminal lookup request requires outcome and finish time")
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ValueError("HTTP status code must be between 100 and 599")
        if self.response_size is not None and self.response_size < 0:
            raise ValueError("response size must not be negative")
        for value, label in (
            (self.raw_observation_id, "raw observation id"),
            (self.candidate_lookup_checkpoint_id, "lookup checkpoint id"),
        ):
            if value is not None:
                _validate_positive_id(value, label)
        object.__setattr__(self, "started_at", normalize_timestamp(self.started_at))
        for name in ("retry_after", "observed_at", "finished_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, normalize_timestamp(value))


@dataclass(frozen=True, slots=True)
class CandidateLookupCheckpointRecord:
    candidate_lookup_run_id: int
    continuation_adapter: str
    continuation_version: str
    continuation_json: str
    page_count: int
    result_count: int
    committed_at: str
    last_page_identity: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.candidate_lookup_run_id, "lookup run id")
        _validate_nonempty(self.continuation_adapter, "continuation adapter", max_length=200)
        _validate_nonempty(self.continuation_version, "continuation version", max_length=200)
        if not isinstance(json.loads(self.continuation_json), dict):
            raise ValueError("lookup continuation must be a JSON object")
        for value, label in (
            (self.page_count, "page count"),
            (self.result_count, "result count"),
        ):
            if value < 0:
                raise ValueError(f"{label} must not be negative")
        if self.last_page_identity is not None:
            validate_secret_free_identity(self.last_page_identity)
        object.__setattr__(self, "committed_at", normalize_timestamp(self.committed_at))


@dataclass(frozen=True, slots=True)
class CandidateLookupResultRecord:
    candidate_lookup_run_id: int
    result_kind: str
    result_digest: str
    page_number: int
    result_order: int
    raw_observation_id: int
    observed_at: str
    normalized_post_id: int | None = None
    attribution_entity_id: int | None = None
    platform_reference_id: int | None = None
    post_candidate_id: int | None = None
    account_candidate_id: int | None = None
    match_evidence_id: int | None = None
    normalized_name: str | None = None
    match_mode: str | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        _validate_positive_id(self.candidate_lookup_run_id, "lookup run id")
        validate_lookup_result_kind(self.result_kind)
        object.__setattr__(self, "result_digest", validate_hash(self.result_digest, 64))
        _validate_positive_id(self.page_number, "lookup page number")
        if self.result_order < 0:
            raise ValueError("lookup result order must not be negative")
        _validate_positive_id(self.raw_observation_id, "raw observation id")
        for value, label in (
            (self.normalized_post_id, "normalized post id"),
            (self.attribution_entity_id, "attribution entity id"),
            (self.platform_reference_id, "platform reference id"),
            (self.post_candidate_id, "post candidate id"),
            (self.account_candidate_id, "account candidate id"),
            (self.match_evidence_id, "match evidence id"),
        ):
            if value is not None:
                _validate_positive_id(value, label)
        if self.match_mode is not None:
            validate_lookup_match_mode(self.match_mode)
        if self.normalized_name is not None:
            _validate_nonempty(self.normalized_name, "normalized lookup name", max_length=500)
        if self.explanation is not None:
            _validate_nonempty(self.explanation, "lookup explanation", max_length=1000)
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at))
