from __future__ import annotations

from dataclasses import dataclass

from media_catalog.records.common import (
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
