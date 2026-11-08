from __future__ import annotations

from dataclasses import dataclass

from media_catalog.records.common import (
    REMOTE_OUTCOMES,
    _validate_choice,
    normalize_timestamp,
    validate_evidence_direction,
    validate_evidence_stance,
    validate_evidence_strength,
    validate_identifier_kind,
    validate_instance,
    validate_native_id,
    validate_object_kind,
    validate_platform,
    validate_relation,
    validate_review_state,
    validate_source_context,
    validate_version,
)


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
        if self.subject_kind not in {"account", "attribution", "post"}:
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


SEARCH_ATTEMPT_STATUSES = frozenset({"running", "complete", "failed"})
SEARCH_ATTEMPT_OUTCOMES = frozenset(REMOTE_OUTCOMES | {"error", "provider_failure"})


def validate_search_attempt_status(value: str) -> str:
    return _validate_choice(value, SEARCH_ATTEMPT_STATUSES, "search attempt status")


def validate_search_attempt_outcome(value: str) -> str:
    return _validate_choice(value, SEARCH_ATTEMPT_OUTCOMES, "search attempt outcome")


@dataclass(frozen=True, slots=True)
class SearchAttemptRecord:
    """One durable cross-session search attempt (the freshness ledger row)."""

    source_kind: str
    source: str
    method: str
    strategy_version: str
    query_digest: str
    status: str
    started_at: str
    discovery_session_id: int
    subject_post_id: int | None = None
    subject_account_id: int | None = None
    subject_file_id: int | None = None
    outcome: str | None = None
    result_count: int = 0
    scope: str | None = None
    requests_used: int = 0
    discovery_step_id: int | None = None
    candidate_lookup_run_id: int | None = None
    finished_at: str | None = None

    def __post_init__(self) -> None:
        subjects = (
            self.subject_post_id,
            self.subject_account_id,
            self.subject_file_id,
        )
        if sum(value is not None for value in subjects) != 1:
            raise ValueError("a search attempt requires exactly one subject id")
        for name, value in (
            ("source kind", self.source_kind),
            ("source", self.source),
            ("method", self.method),
        ):
            if not value or not value.strip():
                raise ValueError(f"search attempt {name} must not be empty")
        validate_version(self.strategy_version)
        if len(self.query_digest) != 64 or any(
            char not in "0123456789abcdefABCDEF" for char in self.query_digest
        ):
            raise ValueError("search attempt query digest must be 64 hex characters")
        validate_search_attempt_status(self.status)
        if self.outcome is not None:
            validate_search_attempt_outcome(self.outcome)
        for name, value in (
            ("result count", self.result_count),
            ("requests used", self.requests_used),
        ):
            if value < 0:
                raise ValueError(f"search attempt {name} must not be negative")
        if self.scope is not None and len(self.scope) > 1000:
            raise ValueError("search attempt scope exceeds 1000 characters")
        if self.status == "running" and self.finished_at is not None:
            raise ValueError("a running search attempt must not carry a finish time")
        if self.status != "running" and self.finished_at is None:
            raise ValueError("a finished search attempt requires a finish time")
        object.__setattr__(self, "started_at", normalize_timestamp(self.started_at))
        if self.finished_at is not None:
            object.__setattr__(self, "finished_at", normalize_timestamp(self.finished_at))
